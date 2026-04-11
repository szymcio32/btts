"""Game-start order cancellation detection and sell re-placement."""

from __future__ import annotations

import logging
import threading
import time

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.config import TimingConfig
from btts_bot.core.game_lifecycle import GameState, InvalidTransitionError
from btts_bot.logging_setup import create_market_logger
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

# States that are already handled or terminal — nothing to do at game start
_TERMINAL_STATES = frozenset(
    {
        GameState.GAME_STARTED,
        GameState.RECOVERY_COMPLETE,
        GameState.DONE,
        GameState.SKIPPED,
        GameState.EXPIRED,
    }
)


class GameStartService:
    """Detects Polymarket's automatic order cancellation at game start and re-places sell orders.

    At game start, Polymarket automatically cancels ALL open orders. This service:
    1. Unconditionally removes any stale sell record (Polymarket cancelled it)
    2. Places a new sell at buy_price for the full accumulated position (with retry)
    3. Transitions the game to GAME_STARTED
    4. Verifies the sell is active after sell_verify_interval_seconds and retries until confirmed

    Runs in a dedicated daemon thread per game — concurrent games are handled concurrently
    without blocking the APScheduler thread pool.
    """

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        timing_config: TimingConfig,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry
        self._timing = timing_config
        self._inflight_lock = threading.Lock()
        self._inflight_tokens: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_game_start(self, token_id: str) -> None:
        """Main game-start recovery handler for a single game.

        Wraps _do_game_start_recovery in a try/except to ensure the recovery
        thread never dies silently — a crash here would leave the position unmanaged.
        """
        if not self._acquire_inflight(token_id):
            logger.debug(
                "Game-start recovery already in progress for token=%s, skipping duplicate trigger",
                token_id,
            )
            return

        try:
            self._do_game_start_recovery(token_id)
        except Exception:
            logger.exception(
                "Game-start recovery FAILED for token=%s — position may be unmanaged",
                token_id,
            )
        finally:
            self._release_inflight(token_id)

    # ------------------------------------------------------------------
    # Internal recovery logic
    # ------------------------------------------------------------------

    def _do_game_start_recovery(self, token_id: str) -> None:
        """Dispatch to state-specific recovery path."""
        entry = self._market_registry.get(token_id)

        if entry is None:
            logger.warning(
                "Game-start recovery: no registry entry for token=%s, skipping",
                token_id,
            )
            return

        mlog = create_market_logger(__name__, entry.home_team, entry.away_team, token_id)
        state = entry.lifecycle.state

        # Already handled or terminal — nothing to do
        if state in _TERMINAL_STATES:
            mlog.debug(
                "Game-start recovery: game already in %s, skipping",
                state.value,
            )
            return

        # DISCOVERED / ANALYSED — no position was ever started
        if state in (GameState.DISCOVERED, GameState.ANALYSED):
            mlog.debug(
                "Game-start recovery: game in %s (no position), skipping",
                state.value,
            )
            return

        # Normal path: pre-kickoff succeeded (PRE_KICKOFF)
        if state == GameState.PRE_KICKOFF:
            self._handle_pre_kickoff_state(token_id, mlog, entry)
        # Pre-kickoff failed: sell was live but pre-kickoff didn't complete
        elif state == GameState.SELL_PLACED:
            self._handle_sell_placed_state(token_id, mlog, entry)
        # Pre-kickoff failed: had fills but no sell placed yet
        elif state == GameState.FILLING:
            self._handle_filling_state(token_id, mlog, entry)
        # Pre-kickoff failed: buy may still be active/partially filled
        elif state == GameState.BUY_PLACED:
            self._handle_buy_placed_state(token_id, mlog, entry)
        else:
            mlog.warning(
                "Game-start recovery: unexpected state %s",
                state.value,
            )

    # ------------------------------------------------------------------
    # State-specific handlers
    # ------------------------------------------------------------------

    def _handle_pre_kickoff_state(
        self, token_id: str, mlog: logging.LoggerAdapter, entry: object
    ) -> None:
        """PRE_KICKOFF path (normal): Polymarket cancelled sell at game start, re-place it."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.error("Game-start recovery PRE_KICKOFF: no buy record")
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No position to protect
            entry.lifecycle.transition(GameState.DONE)
            mlog.info("No position at game start -- nothing to recover")
            return

        # Polymarket cancelled old sell — remove stale record and re-place
        self._order_tracker.remove_sell_order(token_id)
        self._place_sell_and_transition(
            token_id, mlog, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_sell_placed_state(
        self, token_id: str, mlog: logging.LoggerAdapter, entry: object
    ) -> None:
        """SELL_PLACED path: pre-kickoff failed, sell was live but Polymarket cancelled it."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.error("Game-start recovery SELL_PLACED: no buy record")
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # Edge case: no fills — transition to DONE
            self._order_tracker.remove_sell_order(token_id)
            entry.lifecycle.transition(GameState.DONE)
            mlog.info("No position at game start -- nothing to recover")
            return

        # Remove old (now-cancelled) sell record and re-place at buy_price
        self._order_tracker.remove_sell_order(token_id)
        self._place_sell_and_transition(
            token_id, mlog, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_filling_state(
        self, token_id: str, mlog: logging.LoggerAdapter, entry: object
    ) -> None:
        """FILLING path: pre-kickoff failed, had fills but no sell placed yet."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.error("Game-start recovery FILLING: no buy record")
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No fills — transition to DONE
            entry.lifecycle.transition(GameState.DONE)
            mlog.info("No position at game start -- nothing to recover")
            return

        # Cancel active buy (Polymarket may have already cancelled it — handle gracefully)
        self._cancel_buy_if_active(token_id, mlog)
        self._order_tracker.mark_inactive(token_id)

        # Place sell at buy_price for accumulated fills
        self._place_sell_and_transition(
            token_id, mlog, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_buy_placed_state(
        self, token_id: str, mlog: logging.LoggerAdapter, entry: object
    ) -> None:
        """BUY_PLACED path: pre-kickoff failed, buy may be active/partially filled."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            mlog.warning("Game-start recovery BUY_PLACED: no buy record, skipping")
            return

        # Mark buy as inactive — Polymarket already cancelled it at game start
        self._order_tracker.mark_inactive(token_id)

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No fills — no position to protect
            entry.lifecycle.transition(GameState.DONE)
            mlog.info("No position at game start -- nothing to recover")
            return

        # Race condition fills: buy was partially filled before cancellation
        self._place_sell_and_transition(
            token_id, mlog, entry, buy_record.buy_price, accumulated_fills
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _place_sell_and_transition(
        self,
        token_id: str,
        mlog: logging.LoggerAdapter,
        entry: object,
        buy_price: float,
        sell_size: float,
    ) -> None:
        """Place a sell at buy_price (capped at 0.99) and transition to GAME_STARTED.

        Retries indefinitely until sell placement succeeds (position safety is paramount).
        Uses record_sell_if_absent for atomic duplicate prevention (thread-safety).
        After successful placement and transition, calls _verify_and_retry_sell() to
        confirm the sell is active on the CLOB.
        """
        sell_price = min(buy_price, 0.99)

        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)

        retry_count = 0
        order_id = ""
        while not order_id:
            if result is None:
                retry_count += 1
                mlog.warning(
                    "Game-start recovery: sell placement failed, retrying #%d",
                    retry_count,
                )
                time.sleep(self._timing.sell_verify_interval_seconds)
                result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
                continue

            order_id = self._extract_order_id(result)
            if order_id:
                break

            retry_count += 1
            mlog.error(
                "Game-start recovery: sell posted but no orderID, retrying #%d",
                retry_count,
            )
            time.sleep(self._timing.sell_verify_interval_seconds)
            result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)

        # Atomic record — if another thread already placed a sell, False is returned
        # (race condition handled gracefully: another thread succeeded, recovery done)
        recorded = self._order_tracker.record_sell_if_absent(
            token_id, order_id, sell_price, sell_size
        )
        if not recorded:
            mlog.info("Game-start recovery: sell already recorded by another thread")

        try:
            entry.lifecycle.transition(GameState.GAME_STARTED)
        except InvalidTransitionError:
            if entry.lifecycle.state == GameState.GAME_STARTED:
                mlog.debug("Game-start recovery: GAME_STARTED already set by another path")
            else:
                raise
        mlog.info(
            "Game-start recovery: sell re-placed at buy_price=%.4f, size=%.2f",
            sell_price,
            sell_size,
        )

        # Verify sell is active; retry until confirmed (AC #1-#3)
        self._verify_and_retry_sell(token_id, mlog, entry, buy_price, sell_size)

    def _is_sell_active(self, order_id: str, mlog: logging.LoggerAdapter) -> bool:
        """Check if a sell order is still active on the CLOB.

        Returns True if the order is live/open or matched (filled).
        Returns False if cancelled, missing, or API error.
        """
        order_data = self._clob_client.get_order(order_id)
        if order_data is None:
            mlog.warning(
                "Sell verification: get_order returned None for order=%s",
                order_id,
            )
            return False

        # py-clob-client returns order data with various status fields
        status_obj: object = ""
        if hasattr(order_data, "status"):
            status_obj = order_data.status
        elif hasattr(order_data, "order_status"):
            status_obj = order_data.order_status
        elif isinstance(order_data, dict):
            status_obj = order_data.get("status")
            if status_obj is None:
                status_obj = order_data.get("order_status", "")

        status = str(status_obj or "")

        if status.upper() in ("LIVE", "OPEN", "MATCHED"):
            return True

        mlog.warning(
            "Sell verification: order=%s has status=%s (not active)",
            order_id,
            status,
        )
        return False

    def _verify_and_retry_sell(
        self,
        token_id: str,
        mlog: logging.LoggerAdapter,
        entry: object,
        buy_price: float,
        sell_size: float,
    ) -> None:
        """Verify sell order is active after placement; retry until confirmed (AC #1-#3).

        Sleeps sell_verify_interval_seconds, then checks order status via get_order().
        If active: transitions to RECOVERY_COMPLETE, logs INFO, returns.
        If not active: re-places sell, loops until confirmed.
        No maximum retry limit — position safety is paramount.
        """
        sell_record = self._order_tracker.get_sell_order(token_id)
        retry_count = 0
        current_order_id = sell_record.order_id if sell_record is not None else ""

        if not current_order_id:
            mlog.warning(
                "Verify: no sell record after placement, attempting re-placement",
            )

        while True:
            if current_order_id:
                time.sleep(self._timing.sell_verify_interval_seconds)

                if self._is_sell_active(current_order_id, mlog):
                    try:
                        entry.lifecycle.transition(GameState.RECOVERY_COMPLETE)
                    except InvalidTransitionError:
                        if entry.lifecycle.state == GameState.RECOVERY_COMPLETE:
                            mlog.debug("RECOVERY_COMPLETE already set")
                        else:
                            raise
                    mlog.info("Game-start recovery verified -- sell confirmed active")
                    return

                # Sell is not active — re-place immediately
                self._order_tracker.remove_sell_order(token_id)

            retry_count += 1
            mlog.warning("Sell verification failed -- retry #%d", retry_count)

            sell_price = min(buy_price, 0.99)

            result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
            if result is None:
                mlog.error(
                    "Sell re-placement failed on retry #%d",
                    retry_count,
                )
                # Don't return — keep looping, next iteration will try again
                current_order_id = ""
                continue

            order_id = self._extract_order_id(result)
            if not order_id:
                mlog.error(
                    "Sell re-placement returned no orderID on retry #%d",
                    retry_count,
                )
                current_order_id = ""
                continue

            self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)
            current_order_id = order_id
            # Loop continues — will sleep and verify the new sell

    def _extract_order_id(self, result: object) -> str:
        """Extract order id from CLOB response variants."""
        if isinstance(result, dict):
            for key in ("orderID", "orderId", "id"):
                raw_order_id = result.get(key)
                if isinstance(raw_order_id, str) and raw_order_id:
                    return raw_order_id

        for attr in ("orderID", "orderId", "order_id", "id"):
            if hasattr(result, attr):
                raw_order_id = getattr(result, attr)
                if isinstance(raw_order_id, str) and raw_order_id:
                    return raw_order_id

        return ""

    def _cancel_buy_if_active(self, token_id: str, mlog: logging.LoggerAdapter) -> bool:
        """Attempt to cancel the active buy if one exists.

        Returns True if no active buy or cancellation attempt was made (even if it failed).
        Polymarket may have already cancelled it at game start — failure is handled gracefully.
        """
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None or not buy_record.active:
            return True

        cancel_result = self._clob_client.cancel_order(buy_record.order_id)
        if cancel_result is None:
            mlog.warning(
                "Game-start recovery: cancel of buy order=%s returned None -- "
                "Polymarket likely already cancelled it at game start",
                buy_record.order_id,
            )
        return True

    def _acquire_inflight(self, token_id: str) -> bool:
        """Return True if this call acquired ownership of recovery for token_id."""
        with self._inflight_lock:
            if token_id in self._inflight_tokens:
                return False
            self._inflight_tokens.add(token_id)
            return True

    def _release_inflight(self, token_id: str) -> None:
        """Release recovery ownership for token_id."""
        with self._inflight_lock:
            self._inflight_tokens.discard(token_id)
