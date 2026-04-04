"""Tests for btts_bot.core.fill_polling — FillPollingService."""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock

from btts_bot.core.fill_polling import FillPollingService, _parse_fixed_math
from btts_bot.core.game_lifecycle import GameState
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order_response(size_matched="0", original_size="100000000", status="LIVE"):
    """Create a mock CLOB order response."""
    order = MagicMock()
    order.size_matched = size_matched
    order.original_size = original_size
    order.status = status
    return order


def _make_service(
    clob=None,
    tracker=None,
    pos_tracker=None,
    registry=None,
    btts=None,
    order_execution=None,
):
    if btts is None:
        btts = MagicMock()
        btts.min_order_size = 5.0
    return FillPollingService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=pos_tracker or PositionTracker(),
        market_registry=registry or MarketRegistry(),
        btts_config=btts,
        order_execution_service=order_execution or MagicMock(),
    )


def _register_market(registry, token_id="token-1", home_team="Arsenal", away_team="Chelsea"):
    return registry.register(
        token_id=token_id,
        condition_id=f"cond-{token_id}",
        token_ids=[token_id],
        kickoff_time=datetime(2026, 4, 5, 15, 0),
        league="EPL",
        home_team=home_team,
        away_team=away_team,
    )


# ---------------------------------------------------------------------------
# _parse_fixed_math
# ---------------------------------------------------------------------------


def test_parse_fixed_math_full():
    assert _parse_fixed_math("100000000") == 100.0


def test_parse_fixed_math_half():
    assert _parse_fixed_math("50000000") == 50.0


def test_parse_fixed_math_zero():
    assert _parse_fixed_math("0") == 0.0


def test_parse_fixed_math_five():
    assert _parse_fixed_math("5000000") == 5.0


# ---------------------------------------------------------------------------
# AC #2: First fill transitions BUY_PLACED → FILLING
# ---------------------------------------------------------------------------


