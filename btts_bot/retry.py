"""
Retry decorator for API resilience.
Implemented in Story 1.4.
"""

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({425, 429, 500, 503})
NON_RETRYABLE_MESSAGES: tuple[str, ...] = ("not enough balance", "minimum tick size")
MAX_RETRIES = 5
BASE_DELAY = 1.0
MAX_DELAY = 30.0

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(func: F) -> F:
    """Retry decorator with exponential backoff + jitter for API resilience."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc).lower()

                # Non-retryable: business logic errors — re-raise immediately
                if any(msg in exc_str for msg in NON_RETRYABLE_MESSAGES):
                    raise

                # Non-retryable: HTTP 400 validation error — re-raise immediately
                status_code: int | None = None
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    status_code = exc.response.status_code
                if status_code == 400:
                    raise

                # Retryable: log warning and schedule retry with exponential backoff + jitter
                delay = min(BASE_DELAY * (2**attempt), MAX_DELAY) + random.uniform(0, 1)
                logger.warning(
                    "[retry] %s: attempt %d/%d failed: %s — retrying in %.1fs",
                    func.__name__,
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)

        logger.error(
            "[retry] %s: all %d retries exhausted. Last error: %s. Returning None.",
            func.__name__,
            MAX_RETRIES,
            last_exc,
        )
        return None

    return wrapper  # type: ignore[return-value]
