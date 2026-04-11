"""Tests for btts_bot.core.game_start — GameStartService."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from btts_bot.config import TimingConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.game_start import GameStartService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAST_TIMING = TimingConfig(
    daily_fetch_hour_utc=0,
    sell_verify_interval_seconds=1,
)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch time.sleep in game_start module so tests run instantly."""
    monkeypatch.setattr("btts_bot.core.game_start.time.sleep", lambda _: None)


def _make_service(
    clob: object = None,
    tracker: OrderTracker | None = None,
    pos_tracker: PositionTracker | None = None,
    registry: MarketRegistry | None = None,
    timing: TimingConfig | None = None,
) -> GameStartService:
    return GameStartService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=pos_tracker or PositionTracker(),
        market_registry=registry or MarketRegistry(),
        timing_config=timing or _FAST_TIMING,
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
    # create_sell_order succeeds on first call; get_order returns LIVE for verification
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}
    clob.get_order.return_value = {"status": "LIVE"}

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
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


def test_pre_kickoff_state_uses_buy_price_not_spread_price() -> None:
    """PRE_KICKOFF: new sell is placed at buy_price (0.48), NOT sell_price (0.52)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}
    clob.get_order.return_value = {"status": "LIVE"}

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
    clob.get_order.return_value = {"status": "LIVE"}

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
    clob.get_order.return_value = {"status": "LIVE"}

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


def test_pre_kickoff_state_sell_placement_failure_retries_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PRE_KICKOFF: create_sell_order returns None first, then succeeds — logs WARNING for retry."""
    clob = MagicMock()
    # Fail once, then succeed; get_order returns LIVE for verification
    clob.create_sell_order.side_effect = [None, {"orderID": "retry-sell-id"}]
    clob.get_order.return_value = {"status": "LIVE"}

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert clob.create_sell_order.call_count == 2
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "sell placement failed, retrying #1" in caplog.text


# ---------------------------------------------------------------------------
# SELL_PLACED state (pre-kickoff failed, AC #2)
# ---------------------------------------------------------------------------


def test_sell_placed_state_recovery_detects_old_sell_cancelled_re_places() -> None:
    """SELL_PLACED (pre-kickoff failed): removes old sell, places new sell at buy_price."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "new-sell-id"}
    clob.get_order.return_value = {"status": "LIVE"}

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
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


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


def test_filling_state_places_sell_at_buy_price_transitions_to_recovery_complete() -> None:
    """FILLING (pre-kickoff failed): places sell at buy_price, transitions to RECOVERY_COMPLETE."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "fill-sell-id"}
    clob.get_order.return_value = {"status": "LIVE"}

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
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


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
    clob.get_order.return_value = {"status": "LIVE"}

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


def test_buy_placed_state_with_fills_places_sell_transitions_to_recovery_complete() -> None:
    """BUY_PLACED + race condition fills: places sell at buy_price, transitions to RECOVERY_COMPLETE."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "race-sell-id"}
    clob.get_order.return_value = {"status": "LIVE"}

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
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


# ---------------------------------------------------------------------------
# Error handling: create_sell_order returns None then succeeds
# ---------------------------------------------------------------------------


def test_sell_placement_failure_retries_until_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """create_sell_order returns None (retried), then succeeds — recovery thread stays alive."""
    clob = MagicMock()
    # Fail twice, then succeed; get_order returns LIVE
    clob.create_sell_order.side_effect = [None, None, {"orderID": "eventual-sell-id"}]
    clob.get_order.return_value = {"status": "LIVE"}

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

    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    # 3 calls: fail, fail, succeed
    assert clob.create_sell_order.call_count == 3
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "sell placement failed, retrying #1" in caplog.text
    assert "sell placement failed, retrying #2" in caplog.text


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
    clob.get_order.return_value = {"status": "LIVE"}

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


# ---------------------------------------------------------------------------
# Sell verification and retry loop (Story 4.3 — AC #1, #2, #3)
# ---------------------------------------------------------------------------


def test_verify_sell_active_transitions_to_recovery_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sell placed + verification confirms active -> RECOVERY_COMPLETE, INFO log emitted (AC #1, #2)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-1"}
    clob.get_order.return_value = {"status": "LIVE"}

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

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

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Game-start recovery verified -- sell confirmed active" in caplog.text
    assert "Arsenal" in caplog.text


def test_verify_sell_open_status_also_transitions_to_recovery_complete() -> None:
    """get_order status OPEN also triggers RECOVERY_COMPLETE (equivalent to LIVE)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-open"}
    clob.get_order.return_value = {"status": "OPEN"}

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
    service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


def test_verify_sell_matched_status_transitions_to_recovery_complete() -> None:
    """get_order status MATCHED (filled) also triggers RECOVERY_COMPLETE."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-matched"}
    clob.get_order.return_value = {"status": "MATCHED"}

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
    service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


def test_verify_sell_missing_re_places_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sell placed + verification finds order cancelled -> re-place sell, verify again, RECOVERY_COMPLETE (AC #3)."""
    clob = MagicMock()
    # Initial placement succeeds; re-placement after failure also succeeds
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},  # initial placement
        {"orderID": "sell-id-2"},  # re-placement after cancelled
    ]
    # First get_order: CANCELLED; second: LIVE
    clob.get_order.side_effect = [
        {"status": "CANCELLED"},
        {"status": "LIVE"},
    ]

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Sell verification failed -- retry #1" in caplog.text
    # Final sell should be the re-placed one
    assert tracker.get_sell_order("token-1").order_id == "sell-id-2"


