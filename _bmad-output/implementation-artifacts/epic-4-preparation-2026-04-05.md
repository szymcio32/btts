# Epic 4 Preparation: Thread-Safety Analysis & Sell Price Override Design

**Date:** 2026-04-05
**Epic:** Epic 4 - Pre-Kickoff & Game-Start Recovery
**Owners:** Winston (Architect), Amelia (Developer)
**Requested by:** Epic 3 Retrospective (Preparation Tasks #1 and #2)

---

## Overview

Epic 3 retro identified two critical preparation tasks that must complete before Epic 4 implementation begins:

1. **Thread-safety analysis** of all state managers (`OrderTracker`, `PositionTracker`, `MarketRegistry`, `GameLifecycle`) to determine if locks are needed for concurrent per-game recovery threads
2. **Sell price override design decision** -- Epic 4 sells at `buy_price` (not `buy_price + spread`). Decide: parameter override on `place_sell_order()` or new method like `place_emergency_sell()`

---

## Part 1: Thread-Safety Analysis

### Current Threading Model

The bot currently has two execution contexts that share mutable state:

| Thread | Source | What It Does | State It Touches |
|--------|--------|--------------|-----------------|
| **Main thread** | `main.py` startup sequence | Discovery, analysis, buy placement, then sleeps in `while True: time.sleep(1)` | `MarketRegistry` (write), `OrderTracker` (write), `PositionTracker` (read) |
| **APScheduler thread pool** | `BackgroundScheduler` default executor | Runs `_daily_market_fetch()` (cron) and `poll_all_active_orders()` (interval) | `MarketRegistry` (read+write via lifecycle), `OrderTracker` (read+write), `PositionTracker` (read+write), `ClobClientWrapper` (API calls) |

### Epic 4 Threading Model (What Changes)

Epic 4 adds two new job types to the APScheduler, plus **per-game dedicated threads** for game-start recovery:

| Thread | Source | What It Does | State It Touches |
|--------|--------|--------------|-----------------|
| **Pre-kickoff job** | APScheduler date trigger per game at `kickoff_time - pre_kickoff_minutes` | Cancel sells, re-create consolidated sell at buy price, cancel unfilled buy | `OrderTracker` (read+write), `ClobClientWrapper` (cancel + create), `GameLifecycle` (transition to PRE_KICKOFF) |
| **Game-start recovery thread** | APScheduler date trigger at kickoff time, launches dedicated `threading.Thread` per game | Detect cancellation, re-place sell, verify, retry loop | `OrderTracker` (read+write), `PositionTracker` (read), `ClobClientWrapper` (query + create), `GameLifecycle` (transition to GAME_STARTED, RECOVERY_COMPLETE) |

**Critical scenario:** Multiple games can kick off simultaneously (e.g., all Premier League 15:00 Saturday fixtures). This means multiple recovery threads running concurrently, each touching the same singleton state managers.

### Race Condition Inventory

#### Race 1: Check-then-act in duplicate prevention
**Location:** `OrderExecutionService.place_sell_order()` at `order_execution.py:191-196`
```
Thread A: has_sell_order(token_id) -> False
Thread B: has_sell_order(token_id) -> False
Thread A: record_sell(token_id, order_1)
Thread B: record_sell(token_id, order_2)  -- overwrites order_1, order_1 is now orphaned
```
**Risk in Epic 4:** Pre-kickoff handler and fill polling could both try to place sells for the same token. Game-start recovery threads for the same game could double-place.
**Severity:** HIGH -- results in orphaned orders on Polymarket with no in-memory tracking.

#### Race 2: Non-atomic cancel-then-replace in `update_sell_order()`
**Location:** `OrderExecutionService.update_sell_order()` at `order_execution.py:276-310`
```
Thread A: cancel_order(old_sell)
Thread A: remove_sell_order(token_id)
Thread B: has_sell_order(token_id) -> False (record was just removed)
Thread B: place_sell_order(token_id) -> places NEW sell
Thread A: create_sell_order(token_id) -> places ANOTHER sell
```
**Risk in Epic 4:** Fill polling runs `update_sell_order()` while pre-kickoff handler runs its own cancel-and-replace sequence.
**Severity:** HIGH -- same orphan risk, plus double sells on exchange.

#### Race 3: Read-modify-write in `PositionTracker.accumulate()`
**Location:** `position_tracker.py:22`
```python
self._fills[token_id] = self._fills.get(token_id, 0.0) + fill_size
```
**Risk in Epic 4:** Low in isolation (only fill polling writes), but if startup reconciliation (Epic 5) also writes, this becomes a race.
**Severity:** LOW for Epic 4 (single writer). MEDIUM for Epic 5.

#### Race 4: State machine transition check-then-act
**Location:** `GameLifecycle.transition()` at `game_lifecycle.py:54-68`
```
Thread A: reads self._state == SELL_PLACED, validates PRE_KICKOFF is allowed
Thread B: reads self._state == SELL_PLACED, validates PRE_KICKOFF is allowed
Thread A: self._state = PRE_KICKOFF
Thread B: self._state = PRE_KICKOFF  -- silent duplicate, or worse: Thread B sees SELL_PLACED but A already changed it
```
**Risk in Epic 4:** Pre-kickoff handler and fill polling both transitioning the same game.
**Severity:** MEDIUM -- the state machine validation becomes meaningless under concurrency; invalid transitions could silently succeed.

#### Race 5: `ClobClientWrapper` shared `_client` instance
**Location:** `clients/clob.py` -- all `@with_retry`-decorated methods
**Risk in Epic 4:** Multiple recovery threads + fill polling + daily fetch all calling the `py-clob-client` `ClobClient` concurrently. The `py-clob-client` library's thread-safety is undocumented.
**Severity:** UNKNOWN -- could cause cryptographic nonce collisions, auth failures, or data corruption in the HTTP session. Needs defensive locking.

### Thread-Safety Decision

**Decision:** Add `threading.Lock` to each state manager and `ClobClientWrapper`. Use per-instance locks, not a global lock, to minimize contention.

**Rationale:**
- The state managers are small, fast, in-memory dict operations. Lock contention will be negligible (microseconds per operation).
- Per-game recovery threads are I/O-bound (waiting on Polymarket API), not CPU-bound. Lock hold times are tiny relative to API call latency.
- A global lock would serialize all operations unnecessarily. Per-instance locks allow `OrderTracker` and `PositionTracker` to be accessed concurrently by different threads as long as they're operating on different managers.
- This is the simplest correct solution. More complex approaches (lock-free data structures, per-token locks) are over-engineered for ~40 games/week throughput.

### Locking Strategy Per Component

#### `OrderTracker` -- `threading.Lock`

Add a single `self._lock = threading.Lock()` in `__init__`. Wrap **every** public method in `with self._lock:`.

**Why a single lock (not separate locks for `_buy_orders` and `_sell_orders`):**
- Methods like `update_sell_order()` in `OrderExecutionService` do multi-step sequences across both dicts (read buy price, cancel sell, remove sell, create sell, record sell). A single lock per `OrderTracker` instance ensures these sequences are atomic from other threads' perspective.
- Two separate locks would invite deadlocks if a method needed both.

**Method-level locking plan:**

| Method | Lock Required | Notes |
|--------|:---:|-------|
| `record_buy()` | Yes | Dict write |
| `has_buy_order()` | Yes | Dict read (check-then-act pattern depends on this being consistent) |
| `get_buy_order()` | Yes | Dict read |
| `mark_inactive()` | Yes | Mutates `BuyOrderRecord.active` |
| `get_active_buy_orders()` | Yes | Returns list snapshot (must be consistent during iteration) |
| `has_sell_order()` | Yes | Dict read |
| `record_sell()` | Yes | Dict write |
| `get_sell_order()` | Yes | Dict read |
| `remove_sell_order()` | Yes | Dict write |
| `get_order()` | Yes | Delegates to `get_buy_order()` (but external callers might combine with other calls) |

**Critical pattern for Epic 4:** The caller-side check-then-act (e.g., `has_sell_order()` then `record_sell()`) is NOT atomic even with per-method locking. The `OrderExecutionService` must hold the lock across the full check-place-record sequence. This requires exposing the lock or providing an atomic `place_sell_if_absent()` method.

**Recommended approach:** Add a context manager or atomic methods to `OrderTracker`:

```python
def record_sell_if_absent(self, token_id, order_id, sell_price, sell_size) -> bool:
    """Atomically check for existing sell and record if absent. Returns True if recorded."""
    with self._lock:
        if token_id in self._sell_orders:
            return False
        self._sell_orders[token_id] = SellOrderRecord(...)
        return True
```

This eliminates Race 1 at the state manager level. The API call (`create_sell_order`) still happens outside the lock (we don't want to hold locks during I/O), but the in-memory state change is atomic.

#### `PositionTracker` -- `threading.Lock`

Add `self._lock = threading.Lock()` in `__init__`. Wrap all public methods.

| Method | Lock Required | Notes |
|--------|:---:|-------|
| `accumulate()` | Yes | Read-modify-write |
| `get_accumulated_fills()` | Yes | Dict read |
| `has_reached_threshold()` | Yes | Dict read |

Simple and sufficient. Single writer (fill polling) today, but locking now prevents future surprises.

#### `MarketRegistry` -- `threading.Lock`

Add `self._lock = threading.Lock()` in `__init__`. Wrap all public methods.

| Method | Lock Required | Notes |
|--------|:---:|-------|
| `register()` | Yes | Dict write + GameLifecycle creation |
| `get()` | Yes | Dict read |
| `is_processed()` | Yes | Dict read |
| `all_markets()` | Yes | Returns list snapshot -- must copy under lock |

**Important:** `all_markets()` currently returns `list(self._markets.values())`. This creates a snapshot of `MarketEntry` references. The entries themselves (especially `entry.lifecycle`) remain shared and mutable. This is fine -- the lock on `MarketRegistry` protects the dict structure, and `GameLifecycle` has its own lock.

#### `GameLifecycle` -- `threading.Lock`

Add `self._lock = threading.Lock()` in `__init__`. Wrap `transition()` and the `state` property.

```python
def transition(self, new_state: GameState) -> None:
    with self._lock:
        allowed = VALID_TRANSITIONS.get(self._state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(...)
        logger.info(...)
        self._state = new_state
```

This makes the validate-then-mutate sequence atomic, eliminating Race 4.

#### `ClobClientWrapper` -- `threading.Lock`

Add `self._lock = threading.Lock()` in `__init__`. Wrap every method that calls `self._client`.

**Why:** The `py-clob-client` `ClobClient` manages an HTTP session and performs cryptographic signing (ECDSA with nonce). Concurrent calls could corrupt the session state or reuse nonces. Since we cannot verify the library's thread-safety, defensive locking is the correct approach.

**Performance impact:** Minimal. Each CLOB API call takes 100-500ms of network I/O. Lock acquisition adds microseconds. The bottleneck is the API, not the lock.

**Alternative considered:** One `ClobClient` instance per thread. Rejected because:
- Requires multiple L2 auth initializations (wasteful)
- Harder to manage tick-size cache consistency
- Adds complexity for negligible benefit at ~40 games/week throughput

### Implementation Plan for Thread-Safety

**When to implement:** Story 4.1 (first story that adds concurrency via date triggers). The locking should be added as the first AC of Story 4.1, before any per-game scheduling logic.

**Scope:** Add locks to `OrderTracker`, `PositionTracker`, `MarketRegistry`, `GameLifecycle`, and `ClobClientWrapper`. Add atomic check-and-act methods to `OrderTracker` (`record_sell_if_absent`, `cancel_and_replace_sell`).

**Testing:** Add thread-safety unit tests using `concurrent.futures.ThreadPoolExecutor` to verify no data corruption under concurrent access. Target: 2 threads, 100 iterations per test, assert no duplicate records and no lost updates.

---

## Part 2: Sell Price Override Design Decision

### Context

Currently in Epic 3, sell orders are placed at `buy_price + spread` (via `BuyOrderRecord.sell_price`):
- `order_execution.py:208` -- `sell_price = min(buy_record.sell_price, 0.99)`
- `BuyOrderRecord.sell_price` is set at buy time as `buy_price + config.btts.price_diff`

Epic 4 requires sells at the **buy price** (not buy_price + spread) in two contexts:
1. **Story 4.1 (Pre-kickoff consolidation):** FR17 says "re-create a single consolidated sell order at the buy price"
2. **Story 4.2 (Game-start recovery):** FR20 says "re-place sell orders for all filled buy positions at the buy price"

The rationale: before and during kickoff, the priority shifts from profit (spread capture) to safety (ensuring position is covered). Selling at buy_price maximizes fill probability in the critical window.

### Options Evaluated

#### Option A: Price parameter on `place_sell_order()`

Add an optional `override_price: float | None = None` parameter to `place_sell_order()`. If provided, use it instead of `buy_record.sell_price`.

```python
def place_sell_order(self, token_id: str, override_price: float | None = None) -> bool:
    ...
    sell_price = override_price if override_price is not None else min(buy_record.sell_price, 0.99)
    ...
```

**Pros:**
- Minimal code change (one parameter, one conditional)
- Single method, single code path for sell placement logic
- Duplicate prevention, logging, OrderTracker recording all reused

**Cons:**
- Caller must know to pass the price -- easy to forget
- Method signature grows; less clear what `override_price` means without reading docs

#### Option B: New method `place_emergency_sell()`

Create a dedicated method for the kickoff-window use case:

```python
def place_emergency_sell(self, token_id: str) -> bool:
    """Place sell at buy_price for pre-kickoff/game-start recovery."""
    ...
    sell_price = min(buy_record.buy_price, 0.99)
    ...
```

**Pros:**
- Intent is explicit in the method name
- No risk of callers forgetting the price parameter
- Can have different logging (e.g., "emergency sell" vs regular sell)

**Cons:**
- Code duplication -- 80% of the logic (duplicate check, API call, OrderTracker recording, lifecycle transition) is identical to `place_sell_order()`
- Two places to maintain when the sell placement flow changes
- Violates DRY -- the retro explicitly praised "extend, don't recreate"

#### Option C: Price parameter on `place_sell_order()` + `update_sell_order()` with shared internal method

Refactor both methods to delegate to a private `_execute_sell()` that takes an explicit price. Public methods determine the price, then call the shared implementation.

```python
def place_sell_order(self, token_id: str, override_price: float | None = None) -> bool:
    ...
    sell_price = override_price if override_price is not None else min(buy_record.sell_price, 0.99)
    return self._execute_sell(token_id, sell_price, buy_record)

def update_sell_order(self, token_id: str, override_price: float | None = None) -> bool:
    ...
    sell_price = override_price if override_price is not None else existing_record.sell_price
    # cancel existing, then:
    return self._execute_sell(token_id, sell_price, buy_record)

def _execute_sell(self, token_id, sell_price, buy_record) -> bool:
    """Shared sell placement logic."""
    ...
```

**Pros:**
- Clean separation: public methods handle price selection, private method handles execution
- Both `place_sell_order()` and `update_sell_order()` benefit from `override_price`
- Pre-kickoff consolidation needs `update_sell_order(token_id, override_price=buy_price)` -- this fits naturally
- Aligns with "extend, don't recreate"

**Cons:**
- More refactoring than Option A (but the refactoring improves code quality)

### Decision: Option C -- Price parameter + shared internal method

**Rationale:**
1. Epic 4 Story 4.1 pre-kickoff handler needs to cancel and re-place sells at buy price -- this is exactly what `update_sell_order(token_id, override_price=buy_record.buy_price)` does.
2. Epic 4 Story 4.2 game-start recovery needs to place a fresh sell at buy price -- this is `place_sell_order(token_id, override_price=buy_record.buy_price)`.
3. The shared `_execute_sell()` method eliminates duplication between `place_sell_order()` and `update_sell_order()` and becomes the single place to add thread-safe locking for sell placement.
4. The existing fill polling code (`_check_and_trigger_sell()`) calls `place_sell_order()` and `update_sell_order()` without `override_price`, so it continues to use the spread-based price -- no behavior change for Epic 3 code.

### Sell Price Summary

| Context | Method | Price Used |
|---------|--------|-----------|
| Normal fill threshold (Epic 3) | `place_sell_order(token_id)` | `buy_price + spread` (from `BuyOrderRecord.sell_price`) |
| Normal fill update (Epic 3) | `update_sell_order(token_id)` | Same as existing sell price |
| Pre-kickoff consolidation (Story 4.1) | `update_sell_order(token_id, override_price=buy_record.buy_price)` | `buy_price` |
| Game-start recovery (Story 4.2) | `place_sell_order(token_id, override_price=buy_record.buy_price)` | `buy_price` |
| Post-game-start retry (Story 4.3) | `place_sell_order(token_id, override_price=buy_record.buy_price)` | `buy_price` |

### Implementation Plan for Sell Price Override

**When to implement:** Story 4.1 (first story that needs buy-price sells). The refactoring of `place_sell_order()` and `update_sell_order()` to use a shared `_execute_sell()` should happen at the start of Story 4.1, before adding pre-kickoff logic.

**Backward compatibility:** Full. Existing callers pass no `override_price`, so they get the same spread-based behavior. No changes needed in `FillPollingService._check_and_trigger_sell()`.

---

## Part 3: Architecture Document Update Requirements

The following updates to `architecture.md` are implied by these decisions but should **not** be applied now. They should be applied when Story 4.1 is created, to keep the architecture document synchronized with the implementation:

1. **Threading model section** -- add note that state managers and `ClobClientWrapper` use `threading.Lock` for thread safety
2. **Process patterns section** -- add "Thread-Safe State Access" pattern documenting the locking strategy
3. **Anti-patterns section** -- add "Accessing state managers without holding the lock" and "Holding a lock during API calls"
4. **Component listing** -- note that `OrderTracker` provides atomic `record_sell_if_absent()` method

---

## Preparation Checklist

| # | Task | Status | Decision |
|---|------|--------|----------|
| 1 | Thread-safety analysis of all state managers | Done | Add `threading.Lock` to `OrderTracker`, `PositionTracker`, `MarketRegistry`, `GameLifecycle`, `ClobClientWrapper`. Add atomic check-and-act methods. Implement in Story 4.1. |
| 2 | Sell price override design decision | Done | Option C: `override_price` parameter on `place_sell_order()` + `update_sell_order()`, shared `_execute_sell()` internal method. Implement in Story 4.1. |

**Assessment:** Epic 4 is ready to begin story creation. No architectural replan is required. Both preparation decisions inform *how* the stories are implemented, not *what* they implement.
