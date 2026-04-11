"""Tests for MarketLoggerAdapter and factory functions in logging_setup."""

import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from btts_bot.config import LoggingConfig
from btts_bot.logging_setup import (
    MarketLoggerAdapter,
    _TokenOnlyLoggerAdapter,
    create_market_logger,
    create_token_logger,
    setup_logging,
)


class TestMarketLoggerAdapterProcess(unittest.TestCase):
    """Unit tests for MarketLoggerAdapter.process() message transformation."""

    def _make_adapter(
        self,
        home: str = "Arsenal",
        away: str = "Chelsea",
        token: str = "0xabc123",
        module: str = "btts_bot.core.order_execution",
    ) -> MarketLoggerAdapter:
        base_logger = logging.getLogger(module)
        return MarketLoggerAdapter(base_logger, home, away, token)

    def test_process_prepends_bracket_prefix_and_appends_token_suffix(self) -> None:
        adapter = self._make_adapter()
        msg, _ = adapter.process("Buy order placed: price=0.4800", {})
        self.assertEqual(
            msg,
            "[Arsenal vs Chelsea] Buy order placed: price=0.4800 (token=0xabc123)",
        )

    def test_process_uses_correct_home_and_away_teams(self) -> None:
        adapter = self._make_adapter(home="Liverpool", away="ManCity", token="0xdef456")
        msg, _ = adapter.process("Sell order sent", {})
        self.assertEqual(msg, "[Liverpool vs ManCity] Sell order sent (token=0xdef456)")

    def test_process_passes_kwargs_through_unchanged(self) -> None:
        adapter = self._make_adapter()
        sentinel_kwargs: dict = {"stack_info": True, "extra": {"foo": "bar"}}
        _, returned_kwargs = adapter.process("msg", sentinel_kwargs)
        self.assertIs(returned_kwargs, sentinel_kwargs)

    def test_process_with_empty_message(self) -> None:
        adapter = self._make_adapter(home="A", away="B", token="tok1")
        msg, _ = adapter.process("", {})
        self.assertEqual(msg, "[A vs B]  (token=tok1)")

    def test_extra_contains_market_name_and_token_id(self) -> None:
        adapter = self._make_adapter(home="Arsenal", away="Chelsea", token="0xabc123")
        self.assertEqual(adapter.extra["market_name"], "[Arsenal vs Chelsea]")
        self.assertEqual(adapter.extra["token_id"], "0xabc123")


class TestMarketLoggerAdapterAllLevels(unittest.TestCase):
    """Verify that the adapter's process() is applied at every log level."""

    def setUp(self) -> None:
        self._stream = io.StringIO()
        handler = logging.StreamHandler(self._stream)
        handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
        handler.setLevel(logging.DEBUG)

        self._base_logger = logging.getLogger("test_market_logger.levels")
        self._base_logger.setLevel(logging.DEBUG)
        self._base_logger.propagate = False
        self._base_logger.addHandler(handler)
        self._handler = handler

        self._adapter = MarketLoggerAdapter(self._base_logger, "Arsenal", "Chelsea", "0xabc")

    def tearDown(self) -> None:
        self._base_logger.removeHandler(self._handler)
        self._handler.close()
        self._base_logger.propagate = True

    def _last_line(self) -> str:
        lines = [line for line in self._stream.getvalue().splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def test_debug_level_message_is_transformed(self) -> None:
        self._adapter.debug("debug msg")
        self.assertIn("[Arsenal vs Chelsea] debug msg (token=0xabc)", self._last_line())

    def test_info_level_message_is_transformed(self) -> None:
        self._adapter.info("info msg")
        self.assertIn("[Arsenal vs Chelsea] info msg (token=0xabc)", self._last_line())

    def test_warning_level_message_is_transformed(self) -> None:
        self._adapter.warning("warn msg")
        self.assertIn("[Arsenal vs Chelsea] warn msg (token=0xabc)", self._last_line())

    def test_error_level_message_is_transformed(self) -> None:
        self._adapter.error("error msg")
        self.assertIn("[Arsenal vs Chelsea] error msg (token=0xabc)", self._last_line())

    def test_critical_level_message_is_transformed(self) -> None:
        self._adapter.critical("critical msg")
        self.assertIn("[Arsenal vs Chelsea] critical msg (token=0xabc)", self._last_line())


class TestMarketLoggerAdapterLoggerName(unittest.TestCase):
    """Logger name (%(name)s) must reflect the originating module, not the adapter."""

    def test_logger_name_is_preserved_from_underlying_logger(self) -> None:
        module = "btts_bot.core.fill_polling"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))

        base_logger = logging.getLogger(module)
        base_logger.setLevel(logging.DEBUG)
        base_logger.propagate = False
        base_logger.addHandler(handler)

        try:
            adapter = MarketLoggerAdapter(base_logger, "Home", "Away", "tok99")
            adapter.info("some message")
            output = stream.getvalue()
            self.assertIn(module, output)
            self.assertIn("[Home vs Away] some message (token=tok99)", output)
        finally:
            base_logger.removeHandler(handler)
            handler.close()
            base_logger.propagate = True


