"""Tests for btts_bot.core.order_execution — OrderExecutionService."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.liquidity import AnalysisResult
from btts_bot.core.order_execution import OrderExecutionService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker


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
    registry: MarketRegistry | None = None,
    btts: BttsConfig | None = None,
) -> OrderExecutionService:
    return OrderExecutionService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
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
        kickoff_time=datetime(2026, 4, 5, 15, 0, tzinfo=timezone.utc),
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
    kickoff_dt = datetime(2026, 4, 5, 15, 0, tzinfo=timezone.utc)
    expected_ts = int(kickoff_dt.timestamp()) - 2 * 3600
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
    kickoff_dt = datetime(2026, 4, 5, 15, 0, tzinfo=timezone.utc)
    expected_ts = int(kickoff_dt.timestamp()) - 1 * 3600
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
    kickoff_dt = datetime(2026, 4, 5, 15, 0, tzinfo=timezone.utc)
    expected_ts = int(kickoff_dt.timestamp()) - 3 * 3600
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
