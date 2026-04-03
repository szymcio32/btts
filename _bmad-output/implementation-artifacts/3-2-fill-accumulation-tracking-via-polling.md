# Story 3.2: Fill Accumulation Tracking via Polling

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to periodically check my buy orders for fills and track accumulated shares,
so that it knows when enough shares are filled to place a sell order.

## Acceptance Criteria

1. **Given** the `btts_bot/state/` package from Story 1.1
   **When** the position tracking module is implemented
   **Then** `position_tracker.py` provides a `PositionTracker` class that stores fill accumulations keyed by `token_id`
   **And** `PositionTracker` provides methods: `accumulate(token_id, fill_size)`, `get_accumulated_fills(token_id)`, `has_reached_threshold(token_id, min_size)`
   **And** `PositionTracker` is a pure data manager — it holds state and answers queries but never initiates API calls

2. **Given** one or more buy orders in BUY_PLACED or FILLING state
   **When** the fill polling loop runs (at `timing.fill_poll_interval_seconds` intervals via APScheduler)
   **Then** for each active buy order, it queries the CLOB API for current fill status via `ClobClientWrapper.get_order(order_id)`
   **And** new fills are accumulated in PositionTracker via `accumulate(token_id, new_fill_delta)`
   **And** the game transitions from BUY_PLACED to FILLING on first fill detection

3. **Given** a buy order has no new fills since the last poll
   **When** the polling loop checks it
   **Then** no state change occurs and no log is emitted (avoid log noise)

4. **Given** a buy order is fully filled or expired/cancelled
   **When** the polling loop detects this via the order's `status` field
   **Then** if expired/cancelled with zero fills, the game transitions to EXPIRED state with an INFO log

5. **Given** the CLOB API returns an error during fill polling
   **When** `@with_retry` exhausts retries (returns `None`)
   **Then** the error is logged at WARNING level and the bot continues polling other orders (non-fatal)

## Tasks / Subtasks

