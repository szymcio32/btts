"""Fill polling service for tracking buy order fill accumulation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from btts_bot.clients.clob import ClobClientWrapper
    from btts_bot.config import BttsConfig
    from btts_bot.core.order_execution import OrderExecutionService
    from btts_bot.state.market_registry import MarketRegistry
    from btts_bot.state.order_tracker import BuyOrderRecord, OrderTracker
    from btts_bot.state.position_tracker import PositionTracker

from btts_bot.core.game_lifecycle import GameState
from btts_bot.logging_setup import create_market_logger, create_token_logger

logger = logging.getLogger(__name__)

# CLOB order statuses indicating the order is no longer active
_TERMINAL_STATUSES = frozenset({"MATCHED", "CANCELED", "INVALID", "CANCELED_MARKET_RESOLVED"})


def _parse_fixed_math(value: str) -> float:
    """Convert CLOB fixed-math string (6 decimals) to float shares."""
    return int(value) / 1_000_000


class FillPollingService:
    """Polls CLOB API for buy order fills and accumulates in PositionTracker."""

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        btts_config: BttsConfig,
        order_execution_service: OrderExecutionService,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry
        self._btts = btts_config
        self._order_execution = order_execution_service

    def poll_all_active_orders(self) -> None:
        """Poll all active buy orders for fills. Called by scheduler."""
        active_orders = self._order_tracker.get_active_buy_orders()
        if not active_orders:
            return
        for buy_record in active_orders:
            self._poll_single_order(buy_record)

    def _poll_single_order(self, buy_record: BuyOrderRecord) -> None:
        """Poll a single buy order for fill progress."""
        token_id = buy_record.token_id
        order_id = buy_record.order_id

        entry = self._market_registry.get(token_id)
        if entry is not None:
            mlog = create_market_logger(__name__, entry.home_team, entry.away_team, token_id)
        else:
            mlog = create_token_logger(__name__, token_id)

        try:
            # Only poll orders in active buy lifecycle states.
            # SELL_PLACED is included because buy fills can continue after first sell.
            if entry is not None and entry.lifecycle.state not in (
                GameState.BUY_PLACED,
                GameState.FILLING,
                GameState.SELL_PLACED,
            ):
                return

            # Query CLOB API
            order = self._clob_client.get_order(order_id)
            if order is None:
                mlog.warning(
                    "Fill poll failed (retry exhausted): order=%s",
                    order_id,
                )
                return

            # Parse fill amounts
            current_filled = _parse_fixed_math(order.size_matched)
            original_size = _parse_fixed_math(order.original_size)
            previously_accumulated = self._position_tracker.get_accumulated_fills(token_id)
            delta = current_filled - previously_accumulated

            # Accumulate new fills
            if delta > 0:
                self._position_tracker.accumulate(token_id, delta)
                mlog.info(
                    "Fill detected: +%.2f shares (total: %.2f / %.2f) order=%s",
                    delta,
                    current_filled,
                    original_size,
                    order_id,
                )
                # Transition BUY_PLACED -> FILLING on first fill
                if entry is not None and entry.lifecycle.state == GameState.BUY_PLACED:
                    entry.lifecycle.transition(GameState.FILLING)

                # Check sell threshold after new fills (AC #1, #3)
                self._check_and_trigger_sell(token_id)

            # Handle terminal order statuses or fully-filled size match
            order_status = order.status
            is_fully_filled = current_filled >= original_size
            if order_status in _TERMINAL_STATUSES or is_fully_filled:
                self._order_tracker.mark_inactive(token_id)
                accumulated = self._position_tracker.get_accumulated_fills(token_id)
                if order_status != "MATCHED" and accumulated == 0.0:
                    # Expired/cancelled with zero fills
                    if entry is not None and entry.lifecycle.state in (
                        GameState.BUY_PLACED,
                        GameState.FILLING,
                    ):
                        entry.lifecycle.transition(GameState.EXPIRED)
                        mlog.info(
                            "Buy order expired with no fills: order=%s",
                            order_id,
                        )
                else:
                    # Fully matched — ensure sell exists if threshold met (AC #1, #3)
                    if order_status == "MATCHED":
                        self._check_and_trigger_sell(token_id)
        except Exception as exc:
            mlog.warning(
                "Fill poll failed for order=%s: %s",
                order_id,
                exc,
            )

    def _check_and_trigger_sell(self, token_id: str) -> None:
        """Check fill threshold and trigger sell placement or update."""
        if not self._position_tracker.has_reached_threshold(token_id, self._btts.min_order_size):
            return

        if not self._order_tracker.has_sell_order(token_id):
            self._order_execution.place_sell_order(token_id)
        else:
            self._order_execution.update_sell_order(token_id)
