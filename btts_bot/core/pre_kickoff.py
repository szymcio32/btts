"""Pre-kickoff sell consolidation and buy cancellation."""

from __future__ import annotations

import logging

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.core.game_lifecycle import GameState
from btts_bot.logging_setup import create_market_logger
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

# Terminal / post-processing states — nothing to do at pre-kickoff
_TERMINAL_STATES = frozenset(
    {
        GameState.PRE_KICKOFF,
        GameState.GAME_STARTED,
        GameState.RECOVERY_COMPLETE,
        GameState.DONE,
        GameState.SKIPPED,
        GameState.EXPIRED,
    }
)


class PreKickoffService:
    """Consolidates sell orders and cancels unfilled buys before kickoff.

    Runs as an APScheduler DateTrigger callback — one invocation per game,
    fired at ``kickoff_time - pre_kickoff_minutes``.
    """

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_pre_kickoff(self, token_id: str) -> None:
        """Main pre-kickoff handler for a single game.

        Dispatches to the appropriate path based on current game state.
        Designed to be idempotent: checks state before acting.
        """
        entry = self._market_registry.get(token_id)

        if entry is None:
            logger.warning(
                "Pre-kickoff handler: no registry entry for token=%s, skipping",
                token_id,
            )
            return

        mlog = create_market_logger(__name__, entry.home_team, entry.away_team, token_id)
        state = entry.lifecycle.state

        # Already handled or terminal — nothing to do
        if state in _TERMINAL_STATES:
            mlog.debug(
                "Pre-kickoff handler: game already in %s, skipping",
                state.value,
            )
            return

        # DISCOVERED / ANALYSED — buy was never placed; nothing to manage
        if state in (GameState.DISCOVERED, GameState.ANALYSED):
            mlog.debug(
                "Pre-kickoff handler: game in %s (no position), skipping",
                state.value,
            )
            return

        if state == GameState.SELL_PLACED:
            self._handle_sell_placed(token_id, mlog, entry)
        elif state == GameState.FILLING:
            self._handle_filling(token_id, mlog, entry)
        elif state == GameState.BUY_PLACED:
            self._handle_buy_placed(token_id, mlog, entry)
        else:
            mlog.warning(
                "Pre-kickoff handler: unexpected state %s",
                state.value,
            )

    # ------------------------------------------------------------------
    # State-specific handlers
    # ------------------------------------------------------------------

    def _handle_sell_placed(
        self, token_id: str, mlog: logging.LoggerAdapter, entry: object
    ) -> None:
        """SELL_PLACED path: cancel existing sell, re-create at buy_price (AC #2)."""
        existing_sell = self._order_tracker.get_sell_order(token_id)
        if existing_sell is None:
            mlog.error(
                "Pre-kickoff SELL_PLACED: no sell record found",
            )
            return

        # Step 1: Cancel existing sell
        cancel_result = self._clob_client.cancel_order(existing_sell.order_id)
        if cancel_result is None:
            mlog.error(
                "Pre-kickoff consolidation failed: cancel of sell order=%s returned None "
                "-- game left in SELL_PLACED for game-start recovery",
                existing_sell.order_id,
            )
            return

        # Step 2: Remove old sell record
        self._order_tracker.remove_sell_order(token_id)

        # Step 3: Get buy_price (NOT sell_price) and accumulated fills
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.error(
                "Pre-kickoff consolidation: no buy record after sell cancel",
            )
            return

        sell_price = min(buy_record.buy_price, 0.99)
        sell_size = self._position_tracker.get_accumulated_fills(token_id)

        # Step 4: Place new consolidated sell at buy_price
        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
        if result is None:
            mlog.error(
                "Pre-kickoff consolidation failed: new sell order failed "
                "(price=%.4f size=%.2f) -- position has no sell coverage; "
                "game left in SELL_PLACED for game-start recovery",
                sell_price,
                sell_size,
            )
            return

        order_id = result.get("orderID", "")
        if not order_id:
            mlog.error("Pre-kickoff consolidation: sell order posted but no orderID")
            return

        self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)

        # Step 5: Cancel active buy (may have been partially filled)
        if not self._cancel_buy_if_active(token_id, mlog):
            return

        # Step 6: Transition to PRE_KICKOFF
        entry.lifecycle.transition(GameState.PRE_KICKOFF)
        mlog.info(
            "Pre-kickoff consolidation: sell at buy_price=%.4f, size=%.2f",
            sell_price,
            sell_size,
        )

    def _handle_filling(self, token_id: str, mlog: logging.LoggerAdapter, entry: object) -> None:
        """FILLING path: place sell at buy_price for accumulated fills, cancel buy (AC #4)."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.error("Pre-kickoff FILLING: no buy record")
            return

        sell_price = min(buy_record.buy_price, 0.99)
        sell_size = self._position_tracker.get_accumulated_fills(token_id)

        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
        if result is None:
            mlog.error(
                "Pre-kickoff FILLING: sell order failed "
                "(price=%.4f size=%.2f) -- game left in FILLING for game-start recovery",
                sell_price,
                sell_size,
            )
            return

        order_id = result.get("orderID", "")
        if not order_id:
            mlog.error("Pre-kickoff FILLING: sell order posted but no orderID")
            return

        self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)

        # Cancel active buy
        if not self._cancel_buy_if_active(token_id, mlog):
            return

        # Transition to PRE_KICKOFF
        entry.lifecycle.transition(GameState.PRE_KICKOFF)
        mlog.info(
            "Pre-kickoff consolidation: sell at buy_price=%.4f, size=%.2f",
            sell_price,
            sell_size,
        )

    def _handle_buy_placed(self, token_id: str, mlog: logging.LoggerAdapter, entry: object) -> None:
        """BUY_PLACED path: cancel buy, transition to PRE_KICKOFF / DONE (AC #3)."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.warning("Pre-kickoff BUY_PLACED: no buy record, skipping")
            return

        # Cancel the unfilled buy
        cancel_result = self._clob_client.cancel_order(buy_record.order_id)
        if cancel_result is None:
            mlog.error(
                "Pre-kickoff BUY_PLACED: cancel of buy order=%s returned None",
                buy_record.order_id,
            )
            return
        self._order_tracker.mark_inactive(token_id)
        mlog.info("Pre-kickoff buy cancelled")

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)

        if accumulated_fills <= 0.0:
            # No position — transition to PRE_KICKOFF then DONE
            entry.lifecycle.transition(GameState.PRE_KICKOFF)
            entry.lifecycle.transition(GameState.DONE)
        else:
            # Race condition: fills arrived concurrently — place a sell at buy_price
            sell_price = min(buy_record.buy_price, 0.99)
            result = self._clob_client.create_sell_order(token_id, sell_price, accumulated_fills)
            if result is None:
                mlog.error(
                    "Pre-kickoff BUY_PLACED: sell for race-condition fills failed "
                    "(price=%.4f size=%.2f)",
                    sell_price,
                    accumulated_fills,
                )
                return

            order_id = result.get("orderID", "")
            if not order_id:
                mlog.error("Pre-kickoff BUY_PLACED: sell posted but no orderID")
                return

            self._order_tracker.record_sell(token_id, order_id, sell_price, accumulated_fills)
            entry.lifecycle.transition(GameState.PRE_KICKOFF)
            mlog.info(
                "Pre-kickoff consolidation: sell at buy_price=%.4f, size=%.2f",
                sell_price,
                accumulated_fills,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cancel_buy_if_active(self, token_id: str, mlog: logging.LoggerAdapter) -> bool:
        """Cancel the active buy order if one exists, then mark it inactive.

        Returns True if no active buy existed or cancellation succeeded.
        Returns False if cancellation failed and the game should stay in current state.
        """
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None or not buy_record.active:
            return True

        cancel_result = self._clob_client.cancel_order(buy_record.order_id)
        if cancel_result is None:
            mlog.error(
                "Pre-kickoff: cancel of buy order=%s returned None -- "
                "buy may still be live on exchange",
                buy_record.order_id,
            )
            return False
        self._order_tracker.mark_inactive(token_id)
        mlog.info("Pre-kickoff buy cancelled")
        return True
