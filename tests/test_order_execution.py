"""Tests for btts_bot.core.order_execution — OrderExecutionService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.liquidity import AnalysisResult
from btts_bot.core.order_execution import OrderExecutionService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_btts_config(**overrides: object) -> BttsConfig:
    defaults: dict[str, object] = {
        "order_size": 30,
        "price_diff": 0.02,
        "min_order_size": 5,
        "expiration_hour_offset": 1,
    }
    defaults.update(overrides)
    return BttsConfig(**defaults)  # type: ignore[arg-type]


def _make_service(
    clob: object = None,
    tracker: OrderTracker | None = None,
    position_tracker: PositionTracker | None = None,
    registry: MarketRegistry | None = None,
    btts: BttsConfig | None = None,
) -> OrderExecutionService:
    return OrderExecutionService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=position_tracker or PositionTracker(),
        market_registry=registry or MarketRegistry(),
        btts_config=btts or _make_btts_config(),
    )


def _register_market(
    registry: MarketRegistry,
    token_id: str = "token-1",
    home_team: str = "Arsenal",
    away_team: str = "Chelsea",
) -> object:
    """Register a market and return the MarketEntry."""
    return registry.register(
        token_id=token_id,
        condition_id=f"cond-{token_id}",
        token_ids=[token_id],
        kickoff_time=datetime.now(timezone.utc) + timedelta(days=30),
        league="EPL",
        home_team=home_team,
        away_team=away_team,
    )


# ---------------------------------------------------------------------------
# place_buy_order — success path (AC #2)
# ---------------------------------------------------------------------------


def test_place_buy_order_success():
    """Successful buy order: API called, recorded in tracker, lifecycle transitions to BUY_PLACED."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-123"}
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is True
    assert tracker.has_buy_order("token-1")
    assert tracker.get_buy_order("token-1").order_id == "order-123"
    assert tracker.get_buy_order("token-1").buy_price == pytest.approx(0.48)
    assert entry.lifecycle.state == GameState.BUY_PLACED
    clob.get_tick_size.assert_called_once_with("token-1")
    clob.create_buy_order.assert_called_once()


def test_place_buy_order_success_logs_info(caplog: pytest.LogCaptureFixture):
    """Successful buy order emits INFO log with token, price, size."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-456"}
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("INFO", logger="btts_bot.core.order_execution"):
        service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert "Buy order placed" in caplog.text
    assert "token-1" in caplog.text


def test_place_buy_order_uses_correct_clob_args():
    """place_buy_order passes token_id, buy_price, order_size, expiration to create_buy_order."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-789"}
    btts = _make_btts_config(order_size=25, expiration_hour_offset=2)
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry, btts=btts)
    service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    call_kwargs = clob.create_buy_order.call_args.kwargs
    assert call_kwargs["token_id"] == "token-1"
    assert call_kwargs["price"] == pytest.approx(0.48)
    assert call_kwargs["size"] == pytest.approx(25.0)
    # Expiration is kickoff_ts - 2 * 3600
    entry_obj = registry.get("token-1")
    expected_ts = int(entry_obj.kickoff_time.timestamp()) - 2 * 3600
    assert call_kwargs["expiration_ts"] == expected_ts


# ---------------------------------------------------------------------------
# place_buy_order — duplicate prevention (AC #3)
# ---------------------------------------------------------------------------


def test_place_buy_order_duplicate_prevented(caplog: pytest.LogCaptureFixture):
    """Duplicate buy order is prevented: WARNING logged, no API call made."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "existing-order", 0.48, 0.50)
    registry = MarketRegistry()
    _register_market(registry, "token-1")

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("WARNING", logger="btts_bot.core.order_execution"):
        result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    clob.get_tick_size.assert_not_called()
    clob.create_buy_order.assert_not_called()
    assert "Duplicate buy prevented" in caplog.text


def test_place_buy_order_duplicate_does_not_overwrite_tracker():
    """Duplicate prevention: existing buy order record is NOT overwritten."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "original-order-id", 0.48, 0.50)
    registry = MarketRegistry()
    _register_market(registry, "token-1")

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    service.place_buy_order("token-1", buy_price=0.50, sell_price=0.52)

    # Original order still intact
    assert tracker.get_buy_order("token-1").order_id == "original-order-id"


# ---------------------------------------------------------------------------
# place_buy_order — API failure (AC #4)
# ---------------------------------------------------------------------------


