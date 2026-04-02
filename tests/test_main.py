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


def _run_main_with_patches(**extra_patches: MagicMock) -> dict[str, MagicMock]:
    """Helper to run main() with all required mocks, returning them in a dict.

    The main loop (while True: time.sleep(1)) is broken by making
    time.sleep raise KeyboardInterrupt on the first call.
    """
    mocks: dict[str, MagicMock] = {}
    config = extra_patches.pop("config", make_config())

    mock_load = extra_patches.pop("load_config", MagicMock(return_value=config))
    mock_setup_logging = extra_patches.pop("setup_logging", MagicMock())
    mock_logger = extra_patches.pop("logger", MagicMock())
    mock_clob = extra_patches.pop("ClobClientWrapper", MagicMock())
    mock_gamma = extra_patches.pop("GammaClient", MagicMock())
    mock_discovery_cls = extra_patches.pop("MarketDiscoveryService", MagicMock())
    mock_scheduler_cls = extra_patches.pop("SchedulerService", MagicMock())
    mock_order_tracker_cls = extra_patches.pop("OrderTracker", MagicMock())
    mock_time_sleep = extra_patches.pop("time_sleep", MagicMock(side_effect=KeyboardInterrupt))

    mock_discovery_cls.return_value.discover_markets.return_value = extra_patches.pop(
        "discover_count", 0
    )

    with (
        patch("sys.argv", extra_patches.pop("argv", ["btts_bot"])),
        patch.object(main_module, "load_config", mock_load),
        patch.object(main_module, "setup_logging", mock_setup_logging),
        patch.object(main_module, "logger", mock_logger),
        patch.object(main_module, "ClobClientWrapper", mock_clob),
        patch.object(main_module, "GammaClient", mock_gamma),
        patch.object(main_module, "MarketDiscoveryService", mock_discovery_cls),
        patch.object(main_module, "SchedulerService", mock_scheduler_cls),
        patch.object(main_module, "OrderTracker", mock_order_tracker_cls),
        patch.object(main_module.time, "sleep", mock_time_sleep),
    ):
        with redirect_stdout(io.StringIO()):
            main_module.main()

    mocks["load_config"] = mock_load
    mocks["setup_logging"] = mock_setup_logging
    mocks["logger"] = mock_logger
    mocks["ClobClientWrapper"] = mock_clob
    mocks["GammaClient"] = mock_gamma
    mocks["MarketDiscoveryService"] = mock_discovery_cls
    mocks["SchedulerService"] = mock_scheduler_cls
    mocks["OrderTracker"] = mock_order_tracker_cls
    mocks["time_sleep"] = mock_time_sleep
    mocks["config"] = config
    return mocks


