"""Tests for btts_bot.core.liquidity — LiquidityAnalyser and MarketAnalysisPipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from btts_bot.config import BttsConfig, LiquidityConfig
from btts_bot.core.game_lifecycle import GameLifecycle, GameState
from btts_bot.core.liquidity import AnalysisResult, LiquidityAnalyser, MarketAnalysisPipeline
from btts_bot.state.market_registry import MarketEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_liquidity_config(**overrides: object) -> LiquidityConfig:
    defaults: dict[str, object] = {
        "standard_depth": 1000,
        "deep_book_threshold": 2000,
        "low_liquidity_total": 500,
        "tick_offset": 0.01,
    }
    defaults.update(overrides)
    return LiquidityConfig(**defaults)  # type: ignore[arg-type]


def _make_btts_config(**overrides: object) -> BttsConfig:
    defaults: dict[str, object] = {
        "order_size": 30,
        "price_diff": 0.02,
        "min_order_size": 5,
        "expiration_hour_offset": 1,
    }
    defaults.update(overrides)
    return BttsConfig(**defaults)  # type: ignore[arg-type]


def _make_orderbook(bids: list[tuple[str, str]]) -> MagicMock:
    """Create a mock OrderBookSummary with the given bids.

    Each bid is a tuple of (price_str, size_str).
    """
    ob = MagicMock()
    ob.bids = [MagicMock(price=p, size=s) for p, s in bids]
    return ob


def _make_market_entry(token_id: str = "token-1") -> MarketEntry:
    lifecycle = GameLifecycle(token_id)
    return MarketEntry(
        token_id=token_id,
        condition_id="cond-1",
        token_ids=[token_id],
        kickoff_time=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        league="EPL",
        home_team="Arsenal",
        away_team="Chelsea",
        lifecycle=lifecycle,
    )


# ---------------------------------------------------------------------------
# LiquidityAnalyser — three-case algorithm tests
# ---------------------------------------------------------------------------


class TestLiquidityAnalyserCaseB:
    """Case B: total depth >= deep_book_threshold → buy at L2 price."""

    def test_case_b_returns_l2_price(self) -> None:
        config = _make_liquidity_config(deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # 800 + 700 + 600 = 2100 >= 2000 (deep book)
        ob = _make_orderbook([("0.50", "800"), ("0.49", "700"), ("0.48", "600")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.token_id == "token-1"
        assert result.buy_price == pytest.approx(0.49)
        assert result.case == "B"

    def test_case_b_exactly_at_threshold(self) -> None:
        config = _make_liquidity_config(deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # Total exactly 2000
        ob = _make_orderbook([("0.55", "700"), ("0.54", "800"), ("0.53", "500")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.buy_price == pytest.approx(0.54)
        assert result.case == "B"


class TestLiquidityAnalyserCaseA:
    """Case A: total depth >= standard_depth and < deep_book_threshold → buy at L3 price."""

    def test_case_a_returns_l3_price(self) -> None:
        config = _make_liquidity_config(standard_depth=1000, deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # 500 + 400 + 300 = 1200 >= 1000 and < 2000 (standard)
        ob = _make_orderbook([("0.50", "500"), ("0.49", "400"), ("0.48", "300")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.buy_price == pytest.approx(0.48)
        assert result.case == "A"

    def test_case_a_exactly_at_standard_depth(self) -> None:
        config = _make_liquidity_config(standard_depth=1000, deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # Exactly at standard_depth boundary (1000)
        ob = _make_orderbook([("0.60", "400"), ("0.59", "400"), ("0.58", "200")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.buy_price == pytest.approx(0.58)
        assert result.case == "A"

    def test_case_a_one_below_deep_threshold(self) -> None:
        config = _make_liquidity_config(standard_depth=1000, deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # 1999 < 2000, so Case A not B
        ob = _make_orderbook([("0.50", "700"), ("0.49", "700"), ("0.48", "599")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.case == "A"


class TestLiquidityAnalyserCaseC:
    """Case C: total depth >= low_liquidity_total and < standard_depth → buy at L3 - tick_offset."""

    def test_case_c_returns_l3_minus_tick_offset(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, low_liquidity_total=500, tick_offset=0.01
        )
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # 300 + 200 + 100 = 600 >= 500 and < 1000 (thin liquidity)
        ob = _make_orderbook([("0.50", "300"), ("0.49", "200"), ("0.48", "100")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.buy_price == pytest.approx(0.48 - 0.01)
        assert result.case == "C"

    def test_case_c_exactly_at_low_liquidity_boundary(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, low_liquidity_total=500, tick_offset=0.01
        )
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # Exactly 500 == low_liquidity_total → Case C
        ob = _make_orderbook([("0.50", "200"), ("0.49", "200"), ("0.48", "100")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.case == "C"

    def test_case_c_negative_buy_price_returns_none(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, low_liquidity_total=500, tick_offset=0.50
        )
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # L3 price 0.48 - tick_offset 0.50 = -0.02 → skip
        ob = _make_orderbook([("0.50", "300"), ("0.49", "200"), ("0.48", "100")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None


class TestLiquidityAnalyserSkip:
    """Insufficient liquidity → skip market, return None."""

    def test_skip_total_depth_below_low_liquidity_total(self) -> None:
        config = _make_liquidity_config(low_liquidity_total=500)
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        # 100 + 100 + 100 = 300 < 500 → skip
        ob = _make_orderbook([("0.50", "100"), ("0.49", "100"), ("0.48", "100")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None

    def test_skip_fewer_than_3_bids(self) -> None:
        config = _make_liquidity_config()
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.50", "800"), ("0.49", "700")])  # only 2 bids
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None

    def test_skip_empty_orderbook(self) -> None:
        config = _make_liquidity_config()
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([])  # 0 bids
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None

    def test_skip_bids_is_none(self) -> None:
        config = _make_liquidity_config()
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = MagicMock()
        ob.bids = None
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None

    def test_skip_invalid_price_string(self) -> None:
        config = _make_liquidity_config()
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = MagicMock()
        ob.bids = [
            MagicMock(price="not-a-number", size="800"),
            MagicMock(price="0.49", size="700"),
            MagicMock(price="0.48", size="600"),
        ]
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None

    def test_skip_none_price(self) -> None:
        config = _make_liquidity_config()
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = MagicMock()
        ob.bids = [
            MagicMock(price=None, size="800"),
            MagicMock(price="0.49", size="700"),
            MagicMock(price="0.48", size="600"),
        ]
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is None


class TestSellPriceDeriivation:
    """Sell price = buy_price + price_diff, capped at 0.99."""

    def test_sell_price_derivation(self) -> None:
        config = _make_liquidity_config(deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.50", "800"), ("0.49", "700"), ("0.48", "600")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        # L2=0.49, sell=0.49+0.02=0.51
        assert result.sell_price == pytest.approx(0.51)

    def test_sell_price_capped_at_0_99(self) -> None:
        config = _make_liquidity_config(deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.02)
        analyser = LiquidityAnalyser(config, btts)
        # L2=0.98, sell would be 1.00 → capped at 0.99
        ob = _make_orderbook([("0.99", "800"), ("0.98", "700"), ("0.97", "600")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.sell_price == pytest.approx(0.99)

    def test_sell_price_exactly_at_cap(self) -> None:
        config = _make_liquidity_config(deep_book_threshold=2000)
        btts = _make_btts_config(price_diff=0.01)
        analyser = LiquidityAnalyser(config, btts)
        # L2=0.98, sell=0.98+0.01=0.99 → exactly at cap
        ob = _make_orderbook([("0.99", "800"), ("0.98", "700"), ("0.97", "600")])
        result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
        assert result is not None
        assert result.sell_price == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# Boundary value tests
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    """Boundary conditions at exact threshold values."""

    def test_exactly_at_deep_book_threshold_uses_case_b(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "700"), ("0.54", "800"), ("0.53", "500")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is not None
        assert result.case == "B"

    def test_one_below_deep_book_threshold_uses_case_a(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "700"), ("0.54", "799"), ("0.53", "500")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is not None
        assert result.case == "A"

    def test_exactly_at_standard_depth_uses_case_a(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "400"), ("0.54", "400"), ("0.53", "200")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is not None
        assert result.case == "A"

    def test_one_below_standard_depth_uses_case_c(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "400"), ("0.54", "399"), ("0.53", "200")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is not None
        assert result.case == "C"

    def test_exactly_at_low_liquidity_total_uses_case_c(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "200"), ("0.54", "200"), ("0.53", "100")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is not None
        assert result.case == "C"

    def test_one_below_low_liquidity_total_skips(self) -> None:
        config = _make_liquidity_config(
            standard_depth=1000, deep_book_threshold=2000, low_liquidity_total=500
        )
        btts = _make_btts_config()
        analyser = LiquidityAnalyser(config, btts)
        ob = _make_orderbook([("0.55", "200"), ("0.54", "199"), ("0.53", "100")])
        result = analyser.analyse(ob, "token-1", "[A vs B]")
        assert result is None


# ---------------------------------------------------------------------------
# MarketAnalysisPipeline tests
# ---------------------------------------------------------------------------


def _make_pipeline(
    orderbook_return: object = None,
    analyse_return: AnalysisResult | None = None,
    registry_entry: MarketEntry | None = None,
) -> tuple[MarketAnalysisPipeline, MagicMock, MagicMock, MagicMock]:
    mock_clob = MagicMock()
    mock_clob.get_order_book.return_value = orderbook_return

    mock_analyser = MagicMock()
    mock_analyser.analyse.return_value = analyse_return

    mock_registry = MagicMock()
    mock_registry.get.return_value = registry_entry

    pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
    return pipeline, mock_clob, mock_analyser, mock_registry


class TestMarketAnalysisPipelineAnalyseMarket:
    """Unit tests for MarketAnalysisPipeline.analyse_market."""

    def test_success_path_transitions_to_analysed(self) -> None:
        entry = _make_market_entry("token-1")
        result = AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A")
        ob = MagicMock()
        pipeline, mock_clob, mock_analyser, mock_registry = _make_pipeline(
            orderbook_return=ob, analyse_return=result, registry_entry=entry
        )

        returned = pipeline.analyse_market("token-1")

        assert returned is result
        assert entry.lifecycle.state == GameState.ANALYSED
        mock_clob.get_order_book.assert_called_once_with("token-1")
        mock_analyser.analyse.assert_called_once_with(ob, "token-1", "[Arsenal vs Chelsea]")

    def test_skip_path_transitions_to_skipped(self) -> None:
        entry = _make_market_entry("token-1")
        ob = MagicMock()
        pipeline, mock_clob, mock_analyser, mock_registry = _make_pipeline(
            orderbook_return=ob, analyse_return=None, registry_entry=entry
        )

        returned = pipeline.analyse_market("token-1")

        assert returned is None
        assert entry.lifecycle.state == GameState.SKIPPED

    def test_orderbook_fetch_none_transitions_to_skipped(self) -> None:
        entry = _make_market_entry("token-1")
        pipeline, mock_clob, mock_analyser, mock_registry = _make_pipeline(
            orderbook_return=None, registry_entry=entry
        )

        returned = pipeline.analyse_market("token-1")

        assert returned is None
        assert entry.lifecycle.state == GameState.SKIPPED
        mock_analyser.analyse.assert_not_called()

    def test_returns_analysis_result_on_success(self) -> None:
        entry = _make_market_entry("token-1")
        expected = AnalysisResult(token_id="token-1", buy_price=0.50, sell_price=0.52, case="B")
        ob = MagicMock()
        pipeline, *_ = _make_pipeline(
            orderbook_return=ob, analyse_return=expected, registry_entry=entry
        )

        result = pipeline.analyse_market("token-1")

        assert result is expected

    def test_no_registry_entry_does_not_crash(self) -> None:
        """analyse_market handles missing registry entry gracefully."""
        result = AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A")
        ob = MagicMock()
        pipeline, *_ = _make_pipeline(
            orderbook_return=ob, analyse_return=result, registry_entry=None
        )
        # Should not raise even without a registry entry (no lifecycle to transition)
        returned = pipeline.analyse_market("token-1")
        assert returned is result


class TestMarketAnalysisPipelineAnalyseAllDiscovered:
    """Unit tests for MarketAnalysisPipeline.analyse_all_discovered."""

    def test_processes_only_discovered_markets(self) -> None:
        entry_discovered = _make_market_entry("token-1")
        entry_analysed = _make_market_entry("token-2")
        entry_analysed.lifecycle.transition(GameState.ANALYSED)

        mock_clob = MagicMock()
        mock_analyser = MagicMock()
        mock_analyser.analyse.return_value = AnalysisResult(
            token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"
        )
        ob = MagicMock()
        mock_clob.get_order_book.return_value = ob

        mock_registry = MagicMock()
        mock_registry.all_markets.return_value = [entry_discovered, entry_analysed]
        mock_registry.get.side_effect = lambda tid: {
            "token-1": entry_discovered,
            "token-2": entry_analysed,
        }.get(tid)

        pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
        results = pipeline.analyse_all_discovered()

        # Only token-1 (DISCOVERED) should have been fetched
        mock_clob.get_order_book.assert_called_once_with("token-1")
        assert len(results) == 1

    def test_empty_registry_returns_empty_list(self) -> None:
        mock_clob = MagicMock()
        mock_analyser = MagicMock()
        mock_registry = MagicMock()
        mock_registry.all_markets.return_value = []

        pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
        results = pipeline.analyse_all_discovered()

        assert results == []
        mock_clob.get_order_book.assert_not_called()

    def test_all_markets_already_analysed_returns_empty(self) -> None:
        entry = _make_market_entry("token-1")
        entry.lifecycle.transition(GameState.ANALYSED)

        mock_clob = MagicMock()
        mock_analyser = MagicMock()
        mock_registry = MagicMock()
        mock_registry.all_markets.return_value = [entry]

        pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
        results = pipeline.analyse_all_discovered()

        assert results == []

    def test_skipped_markets_not_included_in_results(self) -> None:
        entry1 = _make_market_entry("token-1")
        entry2 = _make_market_entry("token-2")

        mock_clob = MagicMock()
        mock_analyser = MagicMock()
        # token-1 → success; token-2 → skip (None)
        success_result = AnalysisResult(
            token_id="token-1", buy_price=0.48, sell_price=0.50, case="A"
        )
        ob = MagicMock()
        mock_clob.get_order_book.return_value = ob
        mock_analyser.analyse.side_effect = [success_result, None]

        mock_registry = MagicMock()
        mock_registry.all_markets.return_value = [entry1, entry2]
        mock_registry.get.side_effect = lambda tid: {
            "token-1": entry1,
            "token-2": entry2,
        }.get(tid)

        pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
        results = pipeline.analyse_all_discovered()

        assert len(results) == 1
        assert results[0] is success_result

    def test_multiple_discovered_all_analysed(self) -> None:
        entries = [_make_market_entry(f"token-{i}") for i in range(3)]

        mock_clob = MagicMock()
        mock_analyser = MagicMock()
        ob = MagicMock()
        mock_clob.get_order_book.return_value = ob
        mock_analyser.analyse.side_effect = [
            AnalysisResult(token_id=f"token-{i}", buy_price=0.48, sell_price=0.50, case="A")
            for i in range(3)
        ]

        mock_registry = MagicMock()
        mock_registry.all_markets.return_value = entries
        mock_registry.get.side_effect = lambda tid: next(
            (e for e in entries if e.token_id == tid), None
        )

        pipeline = MarketAnalysisPipeline(mock_clob, mock_analyser, mock_registry)
        results = pipeline.analyse_all_discovered()

        assert len(results) == 3
        assert mock_clob.get_order_book.call_count == 3


# ---------------------------------------------------------------------------
# AnalysisResult dataclass
# ---------------------------------------------------------------------------


class TestAnalysisResult:
    def test_analysis_result_fields(self) -> None:
        r = AnalysisResult(token_id="token-1", buy_price=0.48, sell_price=0.50, case="A")
        assert r.token_id == "token-1"
        assert r.buy_price == 0.48
        assert r.sell_price == 0.50
        assert r.case == "A"