def test_place_buy_order_api_failure_returns_false(caplog: pytest.LogCaptureFixture):
    """API failure (None response): ERROR logged, lifecycle transitions to SKIPPED."""
    clob = MagicMock()
    clob.create_buy_order.return_value = None  # Retry exhausted
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert not tracker.has_buy_order("token-1")
    assert entry.lifecycle.state == GameState.SKIPPED
    assert "Buy order failed" in caplog.text


def test_place_buy_order_empty_order_id_transitions_to_skipped(caplog: pytest.LogCaptureFixture):
    """If response has no orderID, lifecycle transitions to SKIPPED and returns False."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": ""}  # Empty order ID
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert not tracker.has_buy_order("token-1")
    assert entry.lifecycle.state == GameState.SKIPPED
    assert "no orderID" in caplog.text


def test_place_buy_order_no_registry_entry_api_failure_does_not_crash():
    """API failure with no registry entry: returns False without crashing."""
    clob = MagicMock()
    clob.create_buy_order.return_value = None
    tracker = OrderTracker()
    registry = MarketRegistry()  # No entry registered

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("unknown-token", buy_price=0.48, sell_price=0.50)

    assert result is False
    clob.get_tick_size.assert_not_called()
    clob.create_buy_order.assert_not_called()


def test_place_buy_order_no_registry_entry_is_skipped():
    """Missing registry entry is skipped before any API call."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-xyz"}
    tracker = OrderTracker()
    registry = MarketRegistry()  # No entry registered

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("unknown-token", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert not tracker.has_buy_order("unknown-token")
    clob.get_tick_size.assert_not_called()
    clob.create_buy_order.assert_not_called()


def test_place_buy_order_non_retryable_exception_transitions_to_skipped(
    caplog: pytest.LogCaptureFixture,
):
    """Non-retryable API exception is handled and market transitions to SKIPPED."""
    clob = MagicMock()
    clob.create_buy_order.side_effect = RuntimeError("bad request")
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert not tracker.has_buy_order("token-1")
    assert entry.lifecycle.state == GameState.SKIPPED
    assert "non-retryable error" in caplog.text


# ---------------------------------------------------------------------------
# Expiration timestamp calculation
# ---------------------------------------------------------------------------


def test_expiration_timestamp_uses_expiration_hour_offset():
    """Expiration timestamp is kickoff_ts - expiration_hour_offset * 3600."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-ts"}
    btts = _make_btts_config(expiration_hour_offset=1)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, registry=registry, btts=btts)
    service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    call_kwargs = clob.create_buy_order.call_args.kwargs
    expected_ts = int(entry.kickoff_time.timestamp()) - 1 * 3600
    assert call_kwargs["expiration_ts"] == expected_ts


def test_expiration_timestamp_different_offset():
    """Expiration uses configured expiration_hour_offset (not hardcoded)."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-ts2"}
    btts = _make_btts_config(expiration_hour_offset=3)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, registry=registry, btts=btts)
    service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    call_kwargs = clob.create_buy_order.call_args.kwargs
    expected_ts = int(entry.kickoff_time.timestamp()) - 3 * 3600
    assert call_kwargs["expiration_ts"] == expected_ts


def test_place_buy_order_expired_timestamp_is_skipped(caplog: pytest.LogCaptureFixture):
    """Computed expiration in the past is skipped without API call."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-old"}
    btts = _make_btts_config(expiration_hour_offset=4)
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = registry.register(
        token_id="token-1",
        condition_id="cond-token-1",
        token_ids=["token-1"],
        kickoff_time=datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc),
        league="EPL",
        home_team="Arsenal",
        away_team="Chelsea",
    )
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry, btts=btts)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert entry.lifecycle.state == GameState.SKIPPED
    assert not tracker.has_buy_order("token-1")
    clob.get_tick_size.assert_not_called()
    clob.create_buy_order.assert_not_called()
    assert "expiration is not in the future" in caplog.text


# ---------------------------------------------------------------------------
# execute_all_analysed (AC #2)
# ---------------------------------------------------------------------------


def test_execute_all_analysed_success_count():
    """execute_all_analysed returns count of successfully placed orders."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-1"}
    tracker = OrderTracker()
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1", "Arsenal", "Chelsea")
    entry2 = _register_market(registry, "token-2", "Man City", "Liverpool")
    entry1.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.ANALYSED)

    analysis_results = [
        AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"),
        AnalysisResult(token_id="token-2", buy_price=0.49, sell_price=0.51, case="B"),
    ]

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    assert count == 2
    assert tracker.has_buy_order("token-1")
    assert tracker.has_buy_order("token-2")


