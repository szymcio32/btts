"""Tests for btts_bot.core.pre_kickoff — PreKickoffService."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.pre_kickoff import PreKickoffService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    clob: object = None,
    tracker: OrderTracker | None = None,
    pos_tracker: PositionTracker | None = None,
    registry: MarketRegistry | None = None,
) -> PreKickoffService:
    return PreKickoffService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=pos_tracker or PositionTracker(),
        market_registry=registry or MarketRegistry(),
    )


def _register_market(
    registry: MarketRegistry,
    token_id: str = "token-1",
    home_team: str = "Arsenal",
    away_team: str = "Chelsea",
) -> object:
    return registry.register(
        token_id=token_id,
        condition_id=f"cond-{token_id}",
        token_ids=[token_id],
        kickoff_time=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        league="EPL",
        home_team=home_team,
        away_team=away_team,
    )


def _advance_to_state(entry: object, *states: GameState) -> None:
    """Drive the lifecycle through a sequence of states."""
    for state in states:
        entry.lifecycle.transition(state)


# ---------------------------------------------------------------------------
# Unknown / missing registry entry
# ---------------------------------------------------------------------------


def test_handle_pre_kickoff_no_registry_entry_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Handler logs WARNING and returns if the token is not in the registry."""
    clob = MagicMock()
    service = _make_service(clob=clob)
    with caplog.at_level("WARNING", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("unknown-token")
    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()
    assert "no registry entry" in caplog.text


# ---------------------------------------------------------------------------
# Terminal / already-handled states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        GameState.PRE_KICKOFF,
        GameState.GAME_STARTED,
        GameState.RECOVERY_COMPLETE,
        GameState.DONE,
        GameState.SKIPPED,
        GameState.EXPIRED,
    ],
)
def test_handle_pre_kickoff_terminal_state_no_api_calls(state: GameState) -> None:
    """Handler does nothing (no API calls) for terminal / already-handled states."""
    clob = MagicMock()
    registry = MarketRegistry()
    entry = _register_market(registry)
    # Force internal state — bypass normal transition guards for the test
    entry.lifecycle._state = state

    service = _make_service(clob=clob, registry=registry)
    service.handle_pre_kickoff("token-1")

    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()


# ---------------------------------------------------------------------------
# SELL_PLACED path (AC #2)
# ---------------------------------------------------------------------------


def test_sell_placed_cancels_old_sell_and_places_new_sell() -> None:
    """SELL_PLACED: cancels existing sell and places new one at buy_price."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)  # buy_price=0.48, sell_price=0.52
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 15.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    clob.cancel_order.assert_any_call("old-sell-id")
    clob.create_sell_order.assert_called_once()
    assert tracker.get_sell_order("token-1").order_id == "new-sell-id"
    assert entry.lifecycle.state == GameState.PRE_KICKOFF


def test_sell_placed_uses_buy_price_not_spread_price() -> None:
    """SELL_PLACED: new sell is at buy_price (0.48), NOT spread sell_price (0.52)."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    call_args = clob.create_sell_order.call_args
    used_price = call_args.args[1]
    assert used_price == pytest.approx(0.48)  # buy_price, NOT 0.52


def test_sell_placed_sell_size_equals_accumulated_fills() -> None:
    """SELL_PLACED: new sell size equals full accumulated position from PositionTracker."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 25.5)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    call_args = clob.create_sell_order.call_args
    used_size = call_args.args[2]
    assert used_size == pytest.approx(25.5)


def test_sell_placed_caps_sell_price_at_099() -> None:
    """SELL_PLACED: sell price is capped at 0.99 even if buy_price > 0.99."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 1.00, 1.02)  # buy_price above 0.99
    tracker.record_sell("token-1", "old-sell-id", 1.02, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.99)


def test_sell_placed_cancel_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SELL_PLACED: if cancel returns None, logs ERROR and leaves game in SELL_PLACED."""
    clob = MagicMock()
    clob.cancel_order.return_value = None  # Cancel failed

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    clob.create_sell_order.assert_not_called()
    assert entry.lifecycle.state == GameState.SELL_PLACED
    assert "cancel" in caplog.text.lower()


def test_sell_placed_new_sell_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SELL_PLACED: if new sell returns None, logs ERROR and leaves game in SELL_PLACED."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = None  # New sell failed

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    # Old sell was removed (cancel succeeded), new sell was not recorded
    assert not tracker.has_sell_order("token-1")
    # State must NOT advance — stays as implicit flag for game-start recovery
    assert entry.lifecycle.state == GameState.SELL_PLACED
    assert "failed" in caplog.text.lower()


def test_sell_placed_cancels_active_buy_after_new_sell() -> None:
    """SELL_PLACED: buy order is cancelled after successful sell consolidation."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    # cancel_order called twice: once for old sell, once for buy
    assert clob.cancel_order.call_count == 2
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is False


