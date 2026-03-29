# Story 1.4: Retry Decorator for API Resilience

Status: review

## Story

As an operator,
I want all API calls to automatically retry on transient failures with exponential backoff,
So that temporary network issues or server errors don't crash the bot or lose operations.

## Acceptance Criteria

1. **Given** an API call decorated with `@with_retry`
   **When** the call fails with a retryable error (status 425, 429, 500, 503, or network/connection error)
   **Then** the decorator retries with exponential backoff (base=1s, max=30s) plus jitter, up to 5 retries
   **And** each retry attempt is logged at WARNING level

2. **Given** an API call fails with a non-retryable error (HTTP 400, or message containing "not enough balance" or "minimum tick size")
   **When** the error is detected
   **Then** the error is re-raised immediately without retry

3. **Given** an API call exhausts all 5 retries
   **When** the final retry fails
   **Then** the decorator returns `None` (does not raise)
   **And** an ERROR level log message is emitted
   **And** the caller handles `None` by skipping the operation for that market

4. **Given** `@with_retry` is applied to any function
   **When** the function succeeds on the first call
   **Then** no retry logic runs — zero overhead on the happy path

## Tasks / Subtasks

- [x] Task 1: Implement `@with_retry` decorator in `btts_bot/retry.py` (AC: #1, #2, #3, #4)
  - [x] Define `RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({425, 429, 500, 503})`
  - [x] Define `NON_RETRYABLE_MESSAGES: tuple[str, ...] = ("not enough balance", "minimum tick size")`
  - [x] Define `MAX_RETRIES = 5`, `BASE_DELAY = 1.0`, `MAX_DELAY = 30.0`
  - [x] Implement `with_retry` as a decorator factory (or direct decorator) using `functools.wraps`
  - [x] In retry loop: catch `requests.RequestException` and `Exception`
  - [x] Extract HTTP status code from exception: for `requests.HTTPError`, read `exc.response.status_code`; for other exceptions, inspect `str(exc)` for status hint
  - [x] Check non-retryable messages via `any(msg in str(exc).lower() for msg in NON_RETRYABLE_MESSAGES)` — if matched, re-raise immediately
  - [x] Check HTTP 400: if status == 400, re-raise immediately
  - [x] If retryable (status in `RETRYABLE_STATUS_CODES` or network error with no status): log WARNING and schedule retry
  - [x] Compute delay: `min(BASE_DELAY * (2 ** attempt), MAX_DELAY) + random.uniform(0, 1)` where `attempt` is 0-indexed
  - [x] Sleep the computed delay between retries
  - [x] After 5 retries exhausted: log ERROR with function name, attempt count, and last exception message; return `None`
  - [x] On success: return the function's return value directly

- [x] Task 2: Add module-level logger to `retry.py` (AC: #1, #3)
  - [x] `logger = logging.getLogger(__name__)` at module level
  - [x] WARNING log on each retry: `"[retry] %s: attempt %d/%d failed: %s — retrying in %.1fs"` (func name, attempt, max, error, delay)
  - [x] ERROR log on exhaustion: `"[retry] %s: all %d retries exhausted. Last error: %s. Returning None."` (func name, max retries, error)

- [x] Task 3: Verify `retry.py` is importable with no side effects (AC: #4)
  - [x] `uv run python -c "from btts_bot.retry import with_retry; print('OK')"` must print `OK`

- [x] Task 4: Add tests in `tests/test_retry.py` (AC: #1, #2, #3, #4)
  - [x] Test: function succeeds first call → returns value, no retry (AC: #4)
  - [x] Test: retryable status (e.g., 500) → retries up to 5 times → returns `None` (AC: #1, #3)
  - [x] Test: retryable status exhausted → ERROR log emitted (AC: #3)
  - [x] Test: non-retryable message "not enough balance" → re-raised immediately (AC: #2)
  - [x] Test: non-retryable message "minimum tick size" → re-raised immediately (AC: #2)
  - [x] Test: HTTP 400 → re-raised immediately (AC: #2)
  - [x] Test: network error (`requests.ConnectionError`) → treated as retryable → returns `None` after retries (AC: #1)
  - [x] Test: WARNING logged on each retry attempt (AC: #1)

- [x] Task 5: Lint and format (all stories convention)
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### File location

`btts_bot/retry.py` — already exists as a stub with a `# TODO: implemented in Story 1.4` comment. Replace the entire file contents.

This file lives at the top level of the `btts_bot/` package (same level as `config.py`, `logging_setup.py`), making it importable as `from btts_bot.retry import with_retry`.

### Critical: `@with_retry` is infrastructure for ALL subsequent stories

Every `clients/` method in Epics 2-5 must use `@with_retry`. This decorator must be solid — it must never crash the bot itself and must always return a value (never raise after retries are exhausted). The contract is: **return `None` on failure, return the function result on success**.

The architecture explicitly states:
> After max retries exhausted: return `None`, caller handles gracefully (skip and continue)

### Exact decorator implementation pattern

```python
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

                # If retryable status code check (or any other exception = network error)
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
```

Key points:
- Use `functools.wraps(func)` to preserve function metadata
- `F = TypeVar("F", bound=Callable[..., Any])` + `return wrapper  # type: ignore[return-value]` is the idiomatic pattern for typed decorators that preserve signatures
- `random.uniform(0, 1)` for jitter — adds 0–1s of random noise on top of exponential delay
- Non-retryable check comes **before** status code check so business error messages short-circuit first
- Any exception that is NOT an `HTTPError` with a 400 status and NOT containing non-retryable messages is treated as retryable (covers `ConnectionError`, `Timeout`, `requests.RequestException`, and CLOB client exceptions)
- Return type is `Any` because the decorator changes the return type to include `None`

### Retryable vs non-retryable decision table

| Condition | Action |
|---|---|
| `requests.HTTPError` with status 425, 429, 500, 503 | Retry with backoff |
| `requests.ConnectionError`, `requests.Timeout`, other `requests.RequestException` | Retry with backoff |
| Any other exception (CLOB client internal, etc.) | Retry with backoff |
| `requests.HTTPError` with status 400 | Re-raise immediately |
| Exception message contains "not enough balance" | Re-raise immediately |
| Exception message contains "minimum tick size" | Re-raise immediately |
| All 5 retries exhausted | Return `None`, log ERROR |

### How callers handle `None`

This pattern is mandatory throughout all client wrappers (Epics 2-5):

```python
# In core/ business logic:
result = clob_client.place_order(...)  # wrapped with @with_retry
if result is None:
    logger.error("[%s] Order placement failed after retries — skipping market", market_name)
    lifecycle.transition(GameState.SKIPPED)
    return
```

The caller **never** assumes a non-None return. This is the contract.

### Testing pattern — use `unittest.mock.patch` to avoid real sleeps

Tests must patch `time.sleep` to avoid slow tests:

```python
from unittest.mock import MagicMock, call, patch
import requests

@patch("btts_bot.retry.time.sleep")
def test_retries_on_500_and_returns_none(self, mock_sleep):
    call_count = 0

    @with_retry
    def flaky():
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 500
        raise requests.HTTPError(response=resp)

    result = flaky()
    self.assertIsNone(result)
    self.assertEqual(call_count, 5)  # exactly MAX_RETRIES attempts
    self.assertEqual(mock_sleep.call_count, 5)  # slept between each attempt
```

Also patch `btts_bot.retry.random.uniform` to return `0` for deterministic delay values in assertions.

### Logging in tests — capture WARNING and ERROR

```python
import logging

with self.assertLogs("btts_bot.retry", level="WARNING") as log_ctx:
    result = flaky_func()

# Check WARNING messages were emitted
warning_msgs = [r for r in log_ctx.records if r.levelno == logging.WARNING]
self.assertEqual(len(warning_msgs), MAX_RETRIES)

# Check ERROR on exhaustion
error_msgs = [r for r in log_ctx.records if r.levelno == logging.ERROR]
self.assertEqual(len(error_msgs), 1)
```

### ruff compliance notes

- `line-length = 100` (from `pyproject.toml`)
- `target-version = "py314"` — Python 3.14 type syntax is fine (e.g., `int | None`)
- Import order: stdlib first, then third-party (`requests`), then local — ruff enforces this
- No bare `except:` — always `except Exception as exc:`
- The `# type: ignore[return-value]` comment on `return wrapper` is acceptable (ruff won't flag it)

### Files NOT to touch

- `btts_bot/config.py` — no changes needed
- `btts_bot/logging_setup.py` — no changes needed
- `btts_bot/main.py` — no changes needed
- `btts_bot/constants.py` — retry constants live in `retry.py`, not `constants.py`
- Any `clients/`, `state/`, `core/` stubs — those are for later stories

### Project Structure Notes

- `btts_bot/retry.py` — replaces stub with full implementation
- `tests/test_retry.py` — new test file (does not exist yet)
- No other files are created or modified in this story

### References

- [Source: epics.md#Story 1.4: Retry Decorator for API Resilience] — story requirements and acceptance criteria
- [Source: epics.md#Requirements Inventory] — NFR2 (no single API call may terminate the bot), NFR8 (retry with backoff on all CLOB calls)
- [Source: architecture.md#API Client Architecture & Retry Strategy] — `@with_retry` decorator design, retryable status codes (425, 429, 500, 503), non-retryable errors
- [Source: architecture.md#Error Handling] — "All API calls must be wrapped with `@with_retry`. No bare `client.method()` calls in business logic."
- [Source: architecture.md#Communication Patterns > Logging Levels] — WARNING for retry attempts, ERROR for exhausted retries
- [Source: architecture.md#Complete Project Directory Structure] — `retry.py` at top level of `btts_bot/` package
- [Source: architecture.md#Enforcement Guidelines] — "Wrap all API calls with `@with_retry` — no exceptions"

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

None — implementation was straightforward, matching the exact pattern specified in Dev Notes.

### Completion Notes List

- Replaced stub `btts_bot/retry.py` with full `@with_retry` decorator implementation using `functools.wraps`, exponential backoff (base=1s, max=30s), jitter via `random.uniform(0,1)`, and module-level logger.
- Non-retryable short-circuits: HTTP 400 and messages matching "not enough balance" / "minimum tick size" (case-insensitive) are re-raised immediately without sleeping.
- All other exceptions (including `ConnectionError`, `Timeout`, generic `Exception`) are treated as retryable — up to `MAX_RETRIES=5` attempts.
- After exhaustion, returns `None` and logs ERROR; callers handle `None` by skipping the operation.
- Created `tests/test_retry.py` with 20 tests across 5 test classes covering all ACs: success path (zero overhead), retryable errors (425/429/500/503/ConnectionError/Timeout/generic), non-retryable errors (400/balance/tick-size), log levels (WARNING per attempt, ERROR on exhaustion), and exponential delay values with cap verification.
- `time.sleep` and `random.uniform` patched in all tests for deterministic, fast execution.
- Full regression suite: 66/66 passed. Ruff: 0 lint issues, 27 files already formatted.

### File List

- `btts_bot/retry.py` (modified — replaced stub with full implementation)
- `tests/test_retry.py` (new — 20 tests covering all acceptance criteria)

## Change Log

- 2026-03-29: Story 1.4 implemented — `@with_retry` decorator with exponential backoff, jitter, retryable/non-retryable error handling, and comprehensive test suite (20 tests, 66 total passing).
