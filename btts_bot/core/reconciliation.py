"""Startup state reconciliation from Polymarket API."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.clients.data_api import DataApiClient
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.scheduling import SchedulerService
from btts_bot.logging_setup import create_market_logger, create_token_logger
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

# Order statuses considered "active" (open on the exchange)
_ACTIVE_STATUSES = frozenset({"LIVE", "OPEN", "MATCHED"})


class ReconciliationService:
    """Rebuilds bot internal state from the Polymarket API on startup.

    Reconciliation flow:
    1. Query CLOB for all open orders → populate OrderTracker
    2. Query Data API for all positions → populate PositionTracker
    3. Register markets in MarketRegistry with appropriate lifecycle state
    4. Cross-reference: any position with no matching sell → place sell immediately

    Follows best-effort semantics: a failure in any individual step is logged
    and execution continues so the bot can still start (AC #5).
    """

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        data_api_client: DataApiClient,
        gamma_client: GammaClient,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        scheduler_service: SchedulerService,
        btts_config: BttsConfig,
    ) -> None:
        self._clob = clob_client
        self._data_api = data_api_client
        self._gamma = gamma_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._registry = market_registry
        self._scheduler = scheduler_service
        self._btts_config = btts_config

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def reconcile(self) -> None:
        """Run the full reconciliation sequence.

        Completes within 60 seconds under normal conditions (NFR3).
        """
        start_ts = time.monotonic()
        logger.info("Reconciliation starting...")

        # ----------------------------------------------------------------
        # Step 1: Query CLOB for open orders
        # ----------------------------------------------------------------
        open_orders: list[dict] = []
        try:
            result = self._clob.get_open_orders()
            if result is None:
                logger.critical(
                    "Reconciliation: CLOB API returned no orders after retries — "
                    "starting with empty order state. Manual review may be needed."
                )
            else:
                open_orders = result if isinstance(result, list) else []
                logger.info("Reconciliation: %d open orders fetched from CLOB", len(open_orders))
        except Exception as exc:
            logger.critical(
                "Reconciliation: unexpected error fetching open orders: %s — "
                "starting with empty order state. Manual review may be needed.",
                exc,
            )

        # ----------------------------------------------------------------
        # Step 2: Query Data API for positions
        # ----------------------------------------------------------------
        positions: list[dict] = []
        try:
            result = self._data_api.get_positions()
            if result is None:
                logger.critical(
                    "Reconciliation: Data API returned no positions after retries — "
                    "starting with empty position state. Manual review may be needed."
                )
            else:
                positions = result if isinstance(result, list) else []
                logger.info("Reconciliation: %d positions fetched from Data API", len(positions))
        except Exception as exc:
            logger.critical(
                "Reconciliation: unexpected error fetching positions: %s — "
                "starting with empty position state. Manual review may be needed.",
                exc,
            )

        # ----------------------------------------------------------------
        # Step 3: Build a token_id → game metadata lookup from JSON file
        # ----------------------------------------------------------------
        token_to_game: dict[str, dict] = self._build_token_game_lookup()

        # ----------------------------------------------------------------
        # Step 4: Classify orders by side and token
        # ----------------------------------------------------------------
        buy_orders: dict[str, dict] = {}  # token_id → order dict
        sell_orders: dict[str, dict] = {}  # token_id → order dict

        for order in open_orders:
            if not isinstance(order, dict):
                continue
            status = (order.get("status") or order.get("orderStatus") or "").upper()
            if status not in _ACTIVE_STATUSES:
                continue

            token_id: str = (
                order.get("asset_id") or order.get("token_id") or order.get("asset") or ""
            )
            if not token_id:
                continue

            side: str = (order.get("side") or "").upper()
            if side == "BUY":
                buy_orders[token_id] = order
            elif side == "SELL":
                sell_orders[token_id] = order

        # ----------------------------------------------------------------
        # Step 5: Populate OrderTracker
        # ----------------------------------------------------------------
        for token_id, order in buy_orders.items():
            try:
                order_id = order.get("id") or order.get("orderID") or order.get("order_id") or ""
                buy_price = float(order.get("price") or 0)
                sell_price = min(buy_price + self._btts_config.price_diff, 0.99)
                self._order_tracker.record_buy(token_id, order_id, buy_price, sell_price)
            except Exception as exc:
                logger.error(
                    "Reconciliation: failed to record buy order for token=%s: %s",
                    token_id,
                    exc,
                )

        for token_id, order in sell_orders.items():
            try:
                order_id = order.get("id") or order.get("orderID") or order.get("order_id") or ""
                sell_price = float(order.get("price") or 0)
                sell_size = float(
                    order.get("original_size")
                    or order.get("size")
                    or order.get("size_matched")
                    or 0
                )
                self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)
            except Exception as exc:
                logger.error(
                    "Reconciliation: failed to record sell order for token=%s: %s",
                    token_id,
                    exc,
                )

        # ----------------------------------------------------------------
        # Step 6: Populate PositionTracker
        # ----------------------------------------------------------------
        # Build a map of token_id → position size from Data API
        position_by_token: dict[str, float] = {}
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            token_id = pos.get("asset") or pos.get("token_id") or pos.get("asset_id") or ""
            if not token_id:
                continue
            try:
                size = float(pos.get("size") or pos.get("amount") or 0)
            except TypeError, ValueError:
                size = 0.0
            if size > 0:
                position_by_token[token_id] = size
                self._position_tracker.set_position(token_id, size)

        # ----------------------------------------------------------------
        # Step 7: Register markets in MarketRegistry + schedule triggers
        # ----------------------------------------------------------------
        # All token_ids that have any order or position
        all_token_ids = set(buy_orders) | set(sell_orders) | set(position_by_token)

        for token_id in all_token_ids:
            try:
                self._register_market(
                    token_id=token_id,
                    token_to_game=token_to_game,
                    buy_orders=buy_orders,
                    sell_orders=sell_orders,
                    position_by_token=position_by_token,
                )
            except Exception as exc:
                logger.error(
                    "Reconciliation: failed to register market for token=%s: %s",
                    token_id,
                    exc,
                )

        # ----------------------------------------------------------------
        # Step 8: Cross-reference — orphaned positions (position, no sell)
        # ----------------------------------------------------------------
        for token_id, pos_size in position_by_token.items():
            if self._order_tracker.has_sell_order(token_id):
                continue  # sell already exists

            # Orphaned position: must place sell immediately
            try:
                buy_record = self._order_tracker.get_buy_order(token_id)
                if buy_record is not None:
                    sell_price = buy_record.buy_price
                    sell_at = buy_record.buy_price
                else:
                    # No buy record either — use a fallback sell price
                    # Try to derive from sell_orders (edge case: position only, no current orders)
                    sell_at = 0.50  # safe fallback
                    sell_price = sell_at

                game = token_to_game.get(token_id)
                if game:
                    mlog = create_market_logger(
                        __name__,
                        game.get("home_team", "Unknown"),
                        game.get("away_team", "Unknown"),
                        token_id,
                    )
                else:
                    mlog = create_token_logger(__name__, token_id)

                sell_response = self._clob.create_sell_order(token_id, sell_price, pos_size)
                if sell_response is not None:
                    sell_order_id = (
                        sell_response.get("orderID")
                        or sell_response.get("id")
                        or sell_response.get("order_id")
                        or ""
                    )
                    self._order_tracker.record_sell(token_id, sell_order_id, sell_price, pos_size)
                    mlog.warning(
                        "Orphaned position detected -- sell placed at buy_price=%.4f, size=%.2f",
                        sell_at,
                        pos_size,
                    )
                else:
                    mlog.error(
                        "Orphaned position detected but sell placement failed (retries exhausted)"
                        " -- manual intervention required. size=%.2f",
                        pos_size,
                    )
            except Exception as exc:
                logger.error(
                    "Reconciliation: unexpected error placing orphan sell for token=%s: %s",
                    token_id,
                    exc,
                )

        elapsed = time.monotonic() - start_ts
        logger.info("Reconciliation complete in %.2fs", elapsed)
        if elapsed > 60:
            logger.warning("Reconciliation exceeded 60s NFR3 target (took %.2fs)", elapsed)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_token_game_lookup(self) -> dict[str, dict]:
        """Build a token_id → game dict mapping from the JSON data file."""
        lookup: dict[str, dict] = {}
        try:
            games = self._gamma.fetch_games()
            if games is None:
                logger.warning(
                    "Reconciliation: could not load game data file — "
                    "market metadata will be unavailable during reconciliation"
                )
                return lookup

            for game in games:
                if not isinstance(game, dict):
                    continue
                polymarket = game.get("polymarket", {})
                if not isinstance(polymarket, dict):
                    continue
                markets = polymarket.get("markets", [])
                if not isinstance(markets, list):
                    continue
                for market in markets:
                    if not isinstance(market, dict):
                        continue
                    token_ids = market.get("token_ids", [])
                    if not isinstance(token_ids, list):
                        continue
                    for tid in token_ids:
                        if isinstance(tid, str) and tid:
                            lookup[tid] = {
                                "home_team": game.get("home_team", "Unknown"),
                                "away_team": game.get("away_team", "Unknown"),
                                "league": game.get("league", "unknown"),
                                "kickoff_utc": game.get("kickoff_utc", ""),
                                "condition_id": market.get("condition_id", ""),
                                "token_ids": token_ids,
                            }
        except Exception as exc:
            logger.warning("Reconciliation: error building token→game lookup: %s", exc)
        return lookup

    def _register_market(
        self,
        token_id: str,
        token_to_game: dict[str, dict],
        buy_orders: dict[str, dict],
        sell_orders: dict[str, dict],
        position_by_token: dict[str, float],
    ) -> None:
        """Register a market in MarketRegistry and advance to correct lifecycle state."""
        # Skip if already registered (idempotent — e.g., token_ids that share condition_id)
        if self._registry.is_processed(token_id):
            return

        game = token_to_game.get(token_id)
        if game is None:
            # No metadata available — still track orders/positions but skip registry registration
            logger.warning(
                "Reconciliation: no game metadata for token=%s — "
                "market will not be registered in MarketRegistry or have triggers scheduled",
                token_id,
            )
            return

        # Parse kickoff time
        kickoff_time = self._parse_kickoff(game.get("kickoff_utc", ""))
        if kickoff_time is None:
            logger.warning(
                "Reconciliation: could not parse kickoff_utc for token=%s — skipping registration",
                token_id,
            )
            return

        condition_id = game.get("condition_id", "")
        if not condition_id:
            logger.warning(
                "Reconciliation: missing condition_id for token=%s — skipping registration",
                token_id,
            )
            return

        entry = self._registry.register(
            token_id=token_id,
            condition_id=condition_id,
            token_ids=game.get("token_ids", [token_id]),
            kickoff_time=kickoff_time,
            league=game.get("league", "unknown"),
            home_team=game.get("home_team", "Unknown"),
            away_team=game.get("away_team", "Unknown"),
        )

        # Advance lifecycle to the correct state via valid sequential transitions
        # DISCOVERED (initial)
        has_buy = token_id in buy_orders
        has_position = token_id in position_by_token
        has_sell = token_id in sell_orders

        # Always advance to ANALYSED
        entry.lifecycle.transition(GameState.ANALYSED)

        if has_buy or has_position or has_sell:
            # Advance to BUY_PLACED
            entry.lifecycle.transition(GameState.BUY_PLACED)

        if has_position or has_sell:
            # Advance to FILLING
            entry.lifecycle.transition(GameState.FILLING)

        if has_sell:
            # Advance to SELL_PLACED
            entry.lifecycle.transition(GameState.SELL_PLACED)

        # Schedule pre-kickoff and game-start triggers
        self._scheduler.schedule_pre_kickoff(token_id, kickoff_time)
        self._scheduler.schedule_game_start(token_id, kickoff_time)

        mlog = create_market_logger(
            __name__,
            game.get("home_team", "Unknown"),
            game.get("away_team", "Unknown"),
            token_id,
        )
        mlog.info(
            "Reconciliation: registered with state=%s (buy=%s pos=%s sell=%s)",
            entry.lifecycle.state.value,
            has_buy,
            has_position,
            has_sell,
        )

    @staticmethod
    def _parse_kickoff(kickoff_value: object) -> datetime | None:
        """Parse kickoff_utc string to timezone-aware datetime."""
        if not isinstance(kickoff_value, str) or not kickoff_value:
            return None
        try:
            parsed = datetime.fromisoformat(kickoff_value.replace("Z", "+00:00"))
        except ValueError, TypeError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