def test_sell_placed_logs_info_on_success(caplog: pytest.LogCaptureFixture) -> None:
    """SELL_PLACED: logs INFO with buy_price and size on success."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry, home_team="Arsenal", away_team="Chelsea")
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert "Pre-kickoff consolidation" in caplog.text
    assert "buy_price=" in caplog.text
    assert "size=" in caplog.text
    assert "Arsenal" in caplog.text


# ---------------------------------------------------------------------------
# FILLING path (AC #4)
# ---------------------------------------------------------------------------


def test_filling_places_sell_at_buy_price() -> None:
    """FILLING: places sell at buy_price for accumulated fills."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-filling-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 3.0)  # Below min_order_size, but should still be placed

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.48)  # buy_price
    assert call_args.args[2] == pytest.approx(3.0)  # accumulated fills
    assert tracker.has_sell_order("token-1")
    assert entry.lifecycle.state == GameState.PRE_KICKOFF


def test_filling_cancels_unfilled_buy() -> None:
    """FILLING: unfilled buy order is cancelled after placing sell."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "sell-filling-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    clob.cancel_order.assert_called_once_with("buy-order-1")
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is False


def test_filling_sell_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FILLING: sell failure leaves game in FILLING (implicit flag for recovery)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = None

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 3.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert entry.lifecycle.state == GameState.FILLING
    assert "failed" in caplog.text.lower()


def test_filling_logs_buy_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    """FILLING: INFO log '[Home vs Away] Pre-kickoff buy cancelled' is emitted."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)

    registry = MarketRegistry()
    entry = _register_market(registry, home_team="Man City", away_team="Liverpool")
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert "Pre-kickoff buy cancelled" in caplog.text
    assert "Man City" in caplog.text


# ---------------------------------------------------------------------------
# BUY_PLACED path (AC #3)
# ---------------------------------------------------------------------------


def test_buy_placed_no_fills_cancel_buy_transition_to_done() -> None:
    """BUY_PLACED with 0 fills: cancel buy, transition PRE_KICKOFF -> DONE."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    clob.cancel_order.assert_called_once_with("buy-order-1")
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is False
    assert entry.lifecycle.state == GameState.DONE


def test_buy_placed_no_fills_logs_buy_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    """BUY_PLACED: logs INFO 'Pre-kickoff buy cancelled' on buy cancellation."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    registry = MarketRegistry()
    entry = _register_market(registry, home_team="Juventus", away_team="Milan")
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert "Pre-kickoff buy cancelled" in caplog.text
    assert "Juventus" in caplog.text


def test_buy_placed_with_fills_places_sell_at_buy_price() -> None:
    """BUY_PLACED with fills (race condition): places sell at buy_price."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "race-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 8.0)  # Fills exist despite BUY_PLACED state

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_pre_kickoff("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.48)  # buy_price
    assert call_args.args[2] == pytest.approx(8.0)
    assert tracker.has_sell_order("token-1")
    assert entry.lifecycle.state == GameState.PRE_KICKOFF


def test_buy_placed_cancel_failure_stays_buy_placed_for_recovery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BUY_PLACED: cancel failure logs ERROR and leaves state/buy unchanged for recovery."""
    clob = MagicMock()
    clob.cancel_order.return_value = None  # Cancel failed

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    # On cancel failure, buy remains active and lifecycle does not advance
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is True
    assert entry.lifecycle.state == GameState.BUY_PLACED
    assert "None" in caplog.text or "cancel" in caplog.text.lower()


def test_filling_cancel_buy_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FILLING: buy-cancel failure logs ERROR and keeps game in FILLING for recovery."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-filling-id"}
    clob.cancel_order.return_value = None

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert entry.lifecycle.state == GameState.FILLING
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is True
    assert "cancel" in caplog.text.lower()


def test_sell_placed_cancel_buy_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SELL_PLACED: buy-cancel failure logs ERROR and keeps game in SELL_PLACED for recovery."""
    clob = MagicMock()
    # First cancel for existing sell succeeds, second cancel for buy fails
    clob.cancel_order.side_effect = [{"success": True}, None]
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.52, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.pre_kickoff"):
        service.handle_pre_kickoff("token-1")

    assert entry.lifecycle.state == GameState.SELL_PLACED
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is True
    assert "cancel" in caplog.text.lower()


# ---------------------------------------------------------------------------
# DISCOVERED / ANALYSED — no-op
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [GameState.DISCOVERED, GameState.ANALYSED])
def test_handle_pre_kickoff_early_states_no_api_calls(state: GameState) -> None:
    """DISCOVERED/ANALYSED: no API calls, handler returns quietly."""
    clob = MagicMock()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle._state = state

    service = _make_service(clob=clob, registry=registry)
    service.handle_pre_kickoff("token-1")

    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()