def test_execute_all_analysed_processes_only_analysed_markets():
    """execute_all_analysed skips markets not in ANALYSED state."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-1"}
    tracker = OrderTracker()
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1")
    _register_market(registry, "token-2")
    entry1.lifecycle.transition(GameState.ANALYSED)
    # entry2 stays in DISCOVERED state — should be skipped

    analysis_results = [
        AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"),
        AnalysisResult(token_id="token-2", buy_price=0.49, sell_price=0.51, case="B"),
    ]

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    assert count == 1
    assert tracker.has_buy_order("token-1")
    assert not tracker.has_buy_order("token-2")
    clob.create_buy_order.assert_called_once()


def test_execute_all_analysed_skips_existing_buy_orders():
    """execute_all_analysed skips markets where buy order already exists."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "new-order"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "existing-order", 0.48, 0.50)  # Pre-existing buy
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1")
    entry2 = _register_market(registry, "token-2")
    entry1.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.ANALYSED)

    analysis_results = [
        AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"),
        AnalysisResult(token_id="token-2", buy_price=0.49, sell_price=0.51, case="B"),
    ]

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    # Only token-2 should get a new order
    assert count == 1
    assert tracker.get_buy_order("token-1").order_id == "existing-order"
    assert tracker.has_buy_order("token-2")
    clob.create_buy_order.assert_called_once()


def test_execute_all_analysed_returns_zero_when_no_analysed_markets():
    """execute_all_analysed returns 0 if no markets are in ANALYSED state."""
    clob = MagicMock()
    tracker = OrderTracker()
    registry = MarketRegistry()
    # Register market but leave in DISCOVERED state
    _register_market(registry, "token-1")

    analysis_results = [
        AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"),
    ]

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    assert count == 0
    clob.create_buy_order.assert_not_called()


def test_execute_all_analysed_returns_zero_for_empty_registry():
    """execute_all_analysed returns 0 with empty market registry."""
    clob = MagicMock()
    tracker = OrderTracker()
    registry = MarketRegistry()

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed([])

    assert count == 0
    clob.create_buy_order.assert_not_called()


def test_execute_all_analysed_skips_markets_with_no_matching_analysis():
    """execute_all_analysed skips ANALYSED markets that have no matching AnalysisResult."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-1"}
    tracker = OrderTracker()
    registry = MarketRegistry()

    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)

    # No analysis result for token-1
    analysis_results: list[AnalysisResult] = []

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    assert count == 0
    clob.create_buy_order.assert_not_called()


def test_execute_all_analysed_partial_failures():
    """execute_all_analysed returns only count of successfully placed orders."""
    clob = MagicMock()
    # First call succeeds, second fails (None)
    clob.create_buy_order.side_effect = [{"orderID": "order-1"}, None]
    tracker = OrderTracker()
    registry = MarketRegistry()

    entry1 = _register_market(registry, "token-1")
    entry2 = _register_market(registry, "token-2")
    entry1.lifecycle.transition(GameState.ANALYSED)
    entry2.lifecycle.transition(GameState.ANALYSED)

    analysis_results = [
        AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"),
        AnalysisResult(token_id="token-2", buy_price=0.49, sell_price=0.51, case="B"),
    ]

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    count = service.execute_all_analysed(analysis_results)

    # Only 1 succeeded
    assert count == 1
    assert tracker.has_buy_order("token-1")
    assert not tracker.has_buy_order("token-2")
    assert entry2.lifecycle.state == GameState.SKIPPED


# ---------------------------------------------------------------------------
# place_sell_order (AC #1, #2, #4)
# ---------------------------------------------------------------------------


def test_place_sell_order_success():
    """Successful sell order: API called, recorded in tracker, lifecycle → SELL_PLACED."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-order-1"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    result = service.place_sell_order("token-1")

    assert result is True
    assert tracker.has_sell_order("token-1")
    assert tracker.get_sell_order("token-1").order_id == "sell-order-1"
    assert entry.lifecycle.state == GameState.SELL_PLACED


