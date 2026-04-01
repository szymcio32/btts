# Story 2.2: Scheduled Daily Market Fetch

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to automatically fetch new markets once daily at my configured UTC hour,
so that tomorrow's games are discovered and queued for trading without manual intervention.

## Acceptance Criteria

1. **Given** a valid `timing.daily_fetch_hour_utc` in the config (e.g., 23)
   **When** the bot starts
   **Then** an APScheduler `CronTrigger` job is registered to trigger market discovery daily at the configured UTC hour
   **And** the scheduler runs in the background without blocking the main loop

2. **Given** the daily fetch triggers
   **When** new markets are discovered
   **Then** only markets not already in `MarketRegistry` are added (skip duplicates)
   **And** newly discovered markets are logged at INFO level
   **And** the entire daily fetch cycle completes within 5 minutes (NFR12)

3. **Given** the bot starts
   **When** the scheduler is initialized
   **Then** the startup discovery (from Story 2.1) still runs immediately as before
   **And** the scheduled daily fetch runs separately at the configured hour
   **And** the bot does NOT exit after startup discovery — it continues running via the scheduler's event loop

4. **Given** the scheduler is running
   **When** the daily fetch job raises an exception
   **Then** APScheduler catches it and logs the error
   **And** the scheduler continues running — the next daily trigger still fires normally
   **And** the bot does not crash

5. **Given** the bot process
   **When** the main loop is running
   **Then** the bot stays alive via a blocking loop (e.g., `while True: time.sleep(1)` or scheduler blocking) with proper `KeyboardInterrupt` handling for clean shutdown

## Tasks / Subtasks

