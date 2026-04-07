"""Tests for btts_bot.core.game_start — GameStartService."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.game_start import GameStartService
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
) -> GameStartService:
    return GameStartService(
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
# Missing registry entry
# ---------------------------------------------------------------------------


def test_handle_game_start_no_registry_entry_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Handler logs WARNING and returns if token is not in registry."""
    clob = MagicMock()
    service = _make_service(clob=clob)
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("unknown-token")
    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()
    assert "no registry entry" in caplog.text


# ---------------------------------------------------------------------------
# Terminal / already-handled states (AC #2 idempotency)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        GameState.GAME_STARTED,
        GameState.RECOVERY_COMPLETE,
        GameState.DONE,
        GameState.SKIPPED,
        GameState.EXPIRED,
    ],
)
def test_handle_game_start_terminal_state_no_api_calls(state: GameState) -> None:
    """Handler does nothing for terminal / already-handled states."""
    clob = MagicMock()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle._state = state

    service = _make_service(clob=clob, registry=registry)
    service.handle_game_start("token-1")

    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()


# ---------------------------------------------------------------------------
# DISCOVERED / ANALYSED — no position, skip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [GameState.DISCOVERED, GameState.ANALYSED])
def test_handle_game_start_early_states_no_api_calls(state: GameState) -> None:
    """DISCOVERED/ANALYSED: no API calls, handler returns quietly."""
    clob = MagicMock()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle._state = state

    service = _make_service(clob=clob, registry=registry)
    service.handle_game_start("token-1")

    clob.cancel_order.assert_not_called()
    clob.create_sell_order.assert_not_called()


# ---------------------------------------------------------------------------
# PRE_KICKOFF state (normal path, AC #2)
# ---------------------------------------------------------------------------


def test_pre_kickoff_state_detects_cancellation_re_places_sell() -> None:
    """PRE_KICKOFF + sell order exists: removes old sell record, places new sell at buy_price."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.48, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_called_once()
    assert tracker.get_sell_order("token-1").order_id == "new-sell-id"
    assert entry.lifecycle.state == GameState.GAME_STARTED


def test_pre_kickoff_state_uses_buy_price_not_spread_price() -> None:
    """PRE_KICKOFF: new sell is placed at buy_price (0.48), NOT sell_price (0.52)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.48, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.48)  # buy_price, NOT 0.52


def test_pre_kickoff_state_caps_sell_price_at_099() -> None:
    """PRE_KICKOFF: sell price is capped at 0.99 if buy_price > 0.99."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 1.00, 1.02)
    tracker.record_sell("token-1", "old-sell-id", 0.99, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.99)


def test_pre_kickoff_state_no_fills_transitions_to_done() -> None:
    """PRE_KICKOFF with 0 accumulated fills: transitions to DONE (AC #3)."""
    clob = MagicMock()

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_not_called()
    assert entry.lifecycle.state == GameState.DONE


def test_pre_kickoff_state_no_fills_logs_nothing_to_recover(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PRE_KICKOFF + 0 fills: emits INFO 'No position at game start -- nothing to recover'."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos = PositionTracker()

    registry = MarketRegistry()
    entry = _register_market(registry, home_team="Arsenal", away_team="Chelsea")
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert "No position at game start" in caplog.text
    assert "nothing to recover" in caplog.text


def test_pre_kickoff_state_logs_sell_re_placed(caplog: pytest.LogCaptureFixture) -> None:
    """PRE_KICKOFF + fills: logs INFO 'Game-start recovery: sell re-placed at buy_price=..., size=...'"""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.48, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry, home_team="Arsenal", away_team="Chelsea")
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert "Game-start recovery" in caplog.text
    assert "sell re-placed" in caplog.text
    assert "buy_price=" in caplog.text
    assert "size=" in caplog.text
    assert "Arsenal" in caplog.text


def test_pre_kickoff_state_sell_placement_failure_logs_error_no_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PRE_KICKOFF: create_sell_order returns None — logs ERROR, does NOT transition."""
    clob = MagicMock()
    clob.create_sell_order.return_value = None

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    # Must NOT crash and must NOT transition (Story 4.3 retry loop handles it)
    assert entry.lifecycle.state == GameState.PRE_KICKOFF
    assert "failed" in caplog.text.lower() or "sell order" in caplog.text.lower()


# ---------------------------------------------------------------------------
# SELL_PLACED state (pre-kickoff failed, AC #2)
# ---------------------------------------------------------------------------


def test_sell_placed_state_recovery_detects_old_sell_cancelled_re_places() -> None:
    """SELL_PLACED (pre-kickoff failed): removes old sell, places new sell at buy_price."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.48, 10.0)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_called_once()
    assert tracker.get_sell_order("token-1").order_id == "new-sell-id"
    assert entry.lifecycle.state == GameState.GAME_STARTED


def test_sell_placed_state_no_fills_transitions_to_done() -> None:
    """SELL_PLACED + 0 fills: transitions to DONE."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "old-sell-id", 0.48, 10.0)

    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING, GameState.SELL_PLACED
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_not_called()
    assert entry.lifecycle.state == GameState.DONE


# ---------------------------------------------------------------------------
# FILLING state (pre-kickoff failed, AC #2)
# ---------------------------------------------------------------------------


def test_filling_state_places_sell_at_buy_price_transitions_to_game_started() -> None:
    """FILLING (pre-kickoff failed): places sell at buy_price, transitions to GAME_STARTED."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "fill-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 7.5)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.48)  # buy_price
    assert call_args.args[2] == pytest.approx(7.5)  # accumulated fills
    assert tracker.has_sell_order("token-1")
    assert entry.lifecycle.state == GameState.GAME_STARTED


