"""Structured logging setup for btts-bot."""

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

from btts_bot.config import LoggingConfig

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_SECRET_ENV_VARS = ("POLYMARKET_PRIVATE_KEY", "POLYMARKET_PROXY_ADDRESS")


class SecretFilter(logging.Filter):
    """Redact configured secrets from log output."""

    def __init__(self) -> None:
        super().__init__()
        self._patterns = [
            re.compile(re.escape(value))
            for env_var in _SECRET_ENV_VARS
            if (value := os.environ.get(env_var))
        ]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._patterns:
            return True

        record.msg = self._redact(record.getMessage())
        record.args = None

        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)

        return True

    def _redact(self, text: str) -> str:
        for pattern in self._patterns:
            text = pattern.sub("[REDACTED]", text)
        return text


def setup_logging(config: LoggingConfig) -> None:
    """Configure root logging with file and console handlers."""

    root_logger = logging.getLogger()
    for handler in root_logger.handlers.copy():
        root_logger.removeHandler(handler)
        handler.close()

    root_logger.setLevel(config.level)

    formatter = logging.Formatter(LOG_FORMAT)
    secret_filter = SecretFilter()

    file_handler = RotatingFileHandler(
        filename=config.file_path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stdout)

    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(secret_filter)
        root_logger.addHandler(handler)

    _set_log_file_permissions(config.file_path)


def _set_log_file_permissions(file_path: str) -> None:
    try:
        os.chmod(file_path, 0o600)
    except OSError:
        logging.getLogger(__name__).warning(
            "Unable to set restrictive permissions on log file %s", file_path
        )
        return

    try:
        current_mode = os.stat(file_path).st_mode & 0o777
    except OSError:
        return

    if current_mode != 0o600:
        logging.getLogger(__name__).warning(
            "Log file %s permissions are %o instead of 600", file_path, current_mode
        )
