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
            "data_file": "games-data.json",
        }
    )


class MainTests(unittest.TestCase):
    def test_main_uses_default_config_path_when_no_argument(self) -> None:
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()) as mock_load,
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            with redirect_stdout(io.StringIO()):
                main_module.main()

        self.assertEqual(mock_load.call_args.args[0], Path("config_btts.yaml"))
        mock_setup_logging.assert_called_once()
        mock_logger.info.assert_called()

    def test_main_uses_config_argument_override(self) -> None:
        override_path = Path("custom-config.yaml")
        with (
            patch("sys.argv", ["btts_bot", "--config", str(override_path)]),
            patch.object(main_module, "load_config", return_value=make_config()) as mock_load,
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            with redirect_stdout(io.StringIO()):
                main_module.main()

        self.assertEqual(mock_load.call_args.args[0], override_path)
        mock_setup_logging.assert_called_once()
        mock_logger.info.assert_called()

    def test_main_sets_up_logging_with_loaded_config(self) -> None:
        config = make_config()

        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=config),
            patch.object(main_module, "setup_logging") as mock_setup_logging,
            patch.object(main_module, "logger") as mock_logger,
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            with redirect_stdout(io.StringIO()):
                main_module.main()

        mock_setup_logging.assert_called_once_with(config.logging)
        mock_logger.info.assert_any_call(
            "btts-bot starting... config loaded from %s", Path("config_btts.yaml")
        )

    def test_main_logs_loaded_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config_btts.yaml"
            config_path.write_text(
                """\
data_file: "games-data.json"
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
                patch.object(main_module, "ClobClientWrapper"),
                patch.object(main_module, "GammaClient"),
                patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
            ):
                mock_discovery_cls.return_value.discover_markets.return_value = 0
                with redirect_stdout(io.StringIO()):
                    main_module.main()

            fake_logger.info.assert_any_call(
                "btts-bot starting... config loaded from %s", config_path
            )

    def test_main_instantiates_clob_client_wrapper(self) -> None:
        """ClobClientWrapper is instantiated after setup_logging (AC #2 integration)."""
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "logger"),
            patch.object(main_module, "ClobClientWrapper") as mock_wrapper_cls,
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            main_module.main()

        mock_wrapper_cls.assert_called_once()

    def test_main_logs_authentication_successful(self) -> None:
        """main() logs 'Authentication successful' after ClobClientWrapper init."""
        mock_logger = MagicMock()
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "logger", mock_logger),
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            main_module.main()

        mock_logger.info.assert_any_call("Authentication successful")

    def test_main_instantiates_gamma_client_with_data_file(self) -> None:
        """GammaClient is instantiated with config.data_file."""
        config = make_config()
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=config),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "logger"),
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient") as mock_gamma_cls,
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 0
            main_module.main()

        mock_gamma_cls.assert_called_once_with(config.data_file)

    def test_main_calls_discover_markets_on_startup(self) -> None:
        """discover_markets() is called on startup."""
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "logger"),
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_instance = mock_discovery_cls.return_value
            mock_discovery_instance.discover_markets.return_value = 3
            main_module.main()

        mock_discovery_instance.discover_markets.assert_called_once()

    def test_main_logs_startup_discovery_complete(self) -> None:
        """main() logs 'Startup discovery complete' with market count."""
        mock_logger = MagicMock()
        with (
            patch("sys.argv", ["btts_bot"]),
            patch.object(main_module, "load_config", return_value=make_config()),
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "logger", mock_logger),
            patch.object(main_module, "ClobClientWrapper"),
            patch.object(main_module, "GammaClient"),
            patch.object(main_module, "MarketDiscoveryService") as mock_discovery_cls,
        ):
            mock_discovery_cls.return_value.discover_markets.return_value = 5
            main_module.main()

        mock_logger.info.assert_any_call("Startup discovery complete: %d markets", 5)


if __name__ == "__main__":
    unittest.main()
