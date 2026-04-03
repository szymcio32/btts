import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from btts_bot.config import BotConfig, load_config


VALID_CONFIG = """\
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
"""


class ConfigModelTests(unittest.TestCase):
    def test_valid_config_creates_typed_models(self) -> None:
        config = BotConfig.model_validate(
            {
                "leagues": [{"name": "Premier League", "abbreviation": "EPL"}],
                "btts": {
                    "order_size": 30,
                    "price_diff": 0.02,
                    "min_order_size": 5,
                    "expiration_hour_offset": 1,
                },
                "liquidity": {
                    "standard_depth": 1000,
                    "deep_book_threshold": 2000,
                    "low_liquidity_total": 500,
                    "tick_offset": 0.01,
                },
                "timing": {
                    "daily_fetch_hour_utc": 23,
                    "fill_poll_interval_seconds": 30,
                    "pre_kickoff_minutes": 10,
                },
                "logging": {
                    "level": "INFO",
                    "file_path": "btts_bot.log",
                    "max_bytes": 10485760,
                    "backup_count": 5,
                },
                "data_file": "games-data.json",
            }
        )

        self.assertEqual(config.leagues[0].name, "Premier League")
        self.assertEqual(config.timing.daily_fetch_hour_utc, 23)
        self.assertEqual(config.logging.level, "INFO")

    def test_daily_fetch_hour_must_be_between_0_and_23(self) -> None:
        with self.assertRaises(Exception):
            BotConfig.model_validate(
                {
                    "leagues": [{"name": "Premier League", "abbreviation": "EPL"}],
                    "btts": {"order_size": 30, "price_diff": 0.02},
                    "liquidity": {
                        "standard_depth": 1000,
                        "deep_book_threshold": 2000,
                        "low_liquidity_total": 500,
                        "tick_offset": 0.01,
                    },
                    "timing": {"daily_fetch_hour_utc": 24},
                    "logging": {"level": "INFO"},
                    "data_file": "games-data.json",
                }
            )

    def test_invalid_log_level_raises_validation_error(self) -> None:
        with self.assertRaises(Exception):
            BotConfig.model_validate(
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
                    "logging": {"level": "VERBOSE"},
                    "data_file": "games-data.json",
                }
            )


class LoadConfigTests(unittest.TestCase):
    def test_load_config_returns_bot_config_for_valid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config_btts.yaml"
            config_path.write_text(VALID_CONFIG, encoding="utf-8")

            config = load_config(config_path)

            self.assertEqual(config.btts.order_size, 30)
            self.assertEqual(config.timing.fill_poll_interval_seconds, 30)

    def test_load_config_exits_when_file_not_found(self) -> None:
        missing = Path("definitely-missing-config.yaml")
        stderr_buffer = io.StringIO()

        with self.assertRaises(SystemExit) as context:
            with redirect_stderr(stderr_buffer):
                load_config(missing)

        self.assertEqual(context.exception.code, 1)
        self.assertIn("Config file not found", stderr_buffer.getvalue())

    def test_load_config_exits_on_yaml_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config_btts.yaml"
            config_path.write_text("leagues: [", encoding="utf-8")
            stderr_buffer = io.StringIO()

            with self.assertRaises(SystemExit) as context:
                with redirect_stderr(stderr_buffer):
                    load_config(config_path)

            self.assertEqual(context.exception.code, 1)
            self.assertIn("Invalid YAML", stderr_buffer.getvalue())

    def test_load_config_exits_on_validation_error(self) -> None:
        invalid_config = VALID_CONFIG.replace("order_size: 30", "order_size: zero")

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config_btts.yaml"
            config_path.write_text(invalid_config, encoding="utf-8")
            stderr_buffer = io.StringIO()

            with self.assertRaises(SystemExit) as context:
                with redirect_stderr(stderr_buffer):
                    load_config(config_path)

            self.assertEqual(context.exception.code, 1)
            self.assertIn("Invalid configuration", stderr_buffer.getvalue())
            self.assertIn("btts.order_size", stderr_buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
