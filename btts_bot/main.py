import argparse
import logging
import time
from pathlib import Path

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import load_config
from btts_bot.core.liquidity import LiquidityAnalyser, MarketAnalysisPipeline
from btts_bot.core.market_discovery import MarketDiscoveryService
from btts_bot.core.scheduling import SchedulerService
from btts_bot.logging_setup import setup_logging
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="BTTS Bot - Polymarket trading bot")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config_btts.yaml"),
        help="Path to YAML configuration file (default: config_btts.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.logging)
    logger.info("btts-bot starting... config loaded from %s", args.config)

    clob_client = ClobClientWrapper()
    logger.info("Authentication successful")

    market_registry = MarketRegistry()
    order_tracker = OrderTracker()
    logger.info("State managers initialized")

    gamma_client = GammaClient(config.data_file)
    discovery_service = MarketDiscoveryService(
        gamma_client, market_registry, config.leagues, order_tracker
    )

    liquidity_analyser = LiquidityAnalyser(config.liquidity, config.btts)
    analysis_pipeline = MarketAnalysisPipeline(clob_client, liquidity_analyser, market_registry)

    # Immediate startup discovery (FR5)
    discovered_count = discovery_service.discover_markets()
    logger.info("Startup discovery complete: %d markets", discovered_count)

    # Liquidity analysis for all discovered markets
    analysis_results = analysis_pipeline.analyse_all_discovered()
    analysed_count = len(analysis_results)
    skipped_count = discovered_count - analysed_count
    logger.info(
        "Liquidity analysis complete: %d analysed, %d skipped",
        analysed_count,
        skipped_count,
    )

    # Schedule daily fetch (FR6)
    scheduler_service = SchedulerService(
        daily_fetch_hour_utc=config.timing.daily_fetch_hour_utc,
        discovery_service=discovery_service,
    )
    scheduler_service.start()

    logger.info("btts-bot running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        scheduler_service.shutdown()
        logger.info("btts-bot stopped")