def test_place_sell_order_uses_precomputed_sell_price():
    """place_sell_order uses buy_record.sell_price (pre-computed), not a new calculation."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-order-2"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.55)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    service.place_sell_order("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.55)


def test_place_sell_order_uses_accumulated_fills_as_size():
    """place_sell_order uses position_tracker accumulated fills as sell size."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-order-3"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 15.5)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    service.place_sell_order("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[2] == pytest.approx(15.5)


def test_place_sell_order_caps_sell_price_at_099():
    """place_sell_order caps sell_price at 0.99 even if buy_record.sell_price is higher."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-order-cap"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 1.00)  # sell_price above 0.99
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    service.place_sell_order("token-1")

    call_args = clob.create_sell_order.call_args
    assert call_args.args[1] == pytest.approx(0.99)


def test_place_sell_order_duplicate_prevented():
    """Duplicate sell order is prevented: no API call, returns False."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    tracker.record_sell("token-1", "sell-order-existing", 0.52, 10.0)
    pos_tracker = PositionTracker()

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    result = service.place_sell_order("token-1")

    assert result is False
    clob.create_sell_order.assert_not_called()


def test_place_sell_order_no_buy_record_returns_false(caplog: pytest.LogCaptureFixture):
    """place_sell_order returns False and logs ERROR when no buy order exists."""
    clob = MagicMock()
    tracker = OrderTracker()  # No buy record

    service = _make_service(clob=clob, tracker=tracker)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_sell_order("token-1")

    assert result is False
    clob.create_sell_order.assert_not_called()
    assert "no buy order record" in caplog.text


def test_place_sell_order_api_failure_returns_false(caplog: pytest.LogCaptureFixture):
    """API failure (None response): ERROR logged, returns False, lifecycle NOT changed."""
    clob = MagicMock()
    clob.create_sell_order.return_value = None
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.place_sell_order("token-1")

    assert result is False
    assert not tracker.has_sell_order("token-1")
    # Lifecycle must NOT transition to SKIPPED
    assert entry.lifecycle.state == GameState.FILLING
    assert "Sell order failed" in caplog.text


def test_place_sell_order_logs_info_on_success(caplog: pytest.LogCaptureFixture):
    """Successful sell order emits INFO log."""
    clob = MagicMock()
    clob.create_sell_order.return_value = {"orderID": "sell-order-log"}
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)
    registry = MarketRegistry()
    entry = _register_market(registry, "token-1")
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)

    service = _make_service(
        clob=clob, tracker=tracker, position_tracker=pos_tracker, registry=registry
    )
    with caplog.at_level("INFO", logger="btts_bot.core.order_execution"):
        service.place_sell_order("token-1")

    assert "Sell order placed" in caplog.text


# ---------------------------------------------------------------------------
# update_sell_order (AC #3)
# ---------------------------------------------------------------------------


def test_update_sell_order_no_existing_sell_returns_false():
    """update_sell_order returns False when there is no existing sell order."""
    clob = MagicMock()
    tracker = OrderTracker()

    service = _make_service(clob=clob, tracker=tracker)
    result = service.update_sell_order("token-1")

    assert result is False
    clob.cancel_order.assert_not_called()


def test_update_sell_order_no_size_increase_returns_false():
    """update_sell_order returns False when accumulated fills <= existing sell size."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_sell("token-1", "sell-order-1", 0.52, 10.0)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 10.0)  # Same as existing sell size

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    result = service.update_sell_order("token-1")

    assert result is False
    clob.cancel_order.assert_not_called()


def test_update_sell_order_cancels_and_replaces():
    """update_sell_order cancels old sell and places new one with larger size."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "sell-order-new"}
    tracker = OrderTracker()
    tracker.record_sell("token-1", "sell-order-old", 0.52, 10.0)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 15.0)  # More than existing 10.0

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    result = service.update_sell_order("token-1")

    assert result is True
    clob.cancel_order.assert_called_once_with("sell-order-old")
    clob.create_sell_order.assert_called_once()
    new_record = tracker.get_sell_order("token-1")
    assert new_record is not None
    assert new_record.order_id == "sell-order-new"
    assert new_record.sell_size == pytest.approx(15.0)


def test_update_sell_order_cancel_failure_keeps_old_record(caplog: pytest.LogCaptureFixture):
    """If cancel fails (None), old sell record is kept and returns False."""
    clob = MagicMock()
    clob.cancel_order.return_value = None  # Cancel failed
    tracker = OrderTracker()
    tracker.record_sell("token-1", "sell-order-old", 0.52, 10.0)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 15.0)

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.update_sell_order("token-1")

    assert result is False
    # Old record must still be there
    assert tracker.has_sell_order("token-1")
    assert tracker.get_sell_order("token-1").order_id == "sell-order-old"
    clob.create_sell_order.assert_not_called()
    assert "Sell update failed" in caplog.text


