import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from btts_bot.config import BotConfig

from btts_bot import main as main_module
from btts_bot.core.liquidity import AnalysisResult


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
    mock_liquidity_analyser_cls = extra_patches.pop("LiquidityAnalyser", MagicMock())
    mock_analysis_pipeline_cls = extra_patches.pop("MarketAnalysisPipeline", MagicMock())
    mock_order_execution_cls = extra_patches.pop("OrderExecutionService", MagicMock())
    mock_position_tracker_cls = extra_patches.pop("PositionTracker", MagicMock())
    mock_fill_polling_cls = extra_patches.pop("FillPollingService", MagicMock())
    mock_pre_kickoff_cls = extra_patches.pop("PreKickoffService", MagicMock())
    mock_game_start_cls = extra_patches.pop("GameStartService", MagicMock())

    mock_discovery_cls.return_value.discover_markets.return_value = extra_patches.pop(
        "discover_count", 0
    )
    mock_analysis_pipeline_cls.return_value.analyse_all_discovered.return_value = extra_patches.pop(
        "analysis_results", []
    )
    mock_order_execution_cls.return_value.execute_all_analysed.return_value = extra_patches.pop(
        "placed_count", 0
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
        patch.object(main_module, "LiquidityAnalyser", mock_liquidity_analyser_cls),
        patch.object(main_module, "MarketAnalysisPipeline", mock_analysis_pipeline_cls),
        patch.object(main_module, "OrderExecutionService", mock_order_execution_cls),
        patch.object(main_module, "PositionTracker", mock_position_tracker_cls),
        patch.object(main_module, "FillPollingService", mock_fill_polling_cls),
        patch.object(main_module, "PreKickoffService", mock_pre_kickoff_cls),
        patch.object(main_module, "GameStartService", mock_game_start_cls),
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
    mocks["LiquidityAnalyser"] = mock_liquidity_analyser_cls
    mocks["MarketAnalysisPipeline"] = mock_analysis_pipeline_cls
    mocks["OrderExecutionService"] = mock_order_execution_cls
    mocks["PositionTracker"] = mock_position_tracker_cls
    mocks["FillPollingService"] = mock_fill_polling_cls
    mocks["PreKickoffService"] = mock_pre_kickoff_cls
    mocks["GameStartService"] = mock_game_start_cls
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
            mock_analysis_pipeline_cls = MagicMock()
            mock_analysis_pipeline_cls.return_value.analyse_all_discovered.return_value = []
            mock_order_execution_cls = MagicMock()
            mock_order_execution_cls.return_value.execute_all_analysed.return_value = 0

            with (
                patch("sys.argv", ["btts_bot", "--config", str(config_path)]),
                patch.object(main_module, "logger", fake_logger),
                patch.object(main_module, "ClobClientWrapper"),
                patch.object(main_module, "GammaClient"),
                patch.object(main_module, "MarketDiscoveryService", mock_discovery_cls),
                patch.object(main_module, "SchedulerService", mock_scheduler_cls),
                patch.object(main_module, "OrderTracker"),
                patch.object(main_module, "PositionTracker"),
                patch.object(main_module, "LiquidityAnalyser"),
                patch.object(main_module, "MarketAnalysisPipeline", mock_analysis_pipeline_cls),
                patch.object(main_module, "OrderExecutionService", mock_order_execution_cls),
                patch.object(main_module, "FillPollingService"),
                patch.object(main_module, "PreKickoffService"),
                patch.object(main_module, "GameStartService"),
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

    # --- New tests for Story 2.4: Liquidity analysis wiring ---

    def test_main_stores_clob_client_in_variable(self) -> None:
        """ClobClientWrapper instance is stored and passed to MarketAnalysisPipeline."""
        mocks = _run_main_with_patches()
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_pipeline_cls = mocks["MarketAnalysisPipeline"]
        call_args = mock_pipeline_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)

    def test_main_instantiates_liquidity_analyser_with_config(self) -> None:
        """LiquidityAnalyser is instantiated with config.liquidity and config.btts."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mock_analyser_cls = mocks["LiquidityAnalyser"]
        mock_analyser_cls.assert_called_once_with(config.liquidity, config.btts)

    def test_main_instantiates_analysis_pipeline_with_dependencies(self) -> None:
        """MarketAnalysisPipeline is instantiated with clob_client, analyser, registry."""
        mocks = _run_main_with_patches()
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_analyser_instance = mocks["LiquidityAnalyser"].return_value
        mock_pipeline_cls = mocks["MarketAnalysisPipeline"]
        call_args = mock_pipeline_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)
        self.assertIs(call_args.args[1], mock_analyser_instance)

    def test_main_calls_analyse_all_discovered_after_discovery(self) -> None:
        """analyse_all_discovered() is called after discover_markets()."""
        mocks = _run_main_with_patches(discover_count=3)
        mock_pipeline_instance = mocks["MarketAnalysisPipeline"].return_value
        mock_pipeline_instance.analyse_all_discovered.assert_called_once()

    def test_main_logs_analysis_complete_summary(self) -> None:
        """main() logs liquidity analysis summary with analysed and skipped counts."""
        results = [
            AnalysisResult(token_id="t-1", buy_price=0.48, sell_price=0.50, case="A"),
            AnalysisResult(token_id="t-2", buy_price=0.49, sell_price=0.51, case="B"),
        ]
        mocks = _run_main_with_patches(discover_count=3, analysis_results=results)
        mocks["logger"].info.assert_any_call(
            "Liquidity analysis complete: %d analysed, %d skipped",
            2,
            1,
        )

    # --- New tests for Story 3.1: OrderExecutionService wiring ---

    def test_main_instantiates_order_execution_service(self) -> None:
        """OrderExecutionService is instantiated in main() after analysis pipeline."""
        mocks = _run_main_with_patches()
        mocks["OrderExecutionService"].assert_called_once()

    def test_main_instantiates_order_execution_service_with_correct_deps(self) -> None:
        """OrderExecutionService is instantiated with clob_client, order_tracker, position_tracker, registry, config.btts."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_tracker_instance = mocks["OrderTracker"].return_value
        mock_pos_tracker_instance = mocks["PositionTracker"].return_value
        mock_exec_cls = mocks["OrderExecutionService"]
        call_args = mock_exec_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)
        self.assertIs(call_args.args[1], mock_tracker_instance)
        self.assertIs(call_args.args[2], mock_pos_tracker_instance)

    def test_main_calls_execute_all_analysed_after_analysis(self) -> None:
        """execute_all_analysed() is called after analyse_all_discovered()."""
        analysis_results = [
            AnalysisResult(token_id="t-1", buy_price=0.48, sell_price=0.50, case="A"),
        ]
        mocks = _run_main_with_patches(analysis_results=analysis_results)
        mock_exec_instance = mocks["OrderExecutionService"].return_value
        mock_exec_instance.execute_all_analysed.assert_called_once_with(analysis_results)

    def test_main_passes_analysis_results_to_execute_all_analysed(self) -> None:
        """analysis_results from analyse_all_discovered() are passed to execute_all_analysed()."""
        results = [
            AnalysisResult(token_id="t-1", buy_price=0.48, sell_price=0.50, case="A"),
            AnalysisResult(token_id="t-2", buy_price=0.49, sell_price=0.51, case="B"),
        ]
        mocks = _run_main_with_patches(analysis_results=results)
        mock_exec_instance = mocks["OrderExecutionService"].return_value
        call_args = mock_exec_instance.execute_all_analysed.call_args
        self.assertIs(call_args.args[0], results)

    def test_main_logs_buy_orders_placed_summary(self) -> None:
        """main() logs buy orders placed summary after execute_all_analysed()."""
        results = [
            AnalysisResult(token_id="t-1", buy_price=0.48, sell_price=0.50, case="A"),
            AnalysisResult(token_id="t-2", buy_price=0.49, sell_price=0.51, case="B"),
        ]
        mocks = _run_main_with_patches(analysis_results=results, placed_count=2)
        mocks["logger"].info.assert_any_call(
            "Buy orders placed: %d out of %d analysed markets",
            2,
            2,
        )

    # --- New tests for Story 3.2: PositionTracker and FillPollingService wiring ---

    def test_main_instantiates_position_tracker(self) -> None:
        """PositionTracker is instantiated in main() alongside other state managers."""
        mocks = _run_main_with_patches()
        mocks["PositionTracker"].assert_called_once_with()

    def test_main_instantiates_fill_polling_service(self) -> None:
        """FillPollingService is instantiated in main() after order execution service."""
        mocks = _run_main_with_patches()
        mocks["FillPollingService"].assert_called_once()

    def test_main_fill_polling_service_receives_correct_deps(self) -> None:
        """FillPollingService is instantiated with clob_client, order_tracker, position_tracker, registry, config.btts."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_tracker_instance = mocks["OrderTracker"].return_value
        mock_pos_tracker_instance = mocks["PositionTracker"].return_value
        mock_fill_cls = mocks["FillPollingService"]
        call_args = mock_fill_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)
        self.assertIs(call_args.args[1], mock_tracker_instance)
        self.assertIs(call_args.args[2], mock_pos_tracker_instance)

    def test_main_fill_polling_service_receives_order_execution_service(self) -> None:
        """FillPollingService is instantiated with order_execution_service as 6th positional arg."""
        mocks = _run_main_with_patches()
        mock_exec_instance = mocks["OrderExecutionService"].return_value
        mock_fill_cls = mocks["FillPollingService"]
        call_args = mock_fill_cls.call_args
        self.assertIs(call_args.args[5], mock_exec_instance)

    def test_main_registers_fill_polling_job_after_scheduler_start(self) -> None:
        """main() registers fill polling interval job after scheduler_service.start()."""
        mocks = _run_main_with_patches()
        mock_scheduler_instance = mocks["SchedulerService"].return_value
        mock_scheduler_instance.scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler_instance.scheduler.add_job.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("id") or call_kwargs.args[3]
            if len(call_kwargs.args) > 3
            else call_kwargs.kwargs.get("id"),
            "fill_polling",
        )

    def test_main_logs_fill_polling_started(self) -> None:
        """main() logs 'Fill polling started' after registering the job."""
        mocks = _run_main_with_patches()
        # Verify that a fill polling started message was logged
        info_calls = [str(call) for call in mocks["logger"].info.call_args_list]
        assert any("Fill polling started" in c for c in info_calls)

    # --- New tests for Story 4.1: PreKickoffService wiring ---

    def test_main_instantiates_pre_kickoff_service(self) -> None:
        """PreKickoffService is instantiated in main() before SchedulerService."""
        mocks = _run_main_with_patches()
        mocks["PreKickoffService"].assert_called_once()

    def test_main_pre_kickoff_service_receives_correct_deps(self) -> None:
        """PreKickoffService is constructed with clob_client, order_tracker, position_tracker, registry."""
        mocks = _run_main_with_patches()
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_tracker_instance = mocks["OrderTracker"].return_value
        mock_pos_tracker_instance = mocks["PositionTracker"].return_value
        mock_pre_kickoff_cls = mocks["PreKickoffService"]
        call_args = mock_pre_kickoff_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)
        self.assertIs(call_args.args[1], mock_tracker_instance)
        self.assertIs(call_args.args[2], mock_pos_tracker_instance)

    def test_main_scheduler_receives_pre_kickoff_service(self) -> None:
        """SchedulerService is constructed with pre_kickoff_service kwarg."""
        mocks = _run_main_with_patches()
        mock_pre_kickoff_instance = mocks["PreKickoffService"].return_value
        mock_scheduler_cls = mocks["SchedulerService"]
        call_kwargs = mock_scheduler_cls.call_args.kwargs
        self.assertIs(call_kwargs["pre_kickoff_service"], mock_pre_kickoff_instance)

    def test_main_scheduler_receives_timing_config(self) -> None:
        """SchedulerService is constructed with timing_config from BotConfig."""
        config = make_config()
        mocks = _run_main_with_patches(config=config)
        mock_scheduler_cls = mocks["SchedulerService"]
        call_kwargs = mock_scheduler_cls.call_args.kwargs
        self.assertIs(call_kwargs["timing_config"], config.timing)

    def test_main_order_execution_service_receives_scheduler_service(self) -> None:
        """OrderExecutionService receives scheduler_service as 6th positional arg."""
        mocks = _run_main_with_patches()
        mock_scheduler_instance = mocks["SchedulerService"].return_value
        mock_exec_cls = mocks["OrderExecutionService"]
        call_args = mock_exec_cls.call_args
        self.assertIs(call_args.args[5], mock_scheduler_instance)

    # --- New tests for Story 4.2: GameStartService wiring ---

    def test_main_instantiates_game_start_service(self) -> None:
        """GameStartService is instantiated in main() before SchedulerService."""
        mocks = _run_main_with_patches()
        mocks["GameStartService"].assert_called_once()

    def test_main_game_start_service_receives_correct_deps(self) -> None:
        """GameStartService is constructed with clob_client, order_tracker, position_tracker, registry."""
        mocks = _run_main_with_patches()
        mock_clob_instance = mocks["ClobClientWrapper"].return_value
        mock_tracker_instance = mocks["OrderTracker"].return_value
        mock_pos_tracker_instance = mocks["PositionTracker"].return_value
        mock_game_start_cls = mocks["GameStartService"]
        call_args = mock_game_start_cls.call_args
        self.assertIs(call_args.args[0], mock_clob_instance)
        self.assertIs(call_args.args[1], mock_tracker_instance)
        self.assertIs(call_args.args[2], mock_pos_tracker_instance)

    def test_main_scheduler_receives_game_start_service(self) -> None:
        """SchedulerService is constructed with game_start_service kwarg."""
        mocks = _run_main_with_patches()
        mock_game_start_instance = mocks["GameStartService"].return_value
        mock_scheduler_cls = mocks["SchedulerService"]
        call_kwargs = mock_scheduler_cls.call_args.kwargs
        self.assertIs(call_kwargs["game_start_service"], mock_game_start_instance)


if __name__ == "__main__":
    unittest.main()
