import argparse
import logging
import time
from pathlib import Path

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import load_config
from btts_bot.core.fill_polling import FillPollingService
from btts_bot.core.game_start import GameStartService
from btts_bot.core.liquidity import LiquidityAnalyser, MarketAnalysisPipeline
from btts_bot.core.market_discovery import MarketDiscoveryService
from btts_bot.core.order_execution import OrderExecutionService
from btts_bot.core.pre_kickoff import PreKickoffService
from btts_bot.core.scheduling import SchedulerService
from btts_bot.logging_setup import setup_logging
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker

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

    # 1. State managers (no deps)
    market_registry = MarketRegistry()
    order_tracker = OrderTracker()
    position_tracker = PositionTracker()
    logger.info("State managers initialized")

    # 2. Clients
    gamma_client = GammaClient(config.data_file)

    # 3. Core services — discovery and pre-kickoff (no circular deps)
    discovery_service = MarketDiscoveryService(
        gamma_client, market_registry, config.leagues, order_tracker
    )
    pre_kickoff_service = PreKickoffService(
        clob_client, order_tracker, position_tracker, market_registry
    )
    game_start_service = GameStartService(
        clob_client, order_tracker, position_tracker, market_registry, config.timing
    )

    liquidity_analyser = LiquidityAnalyser(config.liquidity, config.btts)
    analysis_pipeline = MarketAnalysisPipeline(clob_client, liquidity_analyser, market_registry)

    # 4. Scheduler (depends on pre_kickoff_service, game_start_service, and discovery_service)
    scheduler_service = SchedulerService(
        daily_fetch_hour_utc=config.timing.daily_fetch_hour_utc,
        discovery_service=discovery_service,
        pre_kickoff_service=pre_kickoff_service,
        game_start_service=game_start_service,
        timing_config=config.timing,
    )

    # 5. Order execution (depends on scheduler_service for trigger registration)
    order_execution_service = OrderExecutionService(
        clob_client,
        order_tracker,
        position_tracker,
        market_registry,
        config.btts,
        scheduler_service,
    )

    # 6. Fill polling (depends on order_execution_service)
    fill_polling_service = FillPollingService(
        clob_client,
        order_tracker,
        position_tracker,
        market_registry,
        config.btts,
        order_execution_service,
    )

    # 7. Immediate startup discovery (FR5)
    discovered_count = discovery_service.discover_markets()
    logger.info("Startup discovery complete: %d markets", discovered_count)

    # 8. Liquidity analysis for all discovered markets
    analysis_results = analysis_pipeline.analyse_all_discovered()
    analysed_count = len(analysis_results)
    skipped_count = discovered_count - analysed_count
    logger.info(
        "Liquidity analysis complete: %d analysed, %d skipped",
        analysed_count,
        skipped_count,
    )

    # 9. Start scheduler BEFORE execute_all_analysed so pre-kickoff triggers
    #    can be added to a running scheduler (APScheduler also allows adding
    #    jobs before start — they queue safely either way)
    scheduler_service.start()

    # 10. Buy order placement — registers pre-kickoff trigger per game (FR12)
    placed_count = order_execution_service.execute_all_analysed(analysis_results)
    logger.info(
        "Buy orders placed: %d out of %d analysed markets",
        placed_count,
        analysed_count,
    )

    # Register fill polling interval job
    scheduler_service.scheduler.add_job(
        fill_polling_service.poll_all_active_orders,
        "interval",
        seconds=config.timing.fill_poll_interval_seconds,
        id="fill_polling",
        name="Fill polling",
        replace_existing=True,
    )
    logger.info(
        "Fill polling started: every %d seconds",
        config.timing.fill_poll_interval_seconds,
    )

    logger.info("btts-bot running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        scheduler_service.shutdown()
        logger.info("btts-bot stopped")