class TestCreateMarketLoggerFactory(unittest.TestCase):
    """Tests for the create_market_logger() factory function."""

    def test_returns_market_logger_adapter_instance(self) -> None:
        adapter = create_market_logger(
            "btts_bot.core.order_execution", "Arsenal", "Chelsea", "0xabc"
        )
        self.assertIsInstance(adapter, MarketLoggerAdapter)

    def test_factory_sets_correct_extra_values(self) -> None:
        adapter = create_market_logger("some.module", "Liverpool", "ManCity", "0xdef")
        self.assertEqual(adapter.extra["market_name"], "[Liverpool vs ManCity]")
        self.assertEqual(adapter.extra["token_id"], "0xdef")

    def test_factory_uses_provided_module_name_as_logger_name(self) -> None:
        module = "btts_bot.core.liquidity"
        adapter = create_market_logger(module, "Home", "Away", "tok1")
        self.assertEqual(adapter.logger.name, module)

    def test_factory_process_output_format(self) -> None:
        adapter = create_market_logger("mod", "Spurs", "West Ham", "0x999")
        msg, _ = adapter.process("Price updated", {})
        self.assertEqual(msg, "[Spurs vs West Ham] Price updated (token=0x999)")


class TestCreateTokenLoggerFactory(unittest.TestCase):
    """Tests for the create_token_logger() factory (token-only fallback)."""

    def test_returns_token_only_logger_adapter_instance(self) -> None:
        adapter = create_token_logger("btts_bot.core.reconciliation", "0xfff")
        self.assertIsInstance(adapter, _TokenOnlyLoggerAdapter)

    def test_token_only_adapter_uses_token_as_prefix(self) -> None:
        adapter = create_token_logger("btts_bot.core.reconciliation", "0xfff")
        # Access process() via the underlying _TokenOnlyLoggerAdapter
        msg, _ = adapter.process("Orphaned position detected", {})
        self.assertEqual(msg, "[0xfff] Orphaned position detected")

    def test_token_only_adapter_has_no_token_suffix(self) -> None:
        adapter = create_token_logger("some.module", "0xaaa")
        msg, _ = adapter.process("some log", {})
        self.assertNotIn("(token=", msg)

    def test_token_only_factory_uses_provided_module_name(self) -> None:
        module = "btts_bot.core.reconciliation"
        adapter = create_token_logger(module, "0xbbb")
        self.assertEqual(adapter.logger.name, module)


class TestMarketLoggerAdapterWithSecretFilter(unittest.TestCase):
    """Verify that SecretFilter still redacts secrets in adapter-transformed messages."""

    def test_secret_in_message_body_is_redacted(self) -> None:
        secret = "super_secret_key_9999"
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "test.log"
            config = LoggingConfig(
                level="debug",
                file_path=str(log_path),
                max_bytes=1024 * 1024,
                backup_count=1,
            )
            stdout_buffer = io.StringIO()

            with (
                patch("sys.stdout", stdout_buffer),
                patch.dict(
                    os.environ,
                    {"POLYMARKET_PRIVATE_KEY": secret},
                    clear=False,
                ),
            ):
                setup_logging(config)
                adapter = create_market_logger(
                    "btts_bot.core.order_execution", "Arsenal", "Chelsea", "0xabc"
                )
                adapter.info("key=%s placed", secret)

                for handler in logging.getLogger().handlers:
                    handler.flush()

            output = stdout_buffer.getvalue()
            self.assertNotIn(secret, output)
            self.assertIn("[REDACTED]", output)
            # Market context prefix and token suffix should still be present
            self.assertIn("[Arsenal vs Chelsea]", output)
            self.assertIn("(token=0xabc)", output)

    def test_secret_in_token_id_position_is_redacted(self) -> None:
        """If token_id itself were a secret value it should be redacted."""
        secret = "another_secret_8888"
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "test2.log"
            config = LoggingConfig(
                level="debug",
                file_path=str(log_path),
                max_bytes=1024 * 1024,
                backup_count=1,
            )
            stdout_buffer = io.StringIO()

            with (
                patch("sys.stdout", stdout_buffer),
                patch.dict(
                    os.environ,
                    {"POLYMARKET_PRIVATE_KEY": secret},
                    clear=False,
                ),
            ):
                setup_logging(config)
                # Token itself contains the secret value
                adapter = create_market_logger(
                    "btts_bot.core.order_execution", "Home", "Away", secret
                )
                adapter.info("order placed")

                for handler in logging.getLogger().handlers:
                    handler.flush()

            output = stdout_buffer.getvalue()
            self.assertNotIn(secret, output)
            self.assertIn("[REDACTED]", output)

    def tearDown(self) -> None:
        # Remove handlers added by setup_logging to avoid polluting other tests
        root_logger = logging.getLogger()
        for handler in root_logger.handlers.copy():
            root_logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    unittest.main()
