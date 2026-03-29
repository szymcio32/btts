import argparse
import logging
from pathlib import Path

from btts_bot.config import load_config
from btts_bot.logging_setup import setup_logging

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