def test_first_fill_transitions_to_filling():
    """First fill detection transitions BUY_PLACED → FILLING and accumulates."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="50000000", status="LIVE"
    )  # 50 shares filled

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    assert pos_tracker.get_accumulated_fills("token-1") == 50.0
    assert entry.lifecycle.state == GameState.FILLING


def test_first_fill_logs_info(caplog):
    """First fill emits INFO log with fill info."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="50000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)

    with caplog.at_level(logging.INFO, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    assert "Fill detected" in caplog.text


# ---------------------------------------------------------------------------
# AC #2: Subsequent fill adds delta only (no duplicate accumulation)
# ---------------------------------------------------------------------------


def test_subsequent_fill_adds_delta_only():
    """Subsequent fill adds only the new delta, not the full size_matched."""
    clob = MagicMock()
    # Second poll: 70 shares matched (previously 50 tracked)
    clob.get_order.return_value = _make_order_response(size_matched="70000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)  # Already tracked 50 shares
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # Should only add 20.0 delta (70 - 50)
    assert pos_tracker.get_accumulated_fills("token-1") == 70.0


# ---------------------------------------------------------------------------
# AC #3: No-change poll is silent
# ---------------------------------------------------------------------------


def test_no_change_poll_silent(caplog):
    """No-change poll produces no INFO log output (AC #3)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="50000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)  # Already tracked 50 shares
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)

    with caplog.at_level(logging.INFO, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    # No INFO-level fill messages should appear
    assert "Fill detected" not in caplog.text


def test_no_change_poll_no_state_change():
    """No-change poll does not change lifecycle state (AC #3)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="50000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # State remains FILLING
    assert entry.lifecycle.state == GameState.FILLING


# ---------------------------------------------------------------------------
# AC #2: Fully filled order marks record inactive
# ---------------------------------------------------------------------------


def test_fully_filled_order_marks_inactive():
    """Fully filled order (MATCHED) marks record inactive."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="100000000", original_size="100000000", status="MATCHED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    record = tracker.get_buy_order("token-1")
    assert record is not None
    assert record.active is False


def test_fully_filled_order_is_excluded_from_subsequent_polls():
    """After MATCHED, get_active_buy_orders returns empty."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="100000000", original_size="100000000", status="MATCHED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # Next poll: no active orders
    clob.get_order.reset_mock()
    service.poll_all_active_orders()
    clob.get_order.assert_not_called()


# ---------------------------------------------------------------------------
# AC #4: Expired/cancelled order with zero fills → EXPIRED
# ---------------------------------------------------------------------------


def test_cancelled_order_zero_fills_transitions_to_expired():
    """Cancelled order with zero fills transitions to EXPIRED (AC #4)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="0", original_size="100000000", status="CANCELED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    assert entry.lifecycle.state == GameState.EXPIRED
    assert tracker.get_buy_order("token-1").active is False


def test_cancelled_order_zero_fills_logs_info(caplog):
    """Cancelled order with zero fills emits INFO log (AC #4)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="0", original_size="100000000", status="CANCELED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)

    with caplog.at_level(logging.INFO, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    assert "expired with no fills" in caplog.text


def test_invalid_order_zero_fills_transitions_to_expired():
    """INVALID order with zero fills transitions to EXPIRED (AC #4)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="0", original_size="100000000", status="INVALID"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    assert entry.lifecycle.state == GameState.EXPIRED


def test_canceled_market_resolved_zero_fills_transitions_to_expired():
    """CANCELED_MARKET_RESOLVED with zero fills transitions to EXPIRED."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="0", original_size="100000000", status="CANCELED_MARKET_RESOLVED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    assert entry.lifecycle.state == GameState.EXPIRED


def test_cancelled_with_partial_fills_not_expired():
    """Cancelled order with partial fills does NOT transition to EXPIRED (only marked inactive)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="50000000", original_size="100000000", status="CANCELED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    pos_tracker.accumulate("token-1", 50.0)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # State remains FILLING — not EXPIRED (partial fills exist)
    assert entry.lifecycle.state == GameState.FILLING
    # But order is marked inactive
    assert tracker.get_buy_order("token-1").active is False


# ---------------------------------------------------------------------------
# AC #5: get_order returns None — WARNING logged, continue polling others
# ---------------------------------------------------------------------------


def test_get_order_returns_none_logs_warning(caplog):
    """When get_order returns None, WARNING is logged (AC #5)."""
    clob = MagicMock()
    clob.get_order.return_value = None  # Retry exhausted

    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)

    with caplog.at_level(logging.WARNING, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    assert "Fill poll failed" in caplog.text


def test_get_order_returns_none_continues_polling_other_orders():
    """When get_order returns None for one order, other orders are still polled (AC #5)."""
    clob = MagicMock()
    # First order: API failure; second order: fills 50 shares
    clob.get_order.side_effect = [
        None,
        _make_order_response(size_matched="50000000", status="LIVE"),
    ]

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1", "Arsenal", "Chelsea")
    entry2 = _register_market(registry, "token-2", "Man City", "Liverpool")

    entry1.lifecycle.transition(GameState.ANALYSED)
    entry1.lifecycle.transition(GameState.BUY_PLACED)
    entry2.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.BUY_PLACED)

    tracker.record_buy("token-1", "order-1", 0.48, 0.50)
    tracker.record_buy("token-2", "order-2", 0.49, 0.51)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # token-1 failed but token-2 should have accumulated 50 shares
    assert pos_tracker.get_accumulated_fills("token-1") == 0.0
    assert pos_tracker.get_accumulated_fills("token-2") == 50.0
    assert entry2.lifecycle.state == GameState.FILLING


# ---------------------------------------------------------------------------
# poll_all_active_orders: iterates all active buy orders
# ---------------------------------------------------------------------------


def test_poll_all_active_orders_iterates_all_active():
    """poll_all_active_orders calls get_order for each active buy order."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="0", status="LIVE")

    tracker = OrderTracker()
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1", "Arsenal", "Chelsea")
    entry2 = _register_market(registry, "token-2", "Man City", "Liverpool")

    entry1.lifecycle.transition(GameState.ANALYSED)
    entry1.lifecycle.transition(GameState.BUY_PLACED)
    entry2.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.BUY_PLACED)

    tracker.record_buy("token-1", "order-1", 0.48, 0.50)
    tracker.record_buy("token-2", "order-2", 0.49, 0.51)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    service.poll_all_active_orders()

    assert clob.get_order.call_count == 2


def test_poll_all_active_orders_no_orders_returns_early():
    """poll_all_active_orders returns early when there are no active orders."""
    clob = MagicMock()
    service = _make_service(clob=clob)
    service.poll_all_active_orders()
    clob.get_order.assert_not_called()


def test_poll_skips_orders_not_in_buy_placed_or_filling():
    """Orders whose market is not in BUY_PLACED or FILLING state are skipped."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="0", status="LIVE")

    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    # Market in ANALYSED state — should be skipped by the polling logic
    entry.lifecycle.transition(GameState.ANALYSED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    service.poll_all_active_orders()

    # get_order should NOT be called — market is not in BUY_PLACED or FILLING
    clob.get_order.assert_not_called()


def test_poll_processes_filling_state_orders():
    """Orders in FILLING state are processed (not skipped)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="70000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # Delta 20 added (70 - 50)
    assert pos_tracker.get_accumulated_fills("token-1") == 70.0
    clob.get_order.assert_called_once()


def test_poll_processes_sell_placed_state_orders():
    """Orders in SELL_PLACED state are still processed to capture later fills."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="70000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    entry.lifecycle.transition(GameState.SELL_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # Delta 20 added (70 - 50)
    assert pos_tracker.get_accumulated_fills("token-1") == 70.0
    clob.get_order.assert_called_once()


def test_poll_handles_missing_market_entry_gracefully():
    """Orders without a market registry entry are still polled (no crash)."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="50000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()  # Empty — no entry for token-1
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    # Should still accumulate fills even without a registry entry
    assert pos_tracker.get_accumulated_fills("token-1") == 50.0


def test_fully_filled_live_order_marks_inactive_by_size_match():
    """Order with LIVE status but size_matched==original_size is marked inactive."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="100000000", original_size="100000000", status="LIVE"
    )

    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    service.poll_all_active_orders()

    record = tracker.get_buy_order("token-1")
    assert record is not None
    assert record.active is False


def test_cancelled_zero_current_but_accumulated_not_expired():
    """EXPIRED transition is based on accumulated fills, not current payload fill."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="0", original_size="100000000", status="CANCELED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    service.poll_all_active_orders()

    assert entry.lifecycle.state == GameState.BUY_PLACED


def test_poll_single_order_exception_does_not_stop_other_orders(caplog):
    """Exceptions while polling one order are logged and polling continues."""
    clob = MagicMock()
    clob.get_order.side_effect = [
        ValueError("bad payload"),
        _make_order_response(size_matched="50000000"),
    ]

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry1 = _register_market(registry, "token-1", "Arsenal", "Chelsea")
    entry2 = _register_market(registry, "token-2", "Man City", "Liverpool")
    entry1.lifecycle.transition(GameState.ANALYSED)
    entry1.lifecycle.transition(GameState.BUY_PLACED)
    entry2.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)
    tracker.record_buy("token-2", "order-2", 0.49, 0.51)

    service = _make_service(clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry)
    with caplog.at_level(logging.WARNING, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    assert "Fill poll failed for order=order-1" in caplog.text
    assert pos_tracker.get_accumulated_fills("token-2") == 50.0


# ---------------------------------------------------------------------------
# AC #1, #3: Sell threshold trigger
# ---------------------------------------------------------------------------


def _make_btts_config_with_min_order_size(min_order_size: float):
    """Return a real BttsConfig-like mock with min_order_size set."""
    btts = MagicMock()
    btts.min_order_size = min_order_size
    return btts


def test_sell_triggered_when_fills_reach_threshold():
    """place_sell_order is called when accumulated fills reach min_order_size threshold."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="5000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    btts = _make_btts_config_with_min_order_size(5.0)
    order_execution = MagicMock()

    service = _make_service(
        clob=clob,
        tracker=tracker,
        pos_tracker=pos_tracker,
        registry=registry,
        btts=btts,
        order_execution=order_execution,
    )
    service.poll_all_active_orders()

    order_execution.place_sell_order.assert_called_once_with("token-1")


def test_sell_not_triggered_below_threshold():
    """place_sell_order is NOT called when accumulated fills are below threshold."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="3000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    btts = _make_btts_config_with_min_order_size(5.0)
    order_execution = MagicMock()

    service = _make_service(
        clob=clob,
        tracker=tracker,
        pos_tracker=pos_tracker,
        registry=registry,
        btts=btts,
        order_execution=order_execution,
    )
    service.poll_all_active_orders()

    order_execution.place_sell_order.assert_not_called()
    order_execution.update_sell_order.assert_not_called()


def test_update_sell_triggered_when_existing_sell_and_new_fills():
    """update_sell_order is called when sell already exists and new fills arrive."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(size_matched="10000000", status="LIVE")

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 5.0)  # Already accumulated 5 shares
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)
    tracker.record_sell("token-1", "sell-order-existing", 0.50, 5.0)  # Existing sell

    btts = _make_btts_config_with_min_order_size(5.0)
    order_execution = MagicMock()

    service = _make_service(
        clob=clob,
        tracker=tracker,
        pos_tracker=pos_tracker,
        registry=registry,
        btts=btts,
        order_execution=order_execution,
    )
    service.poll_all_active_orders()

    order_execution.update_sell_order.assert_called_once_with("token-1")
    order_execution.place_sell_order.assert_not_called()


def test_sell_triggered_on_matched_status():
    """place_sell_order is called after MATCHED terminal status if threshold is met."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="10000000", original_size="10000000", status="MATCHED"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)  # Already fully accumulated — no delta
    registry = MarketRegistry()
    entry = _register_market(registry)
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    btts = _make_btts_config_with_min_order_size(5.0)
    order_execution = MagicMock()

    service = _make_service(
        clob=clob,
        tracker=tracker,
        pos_tracker=pos_tracker,
        registry=registry,
        btts=btts,
        order_execution=order_execution,
    )
    service.poll_all_active_orders()

    order_execution.place_sell_order.assert_called_once_with("token-1")