- [x] Task 1: Implement `PositionTracker` in `btts_bot/state/position_tracker.py` (AC: #1)
  - [x] Replace the stub with a full `PositionTracker` class
  - [x] Store `_fills: dict[str, float]` mapping `token_id` → accumulated fill size
  - [x] `accumulate(token_id, fill_size)` — adds `fill_size` to the running total, logs at DEBUG level
  - [x] `get_accumulated_fills(token_id)` — returns accumulated fills (default `0.0`)
  - [x] `has_reached_threshold(token_id, min_size)` — returns `accumulated >= min_size`
  - [x] Pure data manager: no API imports, no scheduling, no business logic
  - [x] Include `from __future__ import annotations`, module-level `logger`

- [x] Task 2: Extend `OrderTracker` with `sell_price` on `BuyOrderRecord` and active-buy enumeration (AC: #2)
  - [x] Add `sell_price: float` field to `BuyOrderRecord` dataclass
  - [x] Update `record_buy(token_id, order_id, buy_price, sell_price)` signature — add `sell_price` parameter
  - [x] Add `active: bool = True` field to `BuyOrderRecord` (defaults to `True`)
  - [x] Add `mark_inactive(token_id)` method — sets `active = False` on the buy record
  - [x] Add `get_active_buy_orders() -> list[BuyOrderRecord]` — returns all records where `active is True`
  - [x] Update all existing callers of `record_buy` to pass `sell_price`
  - [x] Update existing tests that construct `BuyOrderRecord` or call `record_buy`

- [x] Task 3: Implement `FillPollingService` in `btts_bot/core/fill_polling.py` (AC: #2-#5)
  - [x] Create new file `btts_bot/core/fill_polling.py`
  - [x] `FillPollingService.__init__` receives: `clob_client`, `order_tracker`, `position_tracker`, `market_registry`, `btts_config`
  - [x] `poll_all_active_orders()` — the method called by the scheduler on each tick
  - [x] `_poll_single_order(buy_record)` — polls one order, returns quietly on no change
  - [x] Parse `get_order()` response: extract `size_matched`, `original_size`, `status`
  - [x] Compute `new_fill_delta = current_size_matched - previously_accumulated`
  - [x] If `new_fill_delta > 0`: call `position_tracker.accumulate(token_id, new_fill_delta)` and log INFO
  - [x] On first fill (state == BUY_PLACED): transition to FILLING
  - [x] If order `status` indicates cancelled/expired AND `accumulated == 0`: transition to EXPIRED, mark order inactive
  - [x] If order fully matched (`size_matched == original_size`): mark order inactive
  - [x] If `get_order()` returns `None` (retry exhausted): log WARNING, skip this order, continue

- [x] Task 4: Register fill polling interval job in `btts_bot/main.py` (AC: #2)
  - [x] Import `PositionTracker` from `btts_bot.state.position_tracker`
  - [x] Import `FillPollingService` from `btts_bot.core.fill_polling`
  - [x] Instantiate `position_tracker = PositionTracker()` alongside other state managers
  - [x] Instantiate `fill_polling_service = FillPollingService(clob_client, order_tracker, position_tracker, market_registry, config.btts)`
  - [x] After `scheduler_service.start()`, add an interval job: `scheduler_service.scheduler.add_job(fill_polling_service.poll_all_active_orders, 'interval', seconds=config.timing.fill_poll_interval_seconds, id='fill_polling', name='Fill polling', replace_existing=True)`

- [x] Task 5: Write tests for `PositionTracker` in `tests/test_position_tracker.py` (AC: #1)
  - [x] Test: `accumulate` adds fill amounts correctly
  - [x] Test: `get_accumulated_fills` returns `0.0` for unknown `token_id`
  - [x] Test: `has_reached_threshold` returns True when accumulated >= min_size
  - [x] Test: `has_reached_threshold` returns False when accumulated < min_size
  - [x] Test: multiple `accumulate` calls sum correctly

- [x] Task 6: Write tests for `FillPollingService` in `tests/test_fill_polling.py` (AC: #2-#5)
  - [x] Test: first fill transitions BUY_PLACED → FILLING and accumulates
  - [x] Test: subsequent fill adds delta only (no duplicate accumulation)
  - [x] Test: no-change poll emits no log and no state change (AC #3)
  - [x] Test: fully filled order marks record inactive
  - [x] Test: expired/cancelled order with zero fills transitions to EXPIRED and marks inactive (AC #4)
  - [x] Test: `get_order` returns `None` — WARNING logged, other orders still polled (AC #5)
  - [x] Test: `poll_all_active_orders` iterates all active buy orders
  - [x] Test: orders in non-active states (BUY_PLACED/FILLING only) are polled

- [x] Task 7: Update existing tests for `OrderTracker` changes in `tests/test_order_tracker.py` (if exists) and other files
  - [x] Update all `record_buy` calls to include `sell_price` parameter
  - [x] Update `BuyOrderRecord` constructions to include `sell_price`
  - [x] Add tests for `get_active_buy_orders()` and `mark_inactive()`
  - [x] Update `tests/test_order_execution.py` — `record_buy` calls now include `sell_price`
  - [x] Update `tests/test_main.py` — add `PositionTracker` and `FillPollingService` mocks/patches

- [x] Task 8: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed
  - [x] All existing tests still pass (no regressions)

## Dev Notes

### Critical Context: PositionTracker is a Stub — Build from Scratch

`btts_bot/state/position_tracker.py` currently contains only:

```python
"""
Position tracker for monitoring open positions.
Implemented in Story 3.2.
"""
# TODO: implemented in Story 3.2
```

This must be replaced entirely. It is a pure data manager in `state/` — never initiates API calls, never imports from `clients/` or `core/`.

### Critical Context: OrderTracker Needs Extension — Do NOT Recreate

`btts_bot/state/order_tracker.py` exists with:
- `BuyOrderRecord(token_id, order_id, buy_price)` — **no `sell_price` or `active` flag**
- `record_buy(token_id, order_id, buy_price)` — **no `sell_price` parameter**
- `has_buy_order(token_id)`, `get_buy_order(token_id)`, `get_order(token_id)`
- `has_sell_order(token_id)`, `record_sell(token_id, order_id)` — stubs for Story 3.3
- No method to enumerate active buy orders

**Required extensions for Story 3.2:**
1. Add `sell_price: float` field to `BuyOrderRecord` — needed downstream by Story 3.3 for sell order price, but must be stored now since `place_buy_order()` already has `sell_price` available.
2. Add `active: bool = True` field to `BuyOrderRecord` — used to skip fully-filled or expired orders in future polls.
3. Add `mark_inactive(token_id)` — sets `active = False`.
4. Add `get_active_buy_orders() -> list[BuyOrderRecord]` — returns records where `active is True`.
5. Update `record_buy` signature to accept `sell_price`.

**Ripple effect:** `OrderExecutionService.place_buy_order()` in `btts_bot/core/order_execution.py` calls `order_tracker.record_buy(token_id, order_id, buy_price)`. Must be updated to pass `sell_price`:
```python
self._order_tracker.record_buy(token_id, order_id, buy_price, sell_price)
```

### Polymarket `get_order()` API Response (Critical for Parsing)

`ClobClientWrapper.get_order(order_id)` already exists with `@with_retry`. It returns an `OpenOrder` object from the CLOB API with these key fields:

| Field | Type | Description |
|---|---|---|
| `status` | `str` | One of: `"MATCHED"`, `"LIVE"`, `"CANCELED"`, `"INVALID"`, `"CANCELED_MARKET_RESOLVED"` |
| `original_size` | `str` | Total order size in fixed-math (6 decimals). E.g., `"100000000"` = 100 shares |
| `size_matched` | `str` | Matched (filled) amount in fixed-math (6 decimals). E.g., `"50000000"` = 50 shares |
| `associate_trades` | `list` | Not needed — use `size_matched` delta instead |

**Fixed-math conversion:**
```python
def _parse_fixed_math(value: str) -> float:
    """Convert CLOB fixed-math string (6 decimals) to float shares."""
    return int(value) / 1_000_000
```

**Order status interpretation for polling:**
- `"LIVE"` — order still active, may have partial fills. Check `size_matched`.
- `"MATCHED"` — fully filled. Final `size_matched == original_size`. Mark inactive.
- `"CANCELED"` / `"CANCELED_MARKET_RESOLVED"` / `"INVALID"` — expired/cancelled. If `size_matched == 0`, transition to EXPIRED.

**Important:** The py-clob-client `get_order()` returns an object, not a dict. Access fields as attributes: `order.size_matched`, `order.original_size`, `order.status`.

### Fill Delta Tracking Strategy

The polling service must track **delta fills**, not absolute fills. On each poll:

1. Read `current_filled = _parse_fixed_math(order.size_matched)`
2. Read `previously_accumulated = position_tracker.get_accumulated_fills(token_id)`
3. `delta = current_filled - previously_accumulated`
4. If `delta > 0`: `position_tracker.accumulate(token_id, delta)`
5. If `delta == 0`: skip silently (AC #3)

This approach works because `PositionTracker.accumulate()` adds incrementally, so the tracker's running total stays in sync with the CLOB's `size_matched` value. On each poll, we only accumulate the *new* fills since last check.

### FillPollingService Design

```python
"""Fill polling service for tracking buy order fill accumulation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from btts_bot.clients.clob import ClobClientWrapper
    from btts_bot.config import BttsConfig
    from btts_bot.state.market_registry import MarketRegistry
    from btts_bot.state.order_tracker import OrderTracker
    from btts_bot.state.position_tracker import PositionTracker

from btts_bot.core.game_lifecycle import GameState

logger = logging.getLogger(__name__)

# CLOB order statuses indicating the order is no longer active
_TERMINAL_STATUSES = frozenset({"MATCHED", "CANCELED", "INVALID", "CANCELED_MARKET_RESOLVED"})


def _parse_fixed_math(value: str) -> float:
    """Convert CLOB fixed-math string (6 decimals) to float shares."""
    return int(value) / 1_000_000


class FillPollingService:
    """Polls CLOB API for buy order fills and accumulates in PositionTracker."""

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        btts_config: BttsConfig,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry
        self._btts = btts_config

    def poll_all_active_orders(self) -> None:
        """Poll all active buy orders for fills. Called by scheduler."""
        active_orders = self._order_tracker.get_active_buy_orders()
        if not active_orders:
            return
        for buy_record in active_orders:
            self._poll_single_order(buy_record)

    def _poll_single_order(self, buy_record) -> None:
        """Poll a single buy order for fill progress."""
        token_id = buy_record.token_id
        order_id = buy_record.order_id

        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]"
            if entry is not None
            else f"[{token_id}]"
        )

        # Only poll orders in BUY_PLACED or FILLING state
        if entry is not None and entry.lifecycle.state not in (
            GameState.BUY_PLACED,
            GameState.FILLING,
        ):
            return

        # Query CLOB API
        order = self._clob_client.get_order(order_id)
        if order is None:
            logger.warning(
                "%s Fill poll failed (retry exhausted): order=%s",
                market_name,
                order_id,
            )
            return

        # Parse fill amounts
        current_filled = _parse_fixed_math(order.size_matched)
        original_size = _parse_fixed_math(order.original_size)
        previously_accumulated = self._position_tracker.get_accumulated_fills(token_id)
        delta = current_filled - previously_accumulated

        # Accumulate new fills
        if delta > 0:
            self._position_tracker.accumulate(token_id, delta)
            logger.info(
                "%s Fill detected: +%.2f shares (total: %.2f / %.2f) order=%s",
                market_name,
                delta,
                current_filled,
                original_size,
                order_id,
            )
            # Transition BUY_PLACED → FILLING on first fill
            if entry is not None and entry.lifecycle.state == GameState.BUY_PLACED:
                entry.lifecycle.transition(GameState.FILLING)

        # Handle terminal order statuses
        order_status = order.status
        if order_status in _TERMINAL_STATUSES:
            self._order_tracker.mark_inactive(token_id)
            if order_status != "MATCHED" and current_filled == 0.0:
                # Expired/cancelled with zero fills
                if entry is not None and entry.lifecycle.state in (
                    GameState.BUY_PLACED,
                    GameState.FILLING,
                ):
                    entry.lifecycle.transition(GameState.EXPIRED)
                    logger.info(
                        "%s Buy order expired with no fills: order=%s",
                        market_name,
                        order_id,
                    )
```

### PositionTracker Design

```python
"""Position tracker for monitoring fill accumulation."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks accumulated fill sizes per token_id.

    Pure data manager — holds state and answers queries.
    Never initiates API calls.
    """

    def __init__(self) -> None:
        self._fills: dict[str, float] = {}

    def accumulate(self, token_id: str, fill_size: float) -> None:
        """Add fill_size to the running total for token_id."""
        self._fills[token_id] = self._fills.get(token_id, 0.0) + fill_size
        logger.debug(
            "Fill accumulated: token=%s +%.2f (total: %.2f)",
            token_id,
            fill_size,
            self._fills[token_id],
        )

    def get_accumulated_fills(self, token_id: str) -> float:
        """Return accumulated fill size for token_id (default 0.0)."""
        return self._fills.get(token_id, 0.0)

    def has_reached_threshold(self, token_id: str, min_size: float) -> bool:
        """Return True if accumulated fills >= min_size."""
        return self._fills.get(token_id, 0.0) >= min_size
```

### OrderTracker Extensions

Add to existing `btts_bot/state/order_tracker.py`:

```python
@dataclasses.dataclass
class BuyOrderRecord:
    """Record of a placed buy order."""
    token_id: str
    order_id: str
    buy_price: float
    sell_price: float       # NEW — sell price for downstream sell placement (Story 3.3)
    active: bool = True     # NEW — False when fully filled or expired/cancelled
```

New methods:
```python
def mark_inactive(self, token_id: str) -> None:
    """Mark a buy order as inactive (fully filled or expired)."""
    record = self._buy_orders.get(token_id)
    if record is not None:
        record.active = False
        logger.info("Buy order marked inactive: token=%s order=%s", token_id, record.order_id)

def get_active_buy_orders(self) -> list[BuyOrderRecord]:
    """Return all buy order records where active is True."""
    return [r for r in self._buy_orders.values() if r.active]
```

Update `record_buy` signature:
```python
def record_buy(self, token_id: str, order_id: str, buy_price: float, sell_price: float) -> None:
    self._buy_orders[token_id] = BuyOrderRecord(
        token_id=token_id,
        order_id=order_id,
        buy_price=buy_price,
        sell_price=sell_price,
    )
```

### Ripple Effects from OrderTracker Changes

**`btts_bot/core/order_execution.py` line 135:**
```python
# Current:
self._order_tracker.record_buy(token_id, order_id, buy_price)
# Change to:
self._order_tracker.record_buy(token_id, order_id, buy_price, sell_price)
```
The `sell_price` parameter is already available in `place_buy_order(self, token_id, buy_price, sell_price)`.

**`tests/test_order_execution.py`:**
Any test that calls `tracker.record_buy(...)` directly must add the `sell_price` argument.

**`tests/test_main.py`:**
Must mock/patch `PositionTracker` and `FillPollingService` imports. Add the fill polling scheduler job assertion.

### main.py Wiring Pattern

```python
from btts_bot.state.position_tracker import PositionTracker
from btts_bot.core.fill_polling import FillPollingService

# After other state managers:
position_tracker = PositionTracker()

# After order_execution_service:
fill_polling_service = FillPollingService(
    clob_client, order_tracker, position_tracker, market_registry, config.btts
)

# After scheduler_service.start():
scheduler_service.scheduler.add_job(
    fill_polling_service.poll_all_active_orders,
    'interval',
    seconds=config.timing.fill_poll_interval_seconds,
    id='fill_polling',
    name='Fill polling',
    replace_existing=True,
)
logger.info(
    "Fill polling started: every %d seconds",
    config.timing.fill_poll_interval_seconds,
)
```

### Scheduler Integration

`SchedulerService` already exposes `self.scheduler` property (returns `BackgroundScheduler`). The fill polling job is added after `scheduler_service.start()` from `main.py`. No changes to `scheduling.py` needed.

APScheduler `IntervalTrigger` configuration:
- `seconds=config.timing.fill_poll_interval_seconds` (default 30)
- `id='fill_polling'` — unique job identifier
- `replace_existing=True` — safe for re-registration
- `misfire_grace_time` — not needed for interval jobs (APScheduler handles coalescing)

### File Locations

**Files to create:**
- `btts_bot/core/fill_polling.py` — NEW: `FillPollingService` with `poll_all_active_orders()` and `_poll_single_order()`
- `tests/test_fill_polling.py` — NEW: comprehensive tests for fill polling
- `tests/test_position_tracker.py` — NEW: tests for `PositionTracker`

**Files to modify:**
- `btts_bot/state/position_tracker.py` — REPLACE stub: full `PositionTracker` implementation
- `btts_bot/state/order_tracker.py` — MODIFY: add `sell_price`/`active` to `BuyOrderRecord`, add `mark_inactive()`, `get_active_buy_orders()`, update `record_buy()` signature
- `btts_bot/core/order_execution.py` — MODIFY: update `record_buy()` call to pass `sell_price`
- `btts_bot/main.py` — MODIFY: instantiate `PositionTracker` and `FillPollingService`, add interval job
- `tests/test_order_execution.py` — MODIFY: update `record_buy` calls to include `sell_price`
- `tests/test_main.py` — MODIFY: add `PositionTracker` and `FillPollingService` mocks/patches, verify fill polling job registration

**Files NOT to touch:**
- `btts_bot/clients/clob.py` — `get_order(order_id)` already exists with `@with_retry`
- `btts_bot/config.py` — `TimingConfig.fill_poll_interval_seconds` already exists (default=30)
- `btts_bot/core/game_lifecycle.py` — BUY_PLACED→FILLING, BUY_PLACED→EXPIRED, FILLING→EXPIRED transitions already exist
- `btts_bot/core/scheduling.py` — no changes; scheduler exposes `.scheduler` property, job is added from `main.py`
- `btts_bot/core/liquidity.py` — unchanged
- `btts_bot/core/market_discovery.py` — unchanged
- `btts_bot/state/market_registry.py` — unchanged
- `btts_bot/constants.py` — unchanged
- `btts_bot/retry.py` — unchanged
- `btts_bot/logging_setup.py` — unchanged
- `btts_bot/clients/gamma.py` — unchanged
- `btts_bot/clients/data_api.py` — stub, not involved
- `btts_bot/core/reconciliation.py` — stub for Story 5.1

### Lifecycle Transitions to Use

Transitions already defined in `game_lifecycle.py`:
- `BUY_PLACED → FILLING` — on first fill detection
- `BUY_PLACED → EXPIRED` — buy order expired/cancelled with zero fills
- `FILLING → EXPIRED` — order cancelled with zero fills (edge case: partial fill then cancel)

All transitions exist in `VALID_TRANSITIONS`. No changes to `game_lifecycle.py` needed.

**Note on FILLING → EXPIRED:** The valid transitions include `FILLING → EXPIRED`. However, if a FILLING order gets cancelled but has partial fills (accumulated > 0), do NOT transition to EXPIRED — the position still needs to be managed. Only transition to EXPIRED when `accumulated == 0.0`. If cancelled with partial fills, just mark inactive and leave in FILLING state for Story 3.3 to handle the sell placement.

### Previous Story Intelligence (3.1)

From Story 3.1 completion:
- 248 tests pass (full test suite as of latest commit)
- `OrderExecutionService` is fully wired in `main.py`
- `place_buy_order(token_id, buy_price, sell_price)` — `sell_price` is available but NOT stored in `OrderTracker` (fixed in this story)
- `BuyOrderRecord` has fields: `token_id`, `order_id`, `buy_price` — needs `sell_price` and `active`
- `ClobClientWrapper.get_order(order_id)` exists with `@with_retry`
- `SchedulerService.scheduler` property exposes `BackgroundScheduler` for adding jobs
- `ruff check` and `ruff format` must pass with zero issues
- Tests use pytest with `MagicMock`, `patch`, and `caplog`
- Both `unittest.TestCase` and plain pytest function styles used in test suite
- `from __future__ import annotations` in `core/` and `state/` modules
- Module-level `logger = logging.getLogger(__name__)` in every module
- Type hints on all function signatures
- `@dataclasses.dataclass` for data records

### Git Intelligence

Last 5 commits:
```
0b19fd7 3-1-buy-order-placement-with-duplicate-prevention
2d148ff epic-2-retro
9ddd5a4 2-4-three-case-orderbook-liquidity-analysis
c8f0393 2-3-btts-no-token-selection-and-market-deduplication
1bdd1d9 2-2-scheduled-daily-market-fetch
```

Consistent commit message format: story key only as commit message.

### Architecture Constraints to Enforce

- `core/` modules contain business logic — receive client instances via DI, never import `requests` or `py-clob-client` directly (use `TYPE_CHECKING` for type hints only)
- `state/` modules are pure data managers — hold state and answer queries, NEVER initiate API calls or schedule jobs
- `clients/` modules are thin I/O wrappers — only place that imports `py-clob-client`/`requests`
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` — never set `_state` directly
- `@with_retry` on all API calls in `clients/` — no bare API calls in business logic
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries — caller must handle gracefully

### Architecture Anti-Patterns to Avoid

- Do NOT put API call logic in `PositionTracker` — it is a pure data manager in `state/`
- Do NOT import from `btts_bot.clients` in `fill_polling.py` at module level — use `TYPE_CHECKING` guard for type hints
- Do NOT import `py_clob_client` in `fill_polling.py` — only `clients/clob.py` should reference it
- Do NOT modify `GameLifecycle` transitions — BUY_PLACED→FILLING, BUY_PLACED→EXPIRED, FILLING→EXPIRED already exist
- Do NOT recreate `OrderTracker` from scratch — extend the existing implementation
- Do NOT track absolute fills directly — always track deltas to stay in sync with CLOB's `size_matched`
- Do NOT log on no-change polls (AC #3 explicitly requires silence)
- Do NOT crash on API errors during polling — log WARNING and continue to next order
- Do NOT transition to EXPIRED if partial fills exist (accumulated > 0) — only EXPIRED on zero fills
- Do NOT use `condition_id` as state key — always use `token_id`

### Testing Pattern

```python
# tests/test_position_tracker.py
from btts_bot.state.position_tracker import PositionTracker


def test_accumulate_adds_fills():
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    tracker.accumulate("token-1", 5.0)
    assert tracker.get_accumulated_fills("token-1") == 15.0


def test_get_accumulated_fills_default():
    tracker = PositionTracker()
    assert tracker.get_accumulated_fills("unknown") == 0.0


def test_has_reached_threshold_true():
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    assert tracker.has_reached_threshold("token-1", 5.0) is True


def test_has_reached_threshold_false():
    tracker = PositionTracker()
    tracker.accumulate("token-1", 3.0)
    assert tracker.has_reached_threshold("token-1", 5.0) is False
```

```python
# tests/test_fill_polling.py
from unittest.mock import MagicMock, PropertyMock
from datetime import datetime
from btts_bot.core.fill_polling import FillPollingService, _parse_fixed_math
from btts_bot.core.game_lifecycle import GameState
from btts_bot.state.order_tracker import OrderTracker, BuyOrderRecord
from btts_bot.state.position_tracker import PositionTracker
from btts_bot.state.market_registry import MarketRegistry


def _make_order_response(size_matched="0", original_size="100000000", status="LIVE"):
    """Create a mock CLOB order response."""
    order = MagicMock()
    order.size_matched = size_matched
    order.original_size = original_size
    order.status = status
    return order


def _make_service(clob=None, tracker=None, pos_tracker=None, registry=None, btts=None):
    return FillPollingService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        position_tracker=pos_tracker or PositionTracker(),
        market_registry=registry or MarketRegistry(),
        btts_config=btts or MagicMock(),
    )


def test_first_fill_transitions_to_filling():
    """First fill detection transitions BUY_PLACED → FILLING."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="50000000", status="LIVE"
    )  # 50 shares filled

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    registry = MarketRegistry()
    entry = registry.register(
        token_id="token-1", condition_id="cond-1", token_ids=["t0", "t1"],
        kickoff_time=datetime(2026, 4, 5, 15, 0), league="EPL",
        home_team="Arsenal", away_team="Chelsea",
    )
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(
        clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry
    )
    service.poll_all_active_orders()

    assert pos_tracker.get_accumulated_fills("token-1") == 50.0
    assert entry.lifecycle.state == GameState.FILLING


def test_no_change_poll_silent(caplog):
    """No-change poll produces no log output."""
    clob = MagicMock()
    clob.get_order.return_value = _make_order_response(
        size_matched="50000000", status="LIVE"
    )

    tracker = OrderTracker()
    pos_tracker = PositionTracker()
    pos_tracker.accumulate("token-1", 50.0)  # Already tracked 50 shares
    registry = MarketRegistry()
    entry = registry.register(
        token_id="token-1", condition_id="cond-1", token_ids=["t0", "t1"],
        kickoff_time=datetime(2026, 4, 5, 15, 0), league="EPL",
        home_team="Arsenal", away_team="Chelsea",
    )
    entry.lifecycle.transition(GameState.ANALYSED)
    entry.lifecycle.transition(GameState.BUY_PLACED)
    entry.lifecycle.transition(GameState.FILLING)
    tracker.record_buy("token-1", "order-1", 0.48, 0.50)

    service = _make_service(
        clob=clob, tracker=tracker, pos_tracker=pos_tracker, registry=registry
    )

    import logging
    with caplog.at_level(logging.INFO, logger="btts_bot.core.fill_polling"):
        service.poll_all_active_orders()

    # No INFO-level fill messages should appear
    assert "Fill detected" not in caplog.text


def test_parse_fixed_math():
    assert _parse_fixed_math("100000000") == 100.0
    assert _parse_fixed_math("50000000") == 50.0
    assert _parse_fixed_math("0") == 0.0
    assert _parse_fixed_math("5000000") == 5.0
```

### Scope Boundaries

**In scope:**
- `PositionTracker` class with `accumulate()`, `get_accumulated_fills()`, `has_reached_threshold()`
- `FillPollingService` with `poll_all_active_orders()` and `_poll_single_order()`
- `OrderTracker` extensions: `sell_price`/`active` on `BuyOrderRecord`, `mark_inactive()`, `get_active_buy_orders()`
- Interval job registration in `main.py`
- Ripple effect fixes in `order_execution.py` and existing tests

**Out of scope:**
- Automatic sell order placement (Story 3.3 — triggered when fills reach threshold)
- Pre-kickoff consolidation (Story 4.1)
- Game-start recovery (Story 4.2)
- Startup reconciliation (Story 5.1)
- Any changes to `ClobClientWrapper` (get_order already exists)
- Any changes to `GameLifecycle` transitions (all needed transitions already defined)
- Any changes to `config.py` (`fill_poll_interval_seconds` already exists)

### Project Structure Notes

This story adds fill polling as the bridge between buy order placement and sell order placement:

```
main.py (composition root)
  ├── ClobClientWrapper (clients/)
  ├── MarketRegistry (state/)
  ├── OrderTracker (state/)              — MODIFIED: sell_price, active, mark_inactive, get_active_buy_orders
  ├── PositionTracker (state/)           — NEW: replaces stub
  ├── GammaClient (clients/)
  ├── MarketDiscoveryService (core/)
  ├── LiquidityAnalyser (core/)
  ├── MarketAnalysisPipeline (core/)
  ├── OrderExecutionService (core/)      — MODIFIED: record_buy call updated
  ├── FillPollingService (core/)         — NEW
  └── SchedulerService (core/)           — UNCHANGED (job added from main.py)
```

Flow after this story:
```
discover → analyse → execute_all_analysed → [scheduler: poll fills every 30s] → [future: sell on threshold]
```

### References

- [Source: epics.md#Story 3.2: Fill Accumulation Tracking via Polling] — acceptance criteria
- [Source: architecture.md#State Management Architecture] — PositionTracker: fill accumulations per market, min-threshold logic
- [Source: architecture.md#Order Execution & Position Mgmt] — `core/order_execution.py`, `state/order_tracker.py`, `state/position_tracker.py`
- [Source: architecture.md#API Client Architecture & Retry Strategy] — ClobClientWrapper, @with_retry, returns None on exhaustion
- [Source: architecture.md#Game Lifecycle Management] — BUY_PLACED→FILLING, BUY_PLACED→EXPIRED, FILLING→EXPIRED transitions
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — duplicate prevention, logging patterns, error handling
- [Source: architecture.md#Enforcement Guidelines] — token_id canonical key, transition via GameLifecycle, @with_retry mandated
- [Source: architecture.md#Fill Polling Loop diagram] — ClobClientWrapper.get_order → PositionTracker.accumulate → lifecycle transitions
- [Source: prd.md#FR13] — track incremental fill accumulation on placed buy orders
- [Source: prd.md#FR22] — in-memory state maintenance (PositionTracker)
- [Source: config.py#TimingConfig] — fill_poll_interval_seconds already defined (default=30)
- [Source: game_lifecycle.py#VALID_TRANSITIONS] — BUY_PLACED→FILLING, BUY_PLACED→EXPIRED, FILLING→EXPIRED confirmed
- [Source: scheduling.py#SchedulerService] — .scheduler property exposes BackgroundScheduler for adding interval jobs
- [Source: 3-1-buy-order-placement-with-duplicate-prevention.md] — OrderTracker structure, sell_price available but not stored, 248 tests
- [Source: Polymarket CLOB API /order/{orderID}] — OpenOrder response: status, size_matched, original_size in fixed-math (6 decimals)

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

### Completion Notes List

- Replaced `position_tracker.py` stub with full `PositionTracker` class (pure data manager, no API calls).
- Extended `BuyOrderRecord` dataclass with `sell_price: float` and `active: bool = True` fields.
- Updated `record_buy()` signature to require `sell_price`; ripple-effect updated `order_execution.py` and all test files (`test_order_tracker.py`, `test_order_execution.py`, `test_market_discovery.py`).
- Added `mark_inactive()` and `get_active_buy_orders()` methods to `OrderTracker`.
- Created `btts_bot/core/fill_polling.py` with `FillPollingService`; delta-fill strategy, terminal status handling, WARNING on API failure.
- Wired `PositionTracker`, `FillPollingService`, and APScheduler interval job in `main.py`.
- Created `tests/test_position_tracker.py` (8 tests) and `tests/test_fill_polling.py` (20 tests).
- Updated `tests/test_order_tracker.py` with 8 new tests for `sell_price`, `mark_inactive`, `get_active_buy_orders`.
- Updated `tests/test_main.py` with mocks/patches for `PositionTracker` and `FillPollingService`, plus 4 new wiring tests.
- All 258 tests pass; `ruff check` and `ruff format` report zero issues.

### File List

- `btts_bot/state/position_tracker.py` — REPLACED stub: full `PositionTracker` implementation
- `btts_bot/state/order_tracker.py` — MODIFIED: `sell_price`/`active` on `BuyOrderRecord`, `mark_inactive()`, `get_active_buy_orders()`, updated `record_buy()` signature
- `btts_bot/core/fill_polling.py` — NEW: `FillPollingService` with `poll_all_active_orders()` and `_poll_single_order()`
- `btts_bot/core/order_execution.py` — MODIFIED: updated `record_buy()` call to pass `sell_price`
- `btts_bot/main.py` — MODIFIED: import and instantiate `PositionTracker` and `FillPollingService`, register interval job
- `tests/test_position_tracker.py` — NEW: 8 tests for `PositionTracker`
- `tests/test_fill_polling.py` — NEW: 20 tests for `FillPollingService`
- `tests/test_order_tracker.py` — MODIFIED: updated `record_buy` calls, added tests for new methods
- `tests/test_order_execution.py` — MODIFIED: updated `record_buy` calls to include `sell_price`
- `tests/test_market_discovery.py` — MODIFIED: updated `record_buy` calls to include `sell_price`
- `tests/test_main.py` — MODIFIED: added `PositionTracker`/`FillPollingService` mocks, new wiring tests
