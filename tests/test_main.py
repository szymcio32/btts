import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from btts_bot.config import BotConfig

from btts_bot import main as main_module


def make_config() -> BotConfig:
    return BotConfig.model_validate(
        {
            "leagues": [{"name": "Premier League", "abbreviation": "EPL"}],
            "btts": {"order_size": 30, "price_diff": 0.02},
            "liquidity": {
                "standard_depth": 1000,
                "deep_book_threshold": 2000,
                "low_liquidity_total": 500,
                "tick_offset": 0.01,
            },
            "timing": {"daily_fetch_hour_utc": 23},
            "logging": {"level": "INFO"},
        }
    )


class MainTests(unittest.TestCase):
    def test_main_uses_default_config_path_when_no_argument(self) -> None:
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()) as mock_load,
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
        ):
            with redirect_stdout(io.StringIO()):
                main_module.main()

        self.assertEqual(mock_load.call_args.args[0], Path("config_btts.yaml"))
        mock_setup_logging.assert_called_once()
        mock_logger.info.assert_called_once()

    def test_main_uses_config_argument_override(self) -> None:
        override_path = Path("custom-config.yaml")
        with (
            patch("sys.argv", ["btts_bot", "--config", str(override_path)]),
            patch.object(main_module, "load_config", return_value=make_config()) as mock_load,
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
        ):
            with redirect_stdout(io.StringIO()):
                main_module.main()

        self.assertEqual(mock_load.call_args.args[0], override_path)
        mock_setup_logging.assert_called_once()
        mock_logger.info.assert_called_once()

    def test_main_sets_up_logging_with_loaded_config(self) -> None:
        config = make_config()

        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=config),
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
        ):
            with redirect_stdout(io.StringIO()):
                main_module.main()

        mock_setup_logging.assert_called_once_with(config.logging)
        mock_logger.info.assert_called_once_with(
            "btts-bot starting... config loaded from %s", Path("config_btts.yaml")
        )

    def test_main_logs_loaded_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config_btts.yaml"
            config_path.write_text(
                """\
leagues:
  - name: Premier League
    abbreviation: EPL
btts:
  order_size: 30
  price_diff: 0.02
liquidity:
  standard_depth: 1000
  deep_book_threshold: 2000
  low_liquidity_total: 500
  tick_offset: 0.01
timing:
  daily_fetch_hour_utc: 23
logging:
  level: INFO
""",
                encoding="utf-8",
            )
            fake_logger = MagicMock()

            with (
                patch("sys.argv", ["btts_bot", "--config", str(config_path)]),
                patch.object(main_module, "logger", fake_logger),
            ):
                with redirect_stdout(io.StringIO()):
                    main_module.main()

            fake_logger.info.assert_called_once_with(
                "btts-bot starting... config loaded from %s", config_path
            )


if __name__ == "__main__":
    unittest.main()