- [x] Task 1: Implement `SchedulerService` in `btts_bot/core/scheduling.py` (AC: #1, #4)
  - [x] Import and configure APScheduler `BackgroundScheduler` with `timezone=utc`
  - [x] Constructor takes `daily_fetch_hour_utc: int` and `discovery_service: MarketDiscoveryService`
  - [x] Implement `start()` method that adds a cron job for daily market fetch and starts the scheduler
  - [x] Implement `shutdown()` method that calls `scheduler.shutdown(wait=False)`
  - [x] Add module-level logger
  - [x] The cron job callback calls `discovery_service.discover_markets()`

- [x] Task 2: Update `btts_bot/main.py` to wire scheduler and add main loop (AC: #1, #3, #5)
  - [x] Import `SchedulerService` from `btts_bot.core.scheduling`
  - [x] After startup discovery, instantiate `SchedulerService(config.timing.daily_fetch_hour_utc, discovery_service)`
  - [x] Call `scheduler_service.start()`
  - [x] Add a blocking loop (`while True: time.sleep(1)`) wrapped in `try/except KeyboardInterrupt` for clean shutdown
  - [x] On `KeyboardInterrupt`, call `scheduler_service.shutdown()` and log exit

- [x] Task 3: Write tests (AC: #1-#5)
  - [x] `tests/test_scheduling.py`:
    - [x] Test: `SchedulerService` creates a `BackgroundScheduler` with UTC timezone
    - [x] Test: `start()` adds a cron job at the configured hour
    - [x] Test: cron job callback calls `discovery_service.discover_markets()`
    - [x] Test: `shutdown()` calls `scheduler.shutdown(wait=False)`
    - [x] Test: scheduler handles job exceptions without crashing (APScheduler's built-in behavior)
  - [x] `tests/test_main.py`:
    - [x] Update existing tests to account for new scheduler wiring
    - [x] Test: main wires scheduler with correct daily_fetch_hour_utc from config

- [x] Task 4: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### Architecture Context

This story introduces the APScheduler `BackgroundScheduler` as a shared infrastructure component. Per the architecture document's cross-epic dependency note: "Epic 4 (Stories 4.1 and 4.2) reuses this same scheduler for per-game date triggers (pre-kickoff and game-start). The scheduler should be created as a shared infrastructure component injected into modules that need it."

For this story, the scheduler only needs to handle the daily cron job. Future stories (3.2 for fill polling, 4.1/4.2 for per-game date triggers) will extend this service with additional job types. Design the `SchedulerService` so the internal `BackgroundScheduler` instance can be accessed or extended later, but do NOT implement those future jobs now.

### APScheduler 3.x API (v3.11.2)

This project uses APScheduler **3.x** (specifically 3.11.2), NOT APScheduler 4.x. The APIs are very different. Key 3.x patterns:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import utc  # or datetime.timezone.utc

scheduler = BackgroundScheduler(timezone=utc)

# Add a cron job that runs daily at hour=23 UTC
scheduler.add_job(
    func=some_callable,
    trigger=CronTrigger(hour=23, timezone=utc),
    id="daily_market_fetch",
    name="Daily market fetch",
    replace_existing=True,
    misfire_grace_time=3600,  # Allow 1 hour late execution
)

scheduler.start()  # Starts in background thread
# ...
scheduler.shutdown(wait=False)  # Non-blocking shutdown
```

**Important APScheduler 3.x notes:**
- `BackgroundScheduler` runs in a daemon thread — does NOT block the main thread
- The main thread must stay alive (via a loop or other blocking call) or the process exits
- `misfire_grace_time` should be set generously (3600s = 1 hour) since the bot may have been busy during the exact trigger second
- `replace_existing=True` prevents duplicate jobs on restart
- APScheduler 3.x catches and logs job exceptions by default via its internal logger — jobs don't crash the scheduler
- Use `datetime.timezone.utc` (stdlib) instead of `pytz.utc` to avoid adding a dependency (APScheduler 3.x accepts both)

**Do NOT use:**
- `apscheduler.schedulers.blocking.BlockingScheduler` — this would work but prevents adding interval/date jobs later from other threads. `BackgroundScheduler` is more flexible for the architecture.
- `AsyncIOScheduler` — the project uses synchronous architecture, not asyncio
- APScheduler 4.x API patterns (e.g., `AsyncScheduler`, `add_schedule`, datastore-based) — the installed version is 3.11.2

### File Locations

- `btts_bot/core/scheduling.py` — **replace stub entirely**: implement `SchedulerService`
- `btts_bot/main.py` — **modify**: wire `SchedulerService`, add main loop with `KeyboardInterrupt` handling
- `tests/test_scheduling.py` — **new file**: tests for `SchedulerService`
- `tests/test_main.py` — **modify**: update existing tests for scheduler wiring

Files NOT to touch:
- `btts_bot/config.py` — `TimingConfig` already has `daily_fetch_hour_utc: int` field (validated 0-23), no changes needed
- `btts_bot/core/market_discovery.py` — complete from Story 2.1, call `discover_markets()` as-is
- `btts_bot/clients/gamma.py` — complete from Story 2.1, used internally by `MarketDiscoveryService`
- `btts_bot/state/market_registry.py` — complete from Story 1.6, deduplication handled by `MarketDiscoveryService`
- `btts_bot/logging_setup.py` — complete from Story 1.3
- `btts_bot/retry.py` — complete from Story 1.4
- `btts_bot/clients/clob.py` — complete from Story 1.5
- `btts_bot/core/game_lifecycle.py` — complete from Story 1.6
- All stub files for future stories (order_tracker, position_tracker, liquidity, order_execution, reconciliation)

### `SchedulerService` Implementation Pattern

```python
"""Scheduled job management for market fetching and polling."""

from __future__ import annotations

import logging
from datetime import timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from btts_bot.core.market_discovery import MarketDiscoveryService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled jobs using APScheduler BackgroundScheduler."""

    def __init__(
        self,
        daily_fetch_hour_utc: int,
        discovery_service: MarketDiscoveryService,
    ) -> None:
        self._daily_fetch_hour_utc = daily_fetch_hour_utc
        self._discovery_service = discovery_service
        self._scheduler = BackgroundScheduler(timezone=timezone.utc)

    @property
    def scheduler(self) -> BackgroundScheduler:
        """Expose scheduler for future stories to add jobs."""
        return self._scheduler

    def start(self) -> None:
        """Add scheduled jobs and start the scheduler."""
        self._scheduler.add_job(
            func=self._daily_market_fetch,
            trigger=CronTrigger(hour=self._daily_fetch_hour_utc, timezone=timezone.utc),
            id="daily_market_fetch",
            name="Daily market fetch",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started: daily market fetch at %02d:00 UTC",
            self._daily_fetch_hour_utc,
        )

    def shutdown(self) -> None:
        """Shut down the scheduler without waiting for running jobs."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")

    def _daily_market_fetch(self) -> None:
        """Callback for the daily market fetch cron job."""
        logger.info("Daily scheduled market fetch starting")
        count = self._discovery_service.discover_markets()
        logger.info("Daily scheduled market fetch complete: %d new markets", count)
```

### `main.py` Update Pattern

The current `main.py` ends after startup discovery. It needs:

1. `SchedulerService` instantiation and start
2. A blocking main loop that keeps the process alive
3. `KeyboardInterrupt` handling for graceful shutdown

```python
import time

from btts_bot.core.scheduling import SchedulerService

# ... existing code through startup discovery ...

# Schedule daily fetch (FR6)
scheduler_service = SchedulerService(
    daily_fetch_hour_utc=config.timing.daily_fetch_hour_utc,
    discovery_service=discovery_service,
)
scheduler_service.start()

logger.info("btts-bot running. Press Ctrl+C to exit.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Shutdown requested")
finally:
    scheduler_service.shutdown()
    logger.info("btts-bot stopped")
```

**Critical design notes:**
- The `while True: time.sleep(1)` loop is the standard pattern for keeping a `BackgroundScheduler` process alive. The sleep interval of 1 second is fine — it doesn't affect scheduler precision (APScheduler has its own internal timer).
- `KeyboardInterrupt` handling ensures clean scheduler shutdown on Ctrl+C or SIGINT.
- The `finally` block ensures `scheduler_service.shutdown()` is always called.
- Do NOT use `BlockingScheduler` here — the architecture needs `BackgroundScheduler` so future stories can add jobs from the main thread (e.g., per-game date triggers in Epic 4).

### Testing Pattern

```python
# tests/test_scheduling.py
from datetime import timezone
from unittest.mock import MagicMock, patch

from btts_bot.core.scheduling import SchedulerService


def test_scheduler_creates_with_utc_timezone():
    """SchedulerService creates a BackgroundScheduler with UTC timezone."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    assert service.scheduler.timezone == timezone.utc


def test_start_adds_cron_job():
    """start() adds a daily market fetch cron job and starts the scheduler."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=14, discovery_service=discovery)
    with patch.object(service.scheduler, "add_job") as mock_add, \
         patch.object(service.scheduler, "start") as mock_start:
        service.start()
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs.kwargs["id"] == "daily_market_fetch"
        mock_start.assert_called_once()


def test_daily_fetch_callback_calls_discover():
    """The daily fetch callback calls discovery_service.discover_markets()."""
    discovery = MagicMock()
    discovery.discover_markets.return_value = 5
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    service._daily_market_fetch()
    discovery.discover_markets.assert_called_once()


def test_shutdown_calls_scheduler_shutdown():
    """shutdown() calls scheduler.shutdown(wait=False)."""
    discovery = MagicMock()
    service = SchedulerService(daily_fetch_hour_utc=23, discovery_service=discovery)
    with patch.object(service.scheduler, "shutdown") as mock_shutdown:
        service.shutdown()
        mock_shutdown.assert_called_once_with(wait=False)
```

### Previous Story Intelligence (2.1)

From Story 2.1 completion:
- `MarketDiscoveryService.discover_markets()` takes no arguments and returns `int` (count of new markets)
- Deduplication is handled inside `discover_markets()` via `MarketRegistry.is_processed(token_id)` — safe to call repeatedly
- `GammaClient(config.data_file)` reads from a local JSON file
- 111 total tests pass after Story 2.1; this story should add ~5-8 new tests
- `ruff check` and `ruff format` must pass with zero issues
- Tests use `pytest` with `MagicMock`, `patch`, and `caplog`

### Git Intelligence

Last 5 commits:
```
a2d9cea 2-1-market-discovery-from-json-data-file
97b2c29 1-6-game-lifecycle-state-machine-and-market-registry
6f6c926 1-5-polymarket-clob-client-authentication
9a194cf 1-4-retry-decorator-for-api-resilience
5ec8dfc first commit
```

Code conventions from recent commits:
- Module docstrings at top of every file
- `from __future__ import annotations` used in `core/` modules
- `logger = logging.getLogger(__name__)` at module level
- Type hints on all function signatures
- Constructor dependency injection throughout

### Architecture Constraints to Enforce

From project enforcement guidelines:
- All scheduled job logic in `core/scheduling.py` — not in `main.py`
- `core/` modules receive dependencies via constructor injection
- `state/` modules never initiate API calls or schedule jobs
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- No bare API calls without retry wrapper (not applicable here — no direct API calls)

From architecture anti-patterns to avoid:
- Do NOT use `BlockingScheduler` — use `BackgroundScheduler` for future extensibility
- Do NOT import `MarketDiscoveryService` at module level in `scheduling.py` if it creates circular imports — use `TYPE_CHECKING` guard
- Do NOT add interval/date trigger jobs for future stories (fill polling, pre-kickoff, game-start) — those are out of scope
- Do NOT modify `TimingConfig` or `config.py` — the `daily_fetch_hour_utc` field already exists
- Do NOT add `pytest` as a dev dependency — it should already be available; if not, `uv add --dev pytest` first

### NFR12 Compliance

The daily market fetch cycle must complete within 5 minutes (NFR12). Since `discover_markets()` reads a local JSON file and processes ~8-10 games, this is trivially met. No special performance optimization needed. The `misfire_grace_time=3600` on the cron job handles cases where the bot was busy at the exact trigger time.

### Project Structure Notes

This story transforms the bot from a "run-once-and-exit" script into a long-running daemon process. The key architectural change is:

**Before (Story 2.1):** `main()` runs discovery and exits.
**After (Story 2.2):** `main()` runs discovery, starts the scheduler, and blocks indefinitely until interrupted.

The `SchedulerService` is designed as a shared infrastructure component. Future stories will extend it:
- Story 3.2: Add interval trigger for fill polling (`fill_poll_interval_seconds`)
- Story 4.1: Add date triggers for pre-kickoff consolidation (per-game)
- Story 4.2: Add date triggers for game-start recovery (per-game)

The `scheduler` property exposes the internal `BackgroundScheduler` so these future stories can add jobs without modifying the core `SchedulerService` class.

### References

- [Source: epics.md#Story 2.2: Scheduled Daily Market Fetch] — acceptance criteria and cross-epic dependency note
- [Source: architecture.md#Scheduling & Timing Strategy] — APScheduler BackgroundScheduler decision
- [Source: architecture.md#Core Architectural Decisions] — scheduling as shared infrastructure
- [Source: architecture.md#Data Flow] — daily market fetch position in data flow
- [Source: architecture.md#Project Structure & Boundaries] — `core/scheduling.py` location
- [Source: prd.md#FR6] — "System can fetch all BTTS markets once daily at a configured UTC hour"
- [Source: prd.md#NFR12] — "Daily market fetch cycle must complete within 5 minutes"
- [Source: architecture.md#Communication Patterns] — logging levels (INFO for scheduled events)

## Dev Agent Record

### Agent Model Used

claude-opus-4.6

### Debug Log References

No issues encountered during implementation.

### Completion Notes List

- Implemented `SchedulerService` in `btts_bot/core/scheduling.py` replacing the stub. Uses APScheduler 3.x `BackgroundScheduler` with UTC timezone, a `CronTrigger` daily job at the configured hour, `misfire_grace_time=3600`, and `replace_existing=True`. Exposes `scheduler` property for future story extensibility.
- Updated `btts_bot/main.py` to wire `SchedulerService` after startup discovery. Added `while True: time.sleep(1)` blocking loop with `KeyboardInterrupt` handling for clean shutdown. The bot now runs as a long-lived daemon process.
- Created `tests/test_scheduling.py` with 6 tests covering: UTC timezone creation, cron job addition, trigger hour configuration, callback invocation, shutdown delegation, and exception handling.
- Updated `tests/test_main.py` with 6 new tests for scheduler wiring (instantiation with config hour, start call, shutdown on interrupt, running/shutdown/stopped log messages). Refactored existing 9 tests to use a `_run_main_with_patches()` helper that properly handles the new main loop by patching `time.sleep` to raise `KeyboardInterrupt`.
- All 165 tests pass (zero regressions). `ruff check` and `ruff format` clean.

### File List

- `btts_bot/core/scheduling.py` — replaced stub with full `SchedulerService` implementation
- `btts_bot/main.py` — added `SchedulerService` wiring, main loop, and shutdown handling
- `tests/test_scheduling.py` — new file, 6 tests for `SchedulerService`
- `tests/test_main.py` — updated, refactored existing tests + 6 new scheduler wiring tests

### Change Log

- 2026-04-01: Story 2.2 implemented — added SchedulerService with APScheduler BackgroundScheduler for daily market fetch, wired into main.py with blocking loop and graceful shutdown. 165 tests pass, zero regressions.