def test_filling_state_no_fills_transitions_to_done() -> None:
    """FILLING + 0 fills: transitions to DONE."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_not_called()
    assert entry.lifecycle.state == GameState.DONE


def test_filling_state_marks_buy_inactive() -> None:
    """FILLING: buy order is marked inactive (Polymarket cancelled it)."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "fill-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED, GameState.FILLING)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is False


# ---------------------------------------------------------------------------
# BUY_PLACED state (pre-kickoff failed, AC #2)
# ---------------------------------------------------------------------------


def test_buy_placed_state_no_fills_transitions_to_done() -> None:
    """BUY_PLACED (pre-kickoff failed, no fills): marks buy inactive, transitions to DONE."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos = PositionTracker()  # 0 fills

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    clob.create_sell_order.assert_not_called()
    assert entry.lifecycle.state == GameState.DONE
    buy_record = tracker.get_buy_order("token-1")
    assert buy_record is not None
    assert buy_record.active is False


def test_buy_placed_state_with_fills_places_sell_transitions_to_game_started() -> None:
    """BUY_PLACED + race condition fills: places sell at buy_price, transitions to GAME_STARTED."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "race-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)  # Fills exist despite BUY_PLACED state

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(entry, GameState.ANALYSED, GameState.BUY_PLACED)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.48)  # buy_price
    assert call_args.args[2] == pytest.approx(5.0)
    assert tracker.has_sell_order("token-1")
    assert entry.lifecycle.state == GameState.GAME_STARTED


# ---------------------------------------------------------------------------
# Error handling: create_sell_order returns None (AC — must not crash)
# ---------------------------------------------------------------------------


def test_sell_placement_failure_does_not_crash_recovery_thread(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """create_sell_order returns None: logs ERROR, does NOT crash (recovery thread stays alive)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = None

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)

    # Must not raise
    service.handle_game_start("token-1")

    # No transition happened
    assert entry.lifecycle.state == GameState.PRE_KICKOFF


def test_unhandled_exception_in_recovery_is_caught(caplog: pytest.LogCaptureFixture) -> None:
    """Unhandled exceptions in _do_game_start_recovery are caught by handle_game_start."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = RuntimeError("unexpected boom")

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 10.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)

    # handle_game_start must NOT propagate the exception
    with caplog.at_level("ERROR", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert "FAILED" in caplog.text
    assert "position may be unmanaged" in caplog.text


# ---------------------------------------------------------------------------
# record_sell_if_absent usage — verifies new sell is recorded atomically
# ---------------------------------------------------------------------------


def test_record_sell_if_absent_used_for_atomic_recording() -> None:
    """GameStartService uses record_sell_if_absent (new sell recorded after recovery)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "atomic-sell-id"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.50, 0.52)

    pos = PositionTracker()
    pos.accumulate("token-1", 5.0)

    registry = MarketRegistry()
    entry = _register_market(registry)
    _advance_to_state(
        entry,
        GameState.ANALYSED,
        GameState.BUY_PLACED,
        GameState.FILLING,
        GameState.SELL_PLACED,
        GameState.PRE_KICKOFF,
    )

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)
    service.handle_game_start("token-1")

    sell_record = tracker.get_sell_order("token-1")
    assert sell_record is not None
    assert sell_record.order_id == "atomic-sell-id"
    assert sell_record.sell_price == pytest.approx(0.50)
    assert sell_record.sell_size == pytest.approx(5.0)


def test_duplicate_handle_game_start_same_token_is_skipped() -> None:
    """If a recovery is already in progress for token, duplicate trigger is ignored."""
    clob = MagicMock()
    tracker = OrderTracker()
    pos = PositionTracker()
    registry = MarketRegistry()
    _register_market(registry, token_id="token-dup")

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos, registry=registry)

    assert service._acquire_inflight("token-dup") is True
    service.handle_game_start("token-dup")
    clob.create_sell_order.assert_not_called()
    service._release_inflight("token-dup")


def test_release_inflight_after_exception() -> None:
    """In-flight token ownership is always released, even after exceptions."""
    service = _make_service()

    def boom(_: str) -> None:
        raise RuntimeError("boom")

    service._do_game_start_recovery = boom  # type: ignore[method-assign]

    service.handle_game_start("token-ex")

    # Must be acquirable again, proving finally-block released ownership.
    assert service._acquire_inflight("token-ex") is True
    service._release_inflight("token-ex")