def test_verify_sell_get_order_returns_none_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """get_order returns None (API error) -> treated as failed, re-place sell, retry (AC #3)."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},
        {"orderID": "sell-id-2"},
    ]
    clob.get_order.side_effect = [
        None,  # API error
        {"status": "LIVE"},
    ]

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "get_order returned None" in caplog.text
    assert "Sell verification failed -- retry #1" in caplog.text


def test_verify_multiple_retries_before_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """3 consecutive verification failures then success — verify retry count in log messages (AC #3)."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},  # initial
        {"orderID": "sell-id-2"},  # re-place after retry 1
        {"orderID": "sell-id-3"},  # re-place after retry 2
        {"orderID": "sell-id-4"},  # re-place after retry 3
    ]
    clob.get_order.side_effect = [
        {"status": "CANCELLED"},  # retry 1
        {"status": "CANCELLED"},  # retry 2
        {"status": "CANCELLED"},  # retry 3
        {"status": "LIVE"},  # success
    ]

    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Sell verification failed -- retry #1" in caplog.text
    assert "Sell verification failed -- retry #2" in caplog.text
    assert "Sell verification failed -- retry #3" in caplog.text


def test_verify_re_placed_sell_also_fails_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Re-placed sell (create_sell_order) returns None on first retry, then succeeds — resilient retry."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},  # initial placement succeeds
        None,  # re-placement after CANCELLED fails (retry #1)
        {
            "orderID": "sell-id-3"
        },  # re-placement succeeds (retry #2, since id-1 still shows CANCELLED)
    ]
    clob.get_order.side_effect = [
        {"status": "CANCELLED"},  # verification #1: sell-id-1 is cancelled
        {"status": "LIVE"},  # verification #2: sell-id-3 is live
    ]

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Sell re-placement failed on retry #1" in caplog.text
    assert tracker.get_sell_order("token-1").order_id == "sell-id-3"


def test_time_sleep_called_with_verify_interval() -> None:
    """time.sleep is called with sell_verify_interval_seconds value (AC #1)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-1"}
    clob.get_order.return_value = {"status": "LIVE"}

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

    # Use a non-zero interval to verify it's used
    timing = TimingConfig(daily_fetch_hour_utc=0, sell_verify_interval_seconds=42)
    service = _make_service(
        clob=clob, tracker=tracker, pos_tracker=pos, registry=registry, timing=timing
    )

    with patch("btts_bot.core.game_start.time.sleep") as mock_sleep:
        service.handle_game_start("token-1")

    # sleep(42) called once for verification interval
    mock_sleep.assert_called_with(42)


def test_time_sleep_called_with_interval_for_placement_retry() -> None:
    """time.sleep uses sell_verify_interval_seconds for initial sell placement retry too."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [None, {"orderID": "sell-id-ok"}]
    clob.get_order.return_value = {"status": "LIVE"}

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

    timing = TimingConfig(daily_fetch_hour_utc=0, sell_verify_interval_seconds=30)
    service = _make_service(
        clob=clob, tracker=tracker, pos_tracker=pos, registry=registry, timing=timing
    )

    with patch("btts_bot.core.game_start.time.sleep") as mock_sleep:
        service.handle_game_start("token-1")

    # All sleep calls should use interval=30
    for sleep_call in mock_sleep.call_args_list:
        assert sleep_call == call(30)


def test_recovery_thread_exception_does_not_crash(caplog: pytest.LogCaptureFixture) -> None:
    """Exception inside verification loop (handle_game_start outer try/except) does not crash (AC #3)."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-1"}
    # get_order raises unexpectedly
    clob.get_order.side_effect = RuntimeError("network exploded")

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
    with caplog.at_level("ERROR", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert "FAILED" in caplog.text


def test_initial_sell_placement_failure_then_success_proceeds_with_verification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Initial sell placement fails (returns None) -> retry loop places sell, then verification succeeds (AC #3, Task 2)."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [None, {"orderID": "retry-sell-id"}]
    clob.get_order.return_value = {"status": "LIVE"}

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert clob.create_sell_order.call_count == 2
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "sell placement failed, retrying #1" in caplog.text
    # Verify verification also ran (get_order was called)
    clob.get_order.assert_called_once()


def test_verify_uses_order_status_field_when_status_missing() -> None:
    """Verification accepts order_status field if status field is absent."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-id-1"}
    clob.get_order.return_value = {"order_status": "OPEN"}

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
    service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE


def test_verify_handles_non_string_status_without_crashing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verification coerces non-string status safely and retries instead of crashing."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},
        {"orderID": "sell-id-2"},
    ]
    clob.get_order.side_effect = [
        {"status": None},
        {"status": "LIVE"},
    ]

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
    with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
        service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Sell verification failed -- retry #1" in caplog.text


def test_initial_placement_missing_order_id_retries_until_valid_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Initial placement missing order ID now retries and continues recovery."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {},
        {"orderID": "sell-id-2"},
    ]
    clob.get_order.return_value = {"status": "LIVE"}

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

    assert clob.create_sell_order.call_count == 2
    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "sell posted but no orderID, retrying #1" in caplog.text


def test_verify_missing_sell_record_replaces_and_recovers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verification no longer exits early when sell record is missing."""
    clob = MagicMock()
    clob.create_sell_order.side_effect = [
        {"orderID": "sell-id-1"},
        {"orderID": "sell-id-2"},
    ]
    clob.get_order.return_value = {"status": "LIVE"}

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

    original_get_sell_order = tracker.get_sell_order

    call_count = {"value": 0}

    def flaky_get_sell_order(token_id: str):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return None
        return original_get_sell_order(token_id)

    with patch.object(tracker, "get_sell_order", side_effect=flaky_get_sell_order):
        with caplog.at_level("WARNING", logger="btts_bot.core.game_start"):
            service.handle_game_start("token-1")

    assert entry.lifecycle.state == GameState.RECOVERY_COMPLETE
    assert "Verify: no sell record after placement, attempting re-placement" in caplog.text