class MainTests(unittest.TestCase):
    def test_main_uses_default_config_path_when_no_argument(self) -> None:
        mocks = _run_main_with_patches()
        self.assertEqual(mocks["load_config"].call_args.args[0], Path("config_btts.yaml"))
        mocks["setup_logging"].assert_called_once()
        mocks["logger"].info.assert_called()

    def test_main_uses_config_argument_override(self) -> None:
        override_path = Path("custom-config.yaml")
        mocks = _run_main_with_patches(argv=["btts_bot", "--config", str(override_path)])
        self.assertEqual(mocks["load_config"].call_args.args[0], override_path)
        mocks["setup_logging"].assert_called_once()
        mocks["logger"].info.assert_called()

    def test_main_sets_up_logging_with_loaded_config(self) -> None:
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mocks["setup_logging"].assert_called_once_with(config.logging)
        mocks["logger"].info.assert_any_call(
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
            mock_scheduler_cls = MagicMock()
            mock_discovery_cls = MagicMock()
            mock_discovery_cls.return_value.discover_markets.return_value = 0

            with (
                patch("sys.argv", ["btts_bot", "--config", str(config_path)]),
                patch.object(main_module, "logger", fake_logger),
                patch.object(main_module, "ClobClientWrapper"),
                patch.object(main_module, "GammaClient"),
                patch.object(main_module, "MarketDiscoveryService", mock_discovery_cls),
                patch.object(main_module, "SchedulerService", mock_scheduler_cls),
                patch.object(main_module, "OrderTracker"),
                patch.object(main_module.time, "sleep", side_effect=KeyboardInterrupt),
            ):
                with redirect_stdout(io.StringIO()):
                    main_module.main()

            fake_logger.info.assert_any_call(
                "btts-bot starting... config loaded from %s", config_path
            )

    def test_main_instantiates_clob_client_wrapper(self) -> None:
        """ClobClientWrapper is instantiated after setup_logging (AC #2 integration)."""
        mocks = _run_main_with_patches()
        mocks["ClobClientWrapper"].assert_called_once()

    def test_main_logs_authentication_successful(self) -> None:
        """main() logs 'Authentication successful' after ClobClientWrapper init."""
        mocks = _run_main_with_patches()
        mocks["logger"].info.assert_any_call("Authentication successful")

    def test_main_instantiates_gamma_client_with_data_file(self) -> None:
        """GammaClient is instantiated with config.data_file."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mocks["GammaClient"].assert_called_once_with(config.data_file)

    def test_main_calls_discover_markets_on_startup(self) -> None:
        """discover_markets() is called on startup."""
        mocks = _run_main_with_patches(discover_count=3)
        mock_discovery_instance = mocks["MarketDiscoveryService"].return_value
        mock_discovery_instance.discover_markets.assert_called_once()

    def test_main_logs_startup_discovery_complete(self) -> None:
        """main() logs 'Startup discovery complete' with market count."""
        mocks = _run_main_with_patches(discover_count=5)
        mocks["logger"].info.assert_any_call("Startup discovery complete: %d markets", 5)

    # --- New tests for Story 2.2: Scheduler wiring ---

    def test_main_instantiates_scheduler_with_config_hour(self) -> None:
        """SchedulerService is instantiated with daily_fetch_hour_utc from config."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mock_scheduler_cls = mocks["SchedulerService"]
        mock_scheduler_cls.assert_called_once()
        call_kwargs = mock_scheduler_cls.call_args.kwargs
        self.assertEqual(call_kwargs["daily_fetch_hour_utc"], 23)

    def test_main_calls_scheduler_start(self) -> None:
        """main() calls scheduler_service.start() after instantiation."""
        mocks = _run_main_with_patches()
        mock_scheduler_instance = mocks["SchedulerService"].return_value
        mock_scheduler_instance.start.assert_called_once()

    def test_main_calls_scheduler_shutdown_on_keyboard_interrupt(self) -> None:
        """main() calls scheduler_service.shutdown() when KeyboardInterrupt is raised."""
        mocks = _run_main_with_patches()
        mock_scheduler_instance = mocks["SchedulerService"].return_value
        mock_scheduler_instance.shutdown.assert_called_once()

    def test_main_logs_running_message(self) -> None:
        """main() logs 'btts-bot running' message before entering main loop."""
        mocks = _run_main_with_patches()
        mocks["logger"].info.assert_any_call("btts-bot running. Press Ctrl+C to exit.")

    def test_main_logs_shutdown_requested(self) -> None:
        """main() logs 'Shutdown requested' on KeyboardInterrupt."""
        mocks = _run_main_with_patches()
        mocks["logger"].info.assert_any_call("Shutdown requested")

    def test_main_logs_stopped(self) -> None:
        """main() logs 'btts-bot stopped' after shutdown."""
        mocks = _run_main_with_patches()
        mocks["logger"].info.assert_any_call("btts-bot stopped")

    # --- New tests for Story 2.3: OrderTracker wiring ---

    def test_main_instantiates_order_tracker(self) -> None:
        """OrderTracker is instantiated in main() alongside MarketRegistry."""
        mocks = _run_main_with_patches()
        mocks["OrderTracker"].assert_called_once_with()

    def test_main_passes_order_tracker_to_discovery_service(self) -> None:
        """MarketDiscoveryService is constructed with the OrderTracker instance."""
        mocks = _run_main_with_patches()
        mock_order_tracker_instance = mocks["OrderTracker"].return_value
        mock_discovery_cls = mocks["MarketDiscoveryService"]
        # Verify the order_tracker instance was passed as 4th positional arg
        call_args = mock_discovery_cls.call_args
        self.assertIs(call_args.args[3], mock_order_tracker_instance)


if __name__ == "__main__":
    unittest.main()
