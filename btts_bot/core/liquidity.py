"""
Orderbook liquidity analysis for BTTS markets.
Implemented in Story 2.4.
"""

from __future__ import annotations

import dataclasses
import logging

from py_clob_client.clob_types import OrderBookSummary

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.config import BttsConfig, LiquidityConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.state.market_registry import MarketRegistry

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class AnalysisResult:
    token_id: str
    buy_price: float
    sell_price: float
    case: str


class LiquidityAnalyser:
    """Determines optimal buy price using the three-case orderbook algorithm."""

    def __init__(self, liquidity_config: LiquidityConfig, btts_config: BttsConfig) -> None:
        self._liquidity = liquidity_config
        self._btts = btts_config

    def analyse(
        self,
        orderbook: OrderBookSummary,
        token_id: str,
        market_name: str,
    ) -> AnalysisResult | None:
        """Analyse orderbook and return AnalysisResult or None if market should be skipped."""
        bids = orderbook.bids

        # Edge case: no bids or None
        if bids is None or len(bids) < 3:
            bid_count = 0 if bids is None else len(bids)
            logger.warning(
                "%s [%s]: skipping — fewer than 3 bid levels (got %d)",
                market_name,
                token_id,
                bid_count,
            )
            return None

        # Convert string prices/sizes to float
        try:
            l1_price = float(bids[0].price)  # noqa: F841 — L1 not used in price calc but kept for clarity
            l2_price = float(bids[1].price)
            l3_price = float(bids[2].price)
            l1_size = float(bids[0].size)
            l2_size = float(bids[1].size)
            l3_size = float(bids[2].size)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "%s [%s]: skipping — could not parse bid prices/sizes: %s",
                market_name,
                token_id,
                exc,
            )
            return None

        total_depth = l1_size + l2_size + l3_size

        logger.debug(
            "%s [%s]: orderbook L1=(%s, %s) L2=(%s, %s) L3=(%s, %s) total_depth=%.2f",
            market_name,
            token_id,
            bids[0].price,
            bids[0].size,
            bids[1].price,
            bids[1].size,
            bids[2].price,
            bids[2].size,
            total_depth,
        )

        # Three-case algorithm
        if total_depth >= self._liquidity.deep_book_threshold:
            # Case B: deep book — buy at L2 (more aggressive)
            buy_price = l2_price
            case = "B"
            logger.info(
                "%s [%s]: Case B (deep book) — total_depth=%.2f buy_price=%.4f",
                market_name,
                token_id,
                total_depth,
                buy_price,
            )
        elif total_depth >= self._liquidity.standard_depth:
            # Case A: standard — buy at L3 (conservative)
            buy_price = l3_price
            case = "A"
            logger.info(
                "%s [%s]: Case A (standard) — total_depth=%.2f buy_price=%.4f",
                market_name,
                token_id,
                total_depth,
                buy_price,
            )
        elif total_depth >= self._liquidity.low_liquidity_total:
            # Case C: thin liquidity — buy at L3 minus tick_offset
            buy_price = l3_price - self._liquidity.tick_offset
            case = "C"
            if buy_price <= 0:
                logger.info(
                    "%s [%s]: skipping — Case C buy_price would be <= 0 (%.4f - %.4f = %.4f)",
                    market_name,
                    token_id,
                    l3_price,
                    self._liquidity.tick_offset,
                    buy_price,
                )
                return None
            logger.info(
                "%s [%s]: Case C (thin liquidity) — total_depth=%.2f buy_price=%.4f",
                market_name,
                token_id,
                total_depth,
                buy_price,
            )
        else:
            # Insufficient liquidity — skip market
            logger.info(
                "%s [%s]: skipping — insufficient liquidity (total_depth=%.2f < low_liquidity_total=%d)",
                market_name,
                token_id,
                total_depth,
                self._liquidity.low_liquidity_total,
            )
            return None

        sell_price = min(buy_price + self._btts.price_diff, 0.99)

        return AnalysisResult(
            token_id=token_id, buy_price=buy_price, sell_price=sell_price, case=case
        )


class MarketAnalysisPipeline:
    """Orchestrates orderbook fetch → liquidity analysis → lifecycle state transition."""

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        liquidity_analyser: LiquidityAnalyser,
        market_registry: MarketRegistry,
    ) -> None:
        self._clob_client = clob_client
        self._analyser = liquidity_analyser
        self._market_registry = market_registry

    def analyse_market(self, token_id: str) -> AnalysisResult | None:
        """Fetch orderbook for a single token and run liquidity analysis.

        Returns AnalysisResult on success, None if market is skipped.
        """
        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
        )

        orderbook = self._clob_client.get_order_book(token_id)
        if orderbook is None:
            logger.error(
                "%s [%s]: orderbook fetch failed (retry exhausted) — skipping",
                market_name,
                token_id,
            )
            if entry is not None:
                entry.lifecycle.transition(GameState.SKIPPED)
            return None

        result = self._analyser.analyse(orderbook, token_id, market_name)

        if result is not None:
            logger.info(
                "%s [%s]: analysis complete — case=%s buy=%.4f sell=%.4f",
                market_name,
                token_id,
                result.case,
                result.buy_price,
                result.sell_price,
            )
            if entry is not None:
                entry.lifecycle.transition(GameState.ANALYSED)
        else:
            logger.info(
                "%s [%s]: market skipped after analysis",
                market_name,
                token_id,
            )
            if entry is not None:
                entry.lifecycle.transition(GameState.SKIPPED)

        return result

    def analyse_all_discovered(self) -> list[AnalysisResult]:
        """Analyse all markets currently in DISCOVERED state.

        Returns list of successful AnalysisResult objects (skipped markets are excluded).
        """
        results = []
        for entry in self._market_registry.all_markets():
            if entry.lifecycle.state != GameState.DISCOVERED:
                continue
            result = self.analyse_market(entry.token_id)
            if result is not None:
                results.append(result)
        return results