def test_update_sell_order_new_sell_failure_logs_error(caplog: pytest.LogCaptureFixture):
    """If cancel succeeds but new sell fails, ERROR is logged and returns False."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = None  # New sell failed
    tracker = OrderTracker()
    tracker.record_sell("token-1", "sell-order-old", 0.52, 10.0)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 15.0)

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    with caplog.at_level("ERROR", logger="btts_bot.core.order_execution"):
        result = service.update_sell_order("token-1")

    assert result is False
    # Old record was removed (cancel succeeded), new record not stored
    assert not tracker.has_sell_order("token-1")
    assert "cancel succeeded but new sell failed" in caplog.text


def test_update_sell_order_logs_info_on_success(caplog: pytest.LogCaptureFixture):
    """Successful sell update emits INFO log with new and old sizes."""
    clob = MagicMock()
    clob.cancel_order.return_value = {"success": True}
    clob.create_sell_order.return_value = {"orderID": "sell-order-updated"}
    tracker = OrderTracker()
    tracker.record_sell("token-1", "sell-order-old", 0.52, 10.0)
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 20.0)

    service = _make_service(clob=clob, tracker=tracker, position_tracker=pos_tracker)
    with caplog.at_level("INFO", logger="btts_bot.core.order_execution"):
        service.update_sell_order("token-1")

    assert "Sell order updated" in caplog.text


# ---------------------------------------------------------------------------
# Pre-kickoff trigger registration (Task 9 / AC #1)
# ---------------------------------------------------------------------------


def _make_service_with_scheduler(
    clob: object = None,
    tracker: OrderTracker | None = None,
    registry: MarketRegistry | None = None,
    btts: BttsConfig | None = None,
    scheduler_service: object = None,
) -> OrderExecutionService:
    """Build OrderExecutionService with an injected scheduler."""
    return OrderExecutionService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=PositionTracker(),
        market_registry=registry or MarketRegistry(),
        btts_config=btts or _make_btts_config(),
        scheduler_service=scheduler_service,
    )


def test_place_buy_order_success_calls_schedule_pre_kickoff() -> None:
    """After successful buy placement, scheduler.schedule_pre_kickoff is called with correct args."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-sched-1"}
    scheduler = MagicMock()
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-sched")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service_with_scheduler(
        clob=clob, tracker=tracker, registry=registry, scheduler_service=scheduler
    )
    result = service.place_buy_order("token-sched", buy_price=0.48, sell_price=0.50)

    assert result is True
    scheduler.schedule_pre_kickoff.assert_called_once_with("token-sched", entry.kickoff_time)


def test_place_buy_order_success_calls_schedule_game_start() -> None:
    """After successful buy placement, scheduler.schedule_game_start is called with correct args."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-sched-gs"}
    scheduler = MagicMock()
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-sched-gs")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service_with_scheduler(
        clob=clob, tracker=tracker, registry=registry, scheduler_service=scheduler
    )
    result = service.place_buy_order("token-sched-gs", buy_price=0.48, sell_price=0.50)

    assert result is True
    scheduler.schedule_game_start.assert_called_once_with("token-sched-gs", entry.kickoff_time)


def test_place_buy_order_api_failure_does_not_call_scheduler() -> None:
    """After failed buy placement (None response), scheduler methods are NOT called."""
    clob = MagicMock()
    clob.create_buy_order.return_value = None  # API failure
    scheduler = MagicMock()
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-sched-fail")
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service_with_scheduler(
        clob=clob, tracker=tracker, registry=registry, scheduler_service=scheduler
    )
    result = service.place_buy_order("token-sched-fail", buy_price=0.48, sell_price=0.50)

    assert result is False
    scheduler.schedule_pre_kickoff.assert_not_called()
    scheduler.schedule_game_start.assert_not_called()


def test_place_buy_order_no_scheduler_service_does_not_crash() -> None:
    """place_buy_order succeeds without a scheduler_service (backward-compatible None default)."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-no-sched"}
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = _register_market(registry, "token-nosched")
    entry.lifecycle.transition(GameState.ANALYSED)

    # No scheduler_service passed (defaults to None)
    service = _make_service_with_scheduler(
        clob=clob, tracker=tracker, registry=registry, scheduler_service=None
    )
    result = service.place_buy_order("token-nosched", buy_price=0.48, sell_price=0.50)

    assert result is True
