"""Order execution logic for placing buy/sell orders."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.liquidity import AnalysisResult
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OrderExecutionService:
    """Places buy and sell orders with duplicate prevention."""

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        btts_config: BttsConfig,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry
        self._btts = btts_config

    def place_buy_order(self, token_id: str, buy_price: float, sell_price: float) -> bool:
        """Place a limit buy order for a single token.

        Returns True if order was placed successfully, False otherwise.
        """
        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
        )

        # Duplicate prevention (AC #3)
        if self._order_tracker.has_buy_order(token_id):
            logger.warning(
                "%s Duplicate buy prevented (token=%s)",
                market_name,
                token_id,
            )
            return False

        if entry is None:
            logger.warning("[%s] Buy skipped: market entry not found", token_id)
            return False

        if entry.lifecycle.state != GameState.ANALYSED:
            logger.warning(
                "%s Buy skipped: expected ANALYSED state, got %s",
                market_name,
                entry.lifecycle.state.value,
            )
            return False

        # Calculate GTD expiration: kickoff time minus offset hours
        kickoff_ts = int(entry.kickoff_time.timestamp())
        expiration_ts = kickoff_ts - self._btts.expiration_hour_offset * 3600
        now_ts = int(time.time())
        if expiration_ts <= now_ts:
            logger.error(
                "%s Buy skipped: computed expiration is not in the future "
                "(expiration=%d, now=%d, kickoff=%d, offset_hours=%d)",
                market_name,
                expiration_ts,
                now_ts,
                kickoff_ts,
                self._btts.expiration_hour_offset,
            )
            entry.lifecycle.transition(GameState.SKIPPED)
            return False

        # Trigger py-clob-client tick-size cache warmup for this token.
        # Order creation also resolves tick size internally, but this explicit
        # fetch keeps Story 3.1 behavior aligned with the intended flow.
        try:
            self._clob_client.get_tick_size(token_id)
        except Exception as exc:  # pragma: no cover - defensive, non-fatal path
            logger.warning(
                "%s Tick size prefetch failed for token=%s: %s",
                market_name,
                token_id,
                exc,
            )

        # Place buy order via CLOB (AC #2)
        try:
            result = self._clob_client.create_buy_order(
                token_id=token_id,
                price=buy_price,
                size=float(self._btts.order_size),
                expiration_ts=expiration_ts,
            )
        except Exception as exc:
            logger.error(
                "%s Buy order failed with non-retryable error: token=%s price=%.4f error=%s",
                market_name,
                token_id,
                buy_price,
                exc,
            )
            entry.lifecycle.transition(GameState.SKIPPED)
            return False

        if result is None:
            # API failure after retries (AC #4)
            logger.error(
                "%s Buy order failed (retry exhausted): token=%s price=%.4f",
                market_name,
                token_id,
                buy_price,
            )
            entry.lifecycle.transition(GameState.SKIPPED)
            return False

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Buy order posted but no orderID in response: token=%s",
                market_name,
                token_id,
            )
            entry.lifecycle.transition(GameState.SKIPPED)
            return False

        # Record and transition
        self._order_tracker.record_buy(token_id, order_id, buy_price, sell_price)
        entry.lifecycle.transition(GameState.BUY_PLACED)
        logger.info(
            "%s Buy order placed: token=%s, price=%.4f, size=%d, order=%s",
            market_name,
            token_id,
            buy_price,
            self._btts.order_size,
            order_id,
        )
        return True

    def execute_all_analysed(self, analysis_results: list[AnalysisResult]) -> int:
        """Place buy orders for all analysed markets.

        Returns count of successfully placed orders.
        """
        results_by_token: dict[str, AnalysisResult] = {}
        for result in analysis_results:
            if result.token_id in results_by_token:
                logger.warning(
                    "Duplicate analysis result for token=%s; using first occurrence",
                    result.token_id,
                )
                continue
            results_by_token[result.token_id] = result

        placed_count = 0
        for entry in self._market_registry.all_markets():
            if entry.lifecycle.state != GameState.ANALYSED:
                continue
            result = results_by_token.get(entry.token_id)
            if result is None:
                continue
            if self.place_buy_order(entry.token_id, result.buy_price, result.sell_price):
                placed_count += 1
        return placed_count

    def place_sell_order(self, token_id: str) -> bool:
        """Place a GTC limit sell order for accumulated fills on a token.

        Returns True if order was placed successfully, False otherwise.
        """
        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
        )

        # Duplicate prevention (AC #2)
        if self._order_tracker.has_sell_order(token_id):
            logger.debug(
                "%s Duplicate sell prevented -- live sell exists",
                market_name,
            )
            return False

        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            logger.error(
                "%s Sell skipped: no buy order record found for token=%s",
                market_name,
                token_id,
            )
            return False

        # Use pre-computed sell_price from buy record, capped at 0.99 (AC #1)
        sell_price = min(buy_record.sell_price, 0.99)

        # Sell size equals total accumulated fills (AC #1)
        sell_size = self._position_tracker.get_accumulated_fills(token_id)

        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)

        if result is None:
            # Do NOT transition to SKIPPED — position still needs to be managed
            logger.error(
                "%s Sell order failed (retry exhausted): token=%s price=%.4f size=%.2f",
                market_name,
                token_id,
                sell_price,
                sell_size,
            )
            return False

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Sell order posted but no orderID in response: token=%s",
                market_name,
                token_id,
            )
            return False

        self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)

        # Transition FILLING -> SELL_PLACED (only on first sell)
        if entry is not None:
            entry.lifecycle.transition(GameState.SELL_PLACED)

        logger.info(
            "%s Sell order placed: token=%s, price=%.4f, size=%.2f",
            market_name,
            token_id,
            sell_price,
            sell_size,
        )
        return True

    def update_sell_order(self, token_id: str) -> bool:
        """Cancel existing sell and re-place for updated accumulated fill size.

        Returns True if the sell was successfully updated, False otherwise.
        """
        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
        )

        existing_record = self._order_tracker.get_sell_order(token_id)
        if existing_record is None:
            logger.debug(
                "%s update_sell_order: no existing sell order for token=%s",
                market_name,
                token_id,
            )
            return False

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)

        # No update needed if accumulated fills don't exceed existing sell size (AC #3)
        if accumulated_fills <= existing_record.sell_size:
            return False

        # Cancel existing sell
        cancel_result = self._clob_client.cancel_order(existing_record.order_id)
        if cancel_result is None:
            logger.error(
                "%s Sell update failed: cancel of order=%s returned None, keeping old sell",
                market_name,
                existing_record.order_id,
            )
            return False

        # Remove old record before placing new sell
        self._order_tracker.remove_sell_order(token_id)

        # Place new sell for full accumulated amount at same price
        sell_price = existing_record.sell_price
        result = self._clob_client.create_sell_order(token_id, sell_price, accumulated_fills)

        if result is None:
            logger.error(
                "%s Sell update: cancel succeeded but new sell failed for token=%s — "
                "position temporarily has no sell coverage",
                market_name,
                token_id,
            )
            return False

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Sell update posted but no orderID in response: token=%s",
                market_name,
                token_id,
            )
            return False

        self._order_tracker.record_sell(token_id, order_id, sell_price, accumulated_fills)

        logger.info(
            "%s Sell order updated: token=%s, new_size=%.2f, old_size=%.2f",
            market_name,
            token_id,
            accumulated_fills,
            existing_record.sell_size,
        )
        return True
