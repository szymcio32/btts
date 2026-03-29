import io
import logging
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from btts_bot.config import LoggingConfig
from btts_bot.logging_setup import LOG_FORMAT, SecretFilter, setup_logging


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root_logger = logging.getLogger()
        self.original_handlers = self.root_logger.handlers.copy()
        self.original_level = self.root_logger.level

    def tearDown(self) -> None:
        current_handlers = self.root_logger.handlers.copy()
        self.root_logger.handlers.clear()
        for handler in current_handlers:
            if handler not in self.original_handlers:
                handler.close()
        self.root_logger.handlers.extend(self.original_handlers)
        self.root_logger.setLevel(self.original_level)

    def test_secret_filter_redacts_message_args_and_exception_text(self) -> None:
        secret = "test_secret_key_12345"
        record = logging.LogRecord(
            name="btts_bot.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="key is %s",
            args=(secret,),
            exc_info=None,
        )
        record.exc_text = f"traceback with {secret}"

        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": secret}, clear=False):
            secret_filter = SecretFilter()

        self.assertTrue(secret_filter.filter(record))
        self.assertEqual(record.msg, "key is [REDACTED]")
        self.assertIsNone(record.args)
        self.assertEqual(record.exc_text, "traceback with [REDACTED]")

    def test_setup_logging_configures_handlers_format_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "btts_bot.log"
            config = LoggingConfig(
                level="info",
                file_path=str(log_path),
                max_bytes=1024,
                backup_count=2,
            )
            stdout_buffer = io.StringIO()
            secret = "test_secret_key_12345"

            with (
                patch("sys.stdout", stdout_buffer),
                patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": secret}, clear=False),
            ):
                setup_logging(config)
                setup_logging(config)

                logger = logging.getLogger("btts_bot.test")
                logger.info("key is %s", secret)

                for handler in logging.getLogger().handlers:
                    handler.flush()

            root_logger = logging.getLogger()
            self.assertEqual(root_logger.level, logging.INFO)
            self.assertEqual(len(root_logger.handlers), 2)

            formatters = {handler.formatter._fmt for handler in root_logger.handlers}
            self.assertEqual(formatters, {LOG_FORMAT})
            self.assertTrue(
                all(
                    any(isinstance(f, SecretFilter) for f in handler.filters)
                    for handler in root_logger.handlers
                )
            )

            self.assertIn("[REDACTED]", stdout_buffer.getvalue())
            self.assertNotIn(secret, stdout_buffer.getvalue())

            file_contents = log_path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", file_contents)
            self.assertNotIn(secret, file_contents)

            if os.name != "nt":
                mode = stat.S_IMODE(log_path.stat().st_mode)
                self.assertEqual(mode, 0o600)
