import argparse
import logging
from pathlib import Path

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import load_config
from btts_bot.core.market_discovery import MarketDiscoveryService
from btts_bot.logging_setup import setup_logging
from btts_bot.state.market_registry import MarketRegistry

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

    ClobClientWrapper()
    logger.info("Authentication successful")

    market_registry = MarketRegistry()
    logger.info("State managers initialized")

    gamma_client = GammaClient(config.data_file)
    discovery_service = MarketDiscoveryService(gamma_client, market_registry, config.leagues)

    # Immediate startup discovery (FR5)
    discovered_count = discovery_service.discover_markets()
    logger.info("Startup discovery complete: %d markets", discovered_count)
