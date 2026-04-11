"""Structured logging setup for btts-bot."""

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

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


class MarketLoggerAdapter(logging.LoggerAdapter):
    """LoggerAdapter that automatically prepends market context to every log message.

    Wraps a module logger and injects ``[Home vs Away]`` prefix and
    ``(token=<token_id>)`` suffix into every message via ``process()``.

    Usage::

        mlog = create_market_logger(__name__, "Arsenal", "Chelsea", "0xabc")
        mlog.info("Buy order placed: price=%.4f", 0.48)
        # → [Arsenal vs Chelsea] Buy order placed: price=0.4800 (token=0xabc)
    """

    def __init__(
        self,
        logger: logging.Logger,
        home_team: str,
        away_team: str,
        token_id: str,
    ) -> None:
        extra = {
            "market_name": f"[{home_team} vs {away_team}]",
            "token_id": token_id,
        }
        super().__init__(logger, extra)

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Prepend market name and append token suffix to every log message."""
        market_name = self.extra["market_name"]
        token_id = self.extra["token_id"]
        return f"{market_name} {msg} (token={token_id})", kwargs


def create_market_logger(
    module_name: str,
    home_team: str,
    away_team: str,
    token_id: str,
) -> MarketLoggerAdapter:
    """Factory: create a MarketLoggerAdapter for a given module and market.

    Args:
        module_name: Typically ``__name__`` of the calling module.
        home_team: Home team display name (e.g. ``"Arsenal"``).
        away_team: Away team display name (e.g. ``"Chelsea"``).
        token_id: The canonical BTTS-No token identifier.

    Returns:
        A ``MarketLoggerAdapter`` that prepends ``[home_team vs away_team]`` and
        appends ``(token=token_id)`` to every log message.
    """
    base_logger = logging.getLogger(module_name)
    return MarketLoggerAdapter(base_logger, home_team, away_team, token_id)


def create_token_logger(module_name: str, token_id: str) -> logging.LoggerAdapter:
    """Factory: create a token-only adapter for contexts where team names are unavailable.

    Output format: ``[<token_id>] <message>`` (no ``(token=...)`` suffix to avoid
    redundancy when only the token ID is available).

    Uses an internal token-only adapter that omits the ``(token=...)`` suffix
    since the token is already present in the prefix.

    Args:
        module_name: Typically ``__name__`` of the calling module.
        token_id: The canonical token identifier used as prefix.

    Returns:
        A ``logging.LoggerAdapter`` whose messages are prefixed with
        ``[<token_id>]`` and have no ``(token=...)`` suffix.
    """
    base_logger = logging.getLogger(module_name)
    return _TokenOnlyLoggerAdapter(base_logger, token_id)


class _TokenOnlyLoggerAdapter(logging.LoggerAdapter):
    """Internal adapter for token-only contexts (no team names available)."""

    def __init__(self, logger: logging.Logger, token_id: str) -> None:
        super().__init__(logger, {"token_id": token_id})

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        token_id = self.extra["token_id"]
        return f"[{token_id}] {msg}", kwargs


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
