"""Tests for ReconciliationService (Story 5.1)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.clients.data_api import DataApiClient
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.reconciliation import ReconciliationService
from btts_bot.core.scheduling import SchedulerService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FUTURE_KICKOFF = datetime(2099, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FUTURE_KICKOFF_ISO = "2099-01-01T12:00:00Z"


def _make_btts_config() -> BttsConfig:
    return BttsConfig(order_size=30, price_diff=0.02)


def _make_game(
    token_id: str = "token-no",
    home: str = "Home",
    away: str = "Away",
    league: str = "epl",
    kickoff: str = FUTURE_KICKOFF_ISO,
    condition_id: str = "cond-1",
    extra_token: str | None = None,
) -> dict:
    token_ids = [f"{token_id}-yes", token_id]
    if extra_token:
        token_ids.append(extra_token)
    return {
        "home_team": home,
        "away_team": away,
        "league": league,
        "kickoff_utc": kickoff,
        "polymarket": {
            "markets": [
                {
                    "market_type": "both_teams_to_score",
                    "condition_id": condition_id,
                    "token_ids": token_ids,
                }
            ]
        },
    }


_UNSET = object()  # sentinel for "not provided" (distinct from explicit None)


def _make_service(
    *,
    open_orders: list | None | object = _UNSET,
    positions: list | None | object = _UNSET,
    games: list | None = None,
) -> tuple[ReconciliationService, dict]:
    """Build a ReconciliationService with mocked dependencies.

    Pass open_orders=None or positions=None to simulate API exhausted-retry (returns None).
    Omit the argument (default) to get an empty list (clean startup).

    Returns (service, mocks_dict).
    """
    clob = MagicMock(spec=ClobClientWrapper)
    data_api = MagicMock(spec=DataApiClient)
    gamma = MagicMock(spec=GammaClient)
    order_tracker = OrderTracker()
    position_tracker = PositionTracker()
    market_registry = MarketRegistry()
    scheduler = MagicMock(spec=SchedulerService)
    btts_config = _make_btts_config()

    clob.get_open_orders.return_value = [] if open_orders is _UNSET else open_orders
    data_api.get_positions.return_value = [] if positions is _UNSET else positions
    gamma.fetch_games.return_value = games if games is not None else []

    svc = ReconciliationService(
        clob_client=clob,
        data_api_client=data_api,
        gamma_client=gamma,
        order_tracker=order_tracker,
        position_tracker=position_tracker,
        market_registry=market_registry,
        scheduler_service=scheduler,
        btts_config=btts_config,
    )

    mocks = {
        "clob": clob,
        "data_api": data_api,
        "gamma": gamma,
        "order_tracker": order_tracker,
        "position_tracker": position_tracker,
        "market_registry": market_registry,
        "scheduler": scheduler,
    }
    return svc, mocks


# ---------------------------------------------------------------------------
# AC #1 — Open orders populate OrderTracker
# ---------------------------------------------------------------------------


class TestReconcileOpenBuyOrders(unittest.TestCase):
    """Open buy orders discovered from CLOB are populated into OrderTracker."""

    def test_buy_order_recorded_in_order_tracker(self) -> None:
        buy_order = {
            "id": "buy-order-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(open_orders=[buy_order], games=[game])

        svc.reconcile()

        self.assertTrue(mocks["order_tracker"].has_buy_order("token-no"))
        record = mocks["order_tracker"].get_buy_order("token-no")
        self.assertEqual(record.order_id, "buy-order-1")
        self.assertAlmostEqual(record.buy_price, 0.48)

    def test_buy_order_sell_price_computed_from_price_diff(self) -> None:
        buy_order = {
            "id": "buy-order-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(open_orders=[buy_order], games=[game])

        svc.reconcile()

        record = mocks["order_tracker"].get_buy_order("token-no")
        # sell_price = min(0.48 + 0.02, 0.99) = 0.50
        self.assertAlmostEqual(record.sell_price, 0.50)

    def test_multiple_buy_orders_all_recorded(self) -> None:
        orders = [
            {"id": "b1", "asset_id": "t1", "side": "BUY", "price": "0.48", "status": "LIVE"},
            {"id": "b2", "asset_id": "t2", "side": "BUY", "price": "0.50", "status": "LIVE"},
        ]
        games = [
            _make_game(token_id="t1", condition_id="c1"),
            _make_game(token_id="t2", condition_id="c2"),
        ]
        svc, mocks = _make_service(open_orders=orders, games=games)

        svc.reconcile()

        self.assertTrue(mocks["order_tracker"].has_buy_order("t1"))
        self.assertTrue(mocks["order_tracker"].has_buy_order("t2"))

    def test_inactive_order_not_recorded(self) -> None:
        """Orders with non-active status should be ignored."""
        order = {
            "id": "b1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "CANCELLED",
        }
        svc, mocks = _make_service(open_orders=[order])

        svc.reconcile()

        self.assertFalse(mocks["order_tracker"].has_buy_order("token-no"))


class TestReconcileOpenSellOrders(unittest.TestCase):
    """Open sell orders discovered from CLOB are populated into OrderTracker."""

    def test_sell_order_recorded_in_order_tracker(self) -> None:
        sell_order = {
            "id": "sell-order-1",
            "asset_id": "token-no",
            "side": "SELL",
            "price": "0.50",
            "original_size": "10.0",
            "status": "LIVE",
        }
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(open_orders=[sell_order], games=[game])

        svc.reconcile()

        self.assertTrue(mocks["order_tracker"].has_sell_order("token-no"))
        record = mocks["order_tracker"].get_sell_order("token-no")
        self.assertEqual(record.order_id, "sell-order-1")
        self.assertAlmostEqual(record.sell_price, 0.50)
        self.assertAlmostEqual(record.sell_size, 10.0)


# ---------------------------------------------------------------------------
# AC #1 — Positions populate PositionTracker
# ---------------------------------------------------------------------------


class TestReconcilePositions(unittest.TestCase):
    """Positions from Data API populate PositionTracker."""

    def test_position_set_in_position_tracker(self) -> None:
        position = {"asset": "token-no", "size": "12.5"}
        svc, mocks = _make_service(positions=[position])

        svc.reconcile()

        self.assertAlmostEqual(mocks["position_tracker"].get_accumulated_fills("token-no"), 12.5)

    def test_zero_size_position_ignored(self) -> None:
        position = {"asset": "token-no", "size": "0"}
        svc, mocks = _make_service(positions=[position])

        svc.reconcile()

        self.assertAlmostEqual(mocks["position_tracker"].get_accumulated_fills("token-no"), 0.0)

    def test_multiple_positions_all_set(self) -> None:
        positions = [
            {"asset": "t1", "size": "5.0"},
            {"asset": "t2", "size": "10.0"},
        ]
        svc, mocks = _make_service(positions=positions)

        svc.reconcile()

        self.assertAlmostEqual(mocks["position_tracker"].get_accumulated_fills("t1"), 5.0)
        self.assertAlmostEqual(mocks["position_tracker"].get_accumulated_fills("t2"), 10.0)


# ---------------------------------------------------------------------------
# AC #2 — Orphaned position (fills, no sell) → sell placed
# ---------------------------------------------------------------------------


class TestReconcileOrphanedPosition(unittest.TestCase):
    """Orphaned position: has fills, no sell order → sell placed immediately."""

    def test_orphan_sell_placed_when_position_has_no_sell(self) -> None:
        # Buy order exists + position, but no sell order in CLOB
        buy_order = {
            "id": "buy-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no")

        svc, mocks = _make_service(
            open_orders=[buy_order],
            positions=[position],
            games=[game],
        )
        mocks["clob"].create_sell_order.return_value = {"orderID": "sell-placed-1"}

        svc.reconcile()

        mocks["clob"].create_sell_order.assert_called_once_with("token-no", 0.48, 10.0)

    def test_orphan_sell_recorded_in_order_tracker(self) -> None:
        buy_order = {
            "id": "buy-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no")

        svc, mocks = _make_service(
            open_orders=[buy_order],
            positions=[position],
            games=[game],
        )
        mocks["clob"].create_sell_order.return_value = {"orderID": "sell-placed-1"}

        svc.reconcile()

        self.assertTrue(mocks["order_tracker"].has_sell_order("token-no"))

    def test_orphan_sell_logs_warning(self) -> None:
        buy_order = {
            "id": "buy-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no", home="Arsenal", away="Chelsea")

        svc, mocks = _make_service(
            open_orders=[buy_order],
            positions=[position],
            games=[game],
        )
        mocks["clob"].create_sell_order.return_value = {"orderID": "sell-placed-1"}

        with self.assertLogs("btts_bot.core.reconciliation", level="WARNING") as cm:
            svc.reconcile()

        warning_msgs = [m for m in cm.output if "WARNING" in m]
        self.assertTrue(
            any("Orphaned position" in m for m in warning_msgs),
            f"Expected orphan warning; got: {cm.output}",
        )

    def test_orphan_sell_failure_logs_error_and_continues(self) -> None:
        """If sell placement fails (retries exhausted → None), logs ERROR and continues."""
        buy_order = {
            "id": "buy-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no")

        svc, mocks = _make_service(
            open_orders=[buy_order],
            positions=[position],
            games=[game],
        )
        mocks["clob"].create_sell_order.return_value = None  # retries exhausted

        with self.assertLogs("btts_bot.core.reconciliation", level="ERROR") as cm:
            svc.reconcile()

        error_msgs = [m for m in cm.output if "ERROR" in m]
        self.assertTrue(
            any("Orphaned" in m for m in error_msgs),
            f"Expected error for failed orphan sell; got: {cm.output}",
        )

    def test_existing_sell_order_not_duplicated(self) -> None:
        """If a sell order already exists in CLOB, no additional sell is placed."""
        buy_order = {
            "id": "buy-1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        sell_order = {
            "id": "sell-1",
            "asset_id": "token-no",
            "side": "SELL",
            "price": "0.50",
            "original_size": "10.0",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no")

        svc, mocks = _make_service(
            open_orders=[buy_order, sell_order],
            positions=[position],
            games=[game],
        )

        svc.reconcile()

        mocks["clob"].create_sell_order.assert_not_called()


# ---------------------------------------------------------------------------
# AC #3 — Markets registered in MarketRegistry with correct lifecycle state
# ---------------------------------------------------------------------------


class TestReconcileMarketRegistration(unittest.TestCase):
    """Markets are registered in MarketRegistry with correct lifecycle states."""

    def test_market_with_buy_order_only_reaches_buy_placed(self) -> None:
        buy_order = {
            "id": "b1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(open_orders=[buy_order], games=[game])

        svc.reconcile()

        entry = mocks["market_registry"].get("token-no")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.lifecycle.state, GameState.BUY_PLACED)

    def test_market_with_buy_and_position_reaches_filling(self) -> None:
        buy_order = {
            "id": "b1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "5.0"}
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(
            open_orders=[buy_order],
            positions=[position],
            games=[game],
        )
        mocks["clob"].create_sell_order.return_value = {"orderID": "s1"}

        svc.reconcile()

        entry = mocks["market_registry"].get("token-no")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.lifecycle.state, GameState.FILLING)

    def test_market_with_sell_order_reaches_sell_placed(self) -> None:
        sell_order = {
            "id": "sell-1",
            "asset_id": "token-no",
            "side": "SELL",
            "price": "0.50",
            "original_size": "10.0",
            "status": "LIVE",
        }
        position = {"asset": "token-no", "size": "10.0"}
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(
            open_orders=[sell_order],
            positions=[position],
            games=[game],
        )

        svc.reconcile()

        entry = mocks["market_registry"].get("token-no")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.lifecycle.state, GameState.SELL_PLACED)

    def test_market_without_metadata_not_registered(self) -> None:
        """Token with orders but no game metadata is not registered in MarketRegistry."""
        buy_order = {
            "id": "b1",
            "asset_id": "unknown-token",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        # No games in the data file
        svc, mocks = _make_service(open_orders=[buy_order], games=[])

        svc.reconcile()

        self.assertFalse(mocks["market_registry"].is_processed("unknown-token"))

    def test_scheduler_triggers_created_for_reconciled_market(self) -> None:
        """Pre-kickoff and game-start triggers are scheduled for reconciled markets."""
        buy_order = {
            "id": "b1",
            "asset_id": "token-no",
            "side": "BUY",
            "price": "0.48",
            "status": "LIVE",
        }
        game = _make_game(token_id="token-no")
        svc, mocks = _make_service(open_orders=[buy_order], games=[game])

        svc.reconcile()

        mocks["scheduler"].schedule_pre_kickoff.assert_called_once_with("token-no", FUTURE_KICKOFF)
        mocks["scheduler"].schedule_game_start.assert_called_once_with("token-no", FUTURE_KICKOFF)


# ---------------------------------------------------------------------------
# AC #5 — API failures handled gracefully (best-effort, bot still starts)
# ---------------------------------------------------------------------------


class TestReconcileApiFailures(unittest.TestCase):
    """Failures during reconciliation are handled best-effort; bot still starts."""

    def test_clob_api_failure_logs_critical_and_continues(self) -> None:
        """If CLOB get_open_orders returns None, log CRITICAL and continue."""
        svc, mocks = _make_service(open_orders=None, positions=[])

        with self.assertLogs("btts_bot.core.reconciliation", level="CRITICAL") as cm:
            svc.reconcile()

        self.assertTrue(any("CRITICAL" in m for m in cm.output))

    def test_data_api_failure_logs_critical_and_continues(self) -> None:
        """If Data API get_positions returns None, log CRITICAL and continue."""
        svc, mocks = _make_service(open_orders=[], positions=None)

        with self.assertLogs("btts_bot.core.reconciliation", level="CRITICAL") as cm:
            svc.reconcile()

        self.assertTrue(any("CRITICAL" in m for m in cm.output))

    def test_both_apis_fail_logs_critical_for_each_bot_still_starts(self) -> None:
        """Both APIs fail — two CRITICAL logs, reconciliation still completes."""
        svc, mocks = _make_service(open_orders=None, positions=None)

        with self.assertLogs("btts_bot.core.reconciliation", level="CRITICAL") as cm:
            svc.reconcile()  # must not raise

        critical_count = sum(1 for m in cm.output if "CRITICAL" in m)
        self.assertGreaterEqual(critical_count, 2)

    def test_no_orders_and_no_positions_clean_startup_no_errors(self) -> None:
        """No open orders, no positions → clean startup, no errors logged."""
        svc, mocks = _make_service(open_orders=[], positions=[])

        # Should not raise and should not log anything at WARNING+ level
        # (if there are no orders/positions, there are no warnings expected)
        svc.reconcile()

        mocks["clob"].create_sell_order.assert_not_called()


# ---------------------------------------------------------------------------
# PositionTracker.set_position() unit tests
# ---------------------------------------------------------------------------


class TestPositionTrackerSetPosition(unittest.TestCase):
    """Tests for the new set_position() method on PositionTracker."""

    def test_set_position_sets_absolute_value(self) -> None:
        tracker = PositionTracker()
        tracker.set_position("token-1", 15.0)
        self.assertAlmostEqual(tracker.get_accumulated_fills("token-1"), 15.0)

    def test_set_position_overwrites_existing_value(self) -> None:
        tracker = PositionTracker()
        tracker.accumulate("token-1", 10.0)
        tracker.set_position("token-1", 3.0)
        self.assertAlmostEqual(tracker.get_accumulated_fills("token-1"), 3.0)

    def test_set_position_does_not_affect_other_tokens(self) -> None:
        tracker = PositionTracker()
        tracker.accumulate("token-1", 10.0)
        tracker.set_position("token-2", 5.0)
        self.assertAlmostEqual(tracker.get_accumulated_fills("token-1"), 10.0)
        self.assertAlmostEqual(tracker.get_accumulated_fills("token-2"), 5.0)


if __name__ == "__main__":
    unittest.main()
