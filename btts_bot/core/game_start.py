"""Game-start order cancellation detection and sell re-placement."""

from __future__ import annotations

import logging
import threading

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.core.game_lifecycle import GameState, InvalidTransitionError
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
    2. Places a new sell at buy_price for the full accumulated position
    3. Transitions the game to GAME_STARTED

    Runs in a dedicated daemon thread per game — concurrent games are handled concurrently
    without blocking the APScheduler thread pool.
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
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
        )

        if entry is None:
            logger.warning(
                "Game-start recovery: no registry entry for token=%s, skipping",
                token_id,
            )
            return

        state = entry.lifecycle.state

        # Already handled or terminal — nothing to do
        if state in _TERMINAL_STATES:
            logger.debug(
                "%s Game-start recovery: game already in %s, skipping",
                market_name,
                state.value,
            )
            return

        # DISCOVERED / ANALYSED — no position was ever started
        if state in (GameState.DISCOVERED, GameState.ANALYSED):
            logger.debug(
                "%s Game-start recovery: game in %s (no position), skipping",
                market_name,
                state.value,
            )
            return

        # Normal path: pre-kickoff succeeded (PRE_KICKOFF)
        if state == GameState.PRE_KICKOFF:
            self._handle_pre_kickoff_state(token_id, market_name, entry)
        # Pre-kickoff failed: sell was live but pre-kickoff didn't complete
        elif state == GameState.SELL_PLACED:
            self._handle_sell_placed_state(token_id, market_name, entry)
        # Pre-kickoff failed: had fills but no sell placed yet
        elif state == GameState.FILLING:
            self._handle_filling_state(token_id, market_name, entry)
        # Pre-kickoff failed: buy may still be active/partially filled
        elif state == GameState.BUY_PLACED:
            self._handle_buy_placed_state(token_id, market_name, entry)
        else:
            logger.warning(
                "%s Game-start recovery: unexpected state %s for token=%s",
                market_name,
                state.value,
                token_id,
            )

    # ------------------------------------------------------------------
    # State-specific handlers
    # ------------------------------------------------------------------

    def _handle_pre_kickoff_state(self, token_id: str, market_name: str, entry: object) -> None:
        """PRE_KICKOFF path (normal): Polymarket cancelled sell at game start, re-place it."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            logger.error(
                "%s Game-start recovery PRE_KICKOFF: no buy record for token=%s",
                market_name,
                token_id,
            )
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No position to protect
            entry.lifecycle.transition(GameState.DONE)
            logger.info(
                "%s No position at game start -- nothing to recover",
                market_name,
            )
            return

        # Polymarket cancelled old sell — remove stale record and re-place
        self._order_tracker.remove_sell_order(token_id)
        self._place_sell_and_transition(
            token_id, market_name, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_sell_placed_state(self, token_id: str, market_name: str, entry: object) -> None:
        """SELL_PLACED path: pre-kickoff failed, sell was live but Polymarket cancelled it."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            logger.error(
                "%s Game-start recovery SELL_PLACED: no buy record for token=%s",
                market_name,
                token_id,
            )
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # Edge case: no fills — transition to DONE
            self._order_tracker.remove_sell_order(token_id)
            entry.lifecycle.transition(GameState.DONE)
            logger.info(
                "%s No position at game start -- nothing to recover",
                market_name,
            )
            return

        # Remove old (now-cancelled) sell record and re-place at buy_price
        self._order_tracker.remove_sell_order(token_id)
        self._place_sell_and_transition(
            token_id, market_name, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_filling_state(self, token_id: str, market_name: str, entry: object) -> None:
        """FILLING path: pre-kickoff failed, had fills but no sell placed yet."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            logger.error(
                "%s Game-start recovery FILLING: no buy record for token=%s",
                market_name,
                token_id,
            )
            return

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No fills — transition to DONE
            entry.lifecycle.transition(GameState.DONE)
            logger.info(
                "%s No position at game start -- nothing to recover",
                market_name,
            )
            return

        # Cancel active buy (Polymarket may have already cancelled it — handle gracefully)
        self._cancel_buy_if_active(token_id, market_name)
        self._order_tracker.mark_inactive(token_id)

        # Place sell at buy_price for accumulated fills
        self._place_sell_and_transition(
            token_id, market_name, entry, buy_record.buy_price, accumulated_fills
        )

    def _handle_buy_placed_state(self, token_id: str, market_name: str, entry: object) -> None:
        """BUY_PLACED path: pre-kickoff failed, buy may be active/partially filled."""
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None:
            logger.warning(
                "%s Game-start recovery BUY_PLACED: no buy record for token=%s, skipping",
                market_name,
                token_id,
            )
            return

        # Mark buy as inactive — Polymarket already cancelled it at game start
        self._order_tracker.mark_inactive(token_id)

        accumulated_fills = self._position_tracker.get_accumulated_fills(token_id)
        if accumulated_fills <= 0.0:
            # No fills — no position to protect
            entry.lifecycle.transition(GameState.DONE)
            logger.info(
                "%s No position at game start -- nothing to recover",
                market_name,
            )
            return

        # Race condition fills: buy was partially filled before cancellation
        self._place_sell_and_transition(
            token_id, market_name, entry, buy_record.buy_price, accumulated_fills
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _place_sell_and_transition(
        self,
        token_id: str,
        market_name: str,
        entry: object,
        buy_price: float,
        sell_size: float,
    ) -> None:
        """Place a sell at buy_price (capped at 0.99) and transition to GAME_STARTED.

        Uses record_sell_if_absent for atomic duplicate prevention (thread-safety).
        If sell placement fails: logs ERROR but does NOT transition (Story 4.3 retry
        loop will handle it).
        """
        sell_price = min(buy_price, 0.99)

        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
        if result is None:
            logger.error(
                "%s Game-start recovery: sell order failed for token=%s "
                "(price=%.4f size=%.2f) — Story 4.3 retry will handle",
                market_name,
                token_id,
                sell_price,
                sell_size,
            )
            return

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Game-start recovery: sell posted but no orderID for token=%s",
                market_name,
                token_id,
            )
            return

        # Atomic record — if another thread already placed a sell, False is returned
        # (race condition handled gracefully: another thread succeeded, recovery done)
        recorded = self._order_tracker.record_sell_if_absent(
            token_id, order_id, sell_price, sell_size
        )
        if not recorded:
            logger.info(
                "%s Game-start recovery: sell already recorded by another thread for token=%s",
                market_name,
                token_id,
            )

        try:
            entry.lifecycle.transition(GameState.GAME_STARTED)
        except InvalidTransitionError:
            if entry.lifecycle.state == GameState.GAME_STARTED:
                logger.debug(
                    "%s Game-start recovery: GAME_STARTED already set by another path for token=%s",
                    market_name,
                    token_id,
                )
            else:
                raise
        logger.info(
            "%s Game-start recovery: sell re-placed at buy_price=%.4f, size=%.2f",
            market_name,
            sell_price,
            sell_size,
        )

    def _cancel_buy_if_active(self, token_id: str, market_name: str) -> bool:
        """Attempt to cancel the active buy if one exists.

        Returns True if no active buy or cancellation attempt was made (even if it failed).
        Polymarket may have already cancelled it at game start — failure is handled gracefully.
        """
        buy_record = self._order_tracker.get_buy_order(token_id)
        if buy_record is None or not buy_record.active:
            return True

        cancel_result = self._clob_client.cancel_order(buy_record.order_id)
        if cancel_result is None:
            logger.warning(
                "%s Game-start recovery: cancel of buy order=%s returned None (token=%s) — "
                "Polymarket likely already cancelled it at game start",
                market_name,
                buy_record.order_id,
                token_id,
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
