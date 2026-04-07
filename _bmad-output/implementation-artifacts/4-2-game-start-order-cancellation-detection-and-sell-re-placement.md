# Story 4.2: Game-Start Order Cancellation Detection and Sell Re-Placement

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to detect when Polymarket cancels all orders at game start and immediately re-place my sell orders,
so that I never have an unmanaged position -- the most critical safety requirement.

## Acceptance Criteria

1. **Given** a game with a known kickoff time and a filled position
   **When** the current time reaches the kickoff time
   **Then** an APScheduler date trigger fires and launches a dedicated thread for game-start recovery

2. **Given** the game-start recovery thread starts
   **When** it queries the CLOB API for the sell order status
   **Then** it detects that Polymarket has automatically cancelled the sell order
   **And** immediately places a new sell order at the buy price for the full position size
   **And** updates OrderTracker with the new sell order ID
   **And** the game transitions to GAME_STARTED via GameLifecycle
   **And** an INFO log is emitted: `[Home vs Away] Game-start recovery: sell re-placed at buy_price=..., size=...`

3. **Given** the game has no filled position (buy expired or was fully cancelled pre-kickoff)
   **When** game-start recovery runs
   **Then** it detects no position to protect
   **And** the game transitions to DONE state
   **And** an INFO log is emitted: `[Home vs Away] No position at game start -- nothing to recover`

4. **Given** multiple games kick off simultaneously
   **When** game-start triggers fire for each
   **Then** each game gets its own dedicated thread for recovery
   **And** recoveries proceed concurrently without blocking each other or the main loop

## Tasks / Subtasks

- [x] Task 1: Add thread-safety locks to all state managers and ClobClientWrapper (AC: #4)
  - [x] Add `threading.Lock` to `OrderTracker.__init__`, wrap every public method with `with self._lock:`
  - [x] Add `threading.Lock` to `PositionTracker.__init__`, wrap every public method
  - [x] Add `threading.Lock` to `MarketRegistry.__init__`, wrap every public method; `all_markets()` must copy under lock
  - [x] Add `threading.Lock` to `GameLifecycle.__init__`, wrap `transition()` and `state` property
  - [x] Add `threading.Lock` to `ClobClientWrapper.__init__`, wrap every `@with_retry` method and `get_tick_size()`
  - [x] Add `record_sell_if_absent(token_id, order_id, sell_price, sell_size) -> bool` atomic method to `OrderTracker`

- [x] Task 2: Create `GameStartService` in `btts_bot/core/game_start.py` (AC: #1-#4)
  - [x] Constructor dependencies: `clob_client`, `order_tracker`, `position_tracker`, `market_registry`
  - [x] Implement `handle_game_start(token_id: str) -> None` -- main handler launched in a dedicated thread
  - [x] Handle PRE_KICKOFF state (normal path): query sell order status, detect cancellation, re-place sell at buy_price, transition to GAME_STARTED (AC #2)
  - [x] Handle SELL_PLACED / FILLING / BUY_PLACED states (pre-kickoff failed path): same recovery logic but transition from those states to GAME_STARTED (AC #2)
  - [x] Handle no-position scenario: 0 accumulated fills -> transition to DONE (AC #3)
  - [x] Handle GAME_STARTED / RECOVERY_COMPLETE / DONE / SKIPPED / EXPIRED states: skip (already handled)
  - [x] Handle DISCOVERED / ANALYSED states: no position, skip

- [x] Task 3: Add game-start transitions to `VALID_TRANSITIONS` in `game_lifecycle.py` (AC: #2)
  - [x] Add `GAME_STARTED` to `SELL_PLACED` valid transitions (pre-kickoff failed, Polymarket cancelled at game start)
  - [x] Add `GAME_STARTED` to `FILLING` valid transitions (pre-kickoff failed)
  - [x] Add `GAME_STARTED` to `BUY_PLACED` valid transitions (pre-kickoff failed)

- [x] Task 4: Add game-start scheduling to `SchedulerService` in `scheduling.py` (AC: #1)
  - [x] Add `game_start_service: GameStartService` as constructor dependency
  - [x] Implement `schedule_game_start(token_id: str, kickoff_time: datetime) -> None`
  - [x] Create APScheduler `DateTrigger` for exactly `kickoff_time`
  - [x] Job ID format: `game_start_{token_id}` for idempotent scheduling
  - [x] Skip scheduling if kickoff time is already in the past (log WARNING)
  - [x] The APScheduler job callback must launch `handle_game_start` in a dedicated `threading.Thread` per game (AC #4)

- [x] Task 5: Wire game-start scheduling into buy order placement flow (AC: #1)
  - [x] After successful buy order placement in `OrderExecutionService.place_buy_order()`, call `scheduler_service.schedule_game_start(token_id, kickoff_time)` alongside existing `schedule_pre_kickoff()` call
  - [x] This ensures every game with a buy order gets both a pre-kickoff trigger and a game-start trigger

- [x] Task 6: Update `main.py` wiring (AC: #1-#4)
  - [x] Create `GameStartService` with `clob_client, order_tracker, position_tracker, market_registry`
  - [x] Update `SchedulerService` constructor call to include `game_start_service`
  - [x] Keep existing dependency order: state managers -> clients -> core services -> scheduler -> order execution -> fill polling

- [x] Task 7: Write tests for `GameStartService` in `tests/test_game_start.py` (AC: #2-#3)
  - [x] Test: PRE_KICKOFF state + sell order exists -- detect cancellation (get_order returns CANCELED), re-place sell at buy_price, transition to GAME_STARTED
  - [x] Test: PRE_KICKOFF state + sell order exists and still active -- re-place anyway (Polymarket may cancel milliseconds later)
  - [x] Test: PRE_KICKOFF state + no accumulated fills -- transition to DONE (AC #3)
  - [x] Test: SELL_PLACED state (pre-kickoff failed) -- recovery detects old sell was cancelled, re-places at buy_price, transitions to GAME_STARTED
  - [x] Test: FILLING state (pre-kickoff failed) -- recovery detects position needs sell, places sell at buy_price, transitions to GAME_STARTED
  - [x] Test: BUY_PLACED state (pre-kickoff failed, no fills) -- cancel buy if active, transition to DONE
  - [x] Test: BUY_PLACED state (pre-kickoff failed, race condition fills > 0) -- cancel buy, place sell at buy_price, transition to GAME_STARTED
  - [x] Test: create_sell_order returns None -- logs ERROR, does NOT crash (recovery thread must not die)
  - [x] Test: game already in GAME_STARTED or later -- skip (idempotent)
  - [x] Test: game in DISCOVERED/ANALYSED -- skip (no position)

- [x] Task 8: Write thread-safety tests (AC: #4)
  - [x] Test: concurrent `record_sell` + `has_sell_order` on OrderTracker -- no data corruption
  - [x] Test: concurrent `transition()` on GameLifecycle -- no invalid state
  - [x] Test: concurrent `accumulate()` on PositionTracker -- no lost updates
  - [x] Test: `record_sell_if_absent()` atomicity -- two threads, one wins, one returns False

- [x] Task 9: Write tests for scheduling in `tests/test_scheduling.py` (AC: #1)
  - [x] Test: `schedule_game_start` adds DateTrigger job with correct `run_date` = kickoff_time
  - [x] Test: kickoff time in the past -- job not added, WARNING logged
  - [x] Test: duplicate scheduling (same token_id) -- `replace_existing=True` handles it
  - [x] Test: job callback spawns a `threading.Thread` (mock Thread and verify start() called)

- [x] Task 10: Update existing tests for modified constructors
  - [x] Update `tests/test_scheduling.py` for new `game_start_service` constructor parameter
  - [x] Update `tests/test_order_execution.py` for new `schedule_game_start` call after buy placement
  - [x] Update `tests/test_main.py` for new `GameStartService` wiring

- [x] Task 11: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` -- zero issues
  - [x] `uv run ruff format btts_bot/ tests/` -- no changes needed
  - [x] All existing tests still pass (no regressions)

## Dev Notes

### Critical Context: Thread-Safety -- The #1 Priority of This Story

The Epic 4 preparation document (`epic-4-preparation-2026-04-05.md`) mandated adding `threading.Lock` to all state managers and `ClobClientWrapper` before adding per-game recovery threads. **Story 4.1 explicitly deferred this** with the note: "Do NOT add locks in Story 4.1... Story 4.2 should evaluate adding locks if dedicated recovery threads increase concurrency."

Story 4.2 adds dedicated `threading.Thread` per game for game-start recovery. Multiple games can kick off simultaneously (e.g., all Premier League 15:00 Saturday fixtures). This makes thread-safety mandatory.

**Task 1 (thread-safety locks) MUST be completed before Task 2 (GameStartService).** The locking must be in place before any code spawns dedicated threads.

### Locking Implementation Details

Follow the locking strategy from `epic-4-preparation-2026-04-05.md` exactly:

**OrderTracker** -- single `self._lock = threading.Lock()`:
```python
import threading

class OrderTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buy_orders: dict[str, BuyOrderRecord] = {}
        self._sell_orders: dict[str, SellOrderRecord] = {}

    def has_sell_order(self, token_id: str) -> bool:
        with self._lock:
            return token_id in self._sell_orders

    # ... same pattern for ALL public methods

    def record_sell_if_absent(
        self, token_id: str, order_id: str, sell_price: float, sell_size: float
    ) -> bool:
        """Atomically check for existing sell and record if absent. Returns True if recorded."""
        with self._lock:
            if token_id in self._sell_orders:
                return False
            self._sell_orders[token_id] = SellOrderRecord(
                token_id=token_id, order_id=order_id,
                sell_price=sell_price, sell_size=sell_size,
            )
            return True
```

**PositionTracker** -- single `self._lock = threading.Lock()`:
Wrap `accumulate()`, `get_accumulated_fills()`, `has_reached_threshold()`.

**MarketRegistry** -- single `self._lock = threading.Lock()`:
Wrap `register()`, `get()`, `is_processed()`, `all_markets()`. Note: `all_markets()` must return a copy under lock.

**GameLifecycle** -- single `self._lock = threading.Lock()`:
```python
class GameLifecycle:
    def __init__(self, token_id: str) -> None:
        self.token_id = token_id
        self._state = GameState.DISCOVERED
        self._lock = threading.Lock()

    @property
    def state(self) -> GameState:
        with self._lock:
            return self._state

    def transition(self, new_state: GameState) -> None:
        with self._lock:
            # existing validation + mutation logic
```

**ClobClientWrapper** -- single `self._lock = threading.Lock()`:
Wrap every method that calls `self._client`. The `py-clob-client` library's thread-safety is undocumented. Defensive locking prevents nonce collisions and session corruption.

```python
class ClobClientWrapper:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # ... existing init ...

    def get_tick_size(self, token_id: str) -> str:
        with self._lock:
            return self._client.get_tick_size(token_id)

    @with_retry
    def get_order(self, order_id: str):
        with self._lock:
            return self._client.get_order(order_id)
    # ... same for all @with_retry methods
```

**IMPORTANT:** The `@with_retry` decorator wraps the entire method including retries. The lock is held per-attempt inside the method body, NOT across all retry attempts. The lock protects `self._client` access. The retry decorator handles transient errors at a higher level. This means the lock annotation goes INSIDE the method body (wrapping `self._client` calls), NOT around the `@with_retry` decorator.

Correct pattern:
```python
@with_retry
def get_order(self, order_id: str):
    with self._lock:
        return self._client.get_order(order_id)
```

This ensures:
- Lock is held only during the actual API call (microseconds of setup + I/O wait)
- Lock is released between retry attempts
- Other threads can make CLOB calls between retries

### Critical Context: GameStartService Handler Logic

The handler must be robust to all possible game states when the trigger fires. Key insight: **Polymarket automatically cancels ALL open orders at game start** -- this is not optional or conditional. If we had a sell order live, it is now cancelled.

**PRE_KICKOFF (normal path -- pre-kickoff succeeded):**
1. Get `buy_record` from `OrderTracker` for `buy_price`
2. Get `accumulated_fills` from `PositionTracker` for sell size
3. If `accumulated_fills <= 0.0`: no position, transition to `DONE`, return
4. Remove old sell record from `OrderTracker` (Polymarket already cancelled it)
5. Place new sell at `min(buy_price, 0.99)` for `accumulated_fills` via `clob_client.create_sell_order()`
6. If sell placement fails: log ERROR, do NOT transition (Story 4.3 retry loop will handle)
7. Use `record_sell_if_absent()` for atomic recording (avoid race with other threads)
8. Transition to `GAME_STARTED`
9. Log: `[Home vs Away] Game-start recovery: sell re-placed at buy_price=..., size=...`

**SELL_PLACED (pre-kickoff failed -- sell was live but pre-kickoff didn't consolidate):**
1. Same as PRE_KICKOFF path -- the old sell was cancelled by Polymarket at game start
2. Remove old sell record, place new sell at `buy_price`, record, transition to `GAME_STARTED`

**FILLING (pre-kickoff failed -- had fills but no sell placed yet):**
1. Get `buy_price` from `BuyOrderRecord`
2. Get `accumulated_fills` from `PositionTracker`
3. If `accumulated_fills <= 0.0`: transition to `DONE`, return
4. Cancel active buy (Polymarket may have already cancelled it -- handle gracefully)
5. Mark buy as inactive
6. Place sell at `min(buy_price, 0.99)` for `accumulated_fills`
7. Record sell, transition to `GAME_STARTED`

**BUY_PLACED (pre-kickoff failed -- buy may still be active/partially filled):**
1. Mark buy as inactive (Polymarket already cancelled it at game start)
2. Get `accumulated_fills` from `PositionTracker`
3. If `accumulated_fills <= 0.0`: transition to `DONE`, return (no position)
4. If fills > 0: place sell at `buy_price`, record, transition to `GAME_STARTED`

**DISCOVERED / ANALYSED:** No position. Skip with DEBUG log.

**GAME_STARTED / RECOVERY_COMPLETE / DONE / SKIPPED / EXPIRED:** Already handled or terminal. Skip with DEBUG log.

### Critical Context: Dedicated Thread Pattern for Recovery

The APScheduler `DateTrigger` fires the callback in APScheduler's thread pool. To ensure recoveries proceed concurrently without blocking the scheduler thread pool (which would prevent other scheduled jobs from running), each game-start handler must spawn a **dedicated `threading.Thread`**:

```python
import threading

def schedule_game_start(self, token_id: str, kickoff_time: datetime) -> None:
    if kickoff_time <= datetime.now(timezone.utc):
        logger.warning(
            "Game-start trigger for token=%s is in the past (kickoff=%s), skipping",
            token_id, kickoff_time.isoformat(),
        )
        return

    self._scheduler.add_job(
        func=self._launch_game_start_thread,
        trigger=DateTrigger(run_date=kickoff_time),
        args=[token_id],
        id=f"game_start_{token_id}",
        name=f"Game-start: {token_id}",
        replace_existing=True,
        misfire_grace_time=300,  # 5 min grace
    )

def _launch_game_start_thread(self, token_id: str) -> None:
    """APScheduler callback: spawn a dedicated thread for game-start recovery."""
    thread = threading.Thread(
        target=self._game_start_service.handle_game_start,
        args=(token_id,),
        name=f"game_start_{token_id}",
        daemon=True,  # Don't block shutdown
    )
    thread.start()
    logger.info("Game-start recovery thread launched for token=%s", token_id)
```

**Why `daemon=True`:** The bot shutdown (`scheduler_service.shutdown()` + `sys.exit`) should not wait indefinitely for recovery threads. If the bot is shutting down, recovery threads should terminate. On the next restart, startup reconciliation (Story 5.1) will handle any orphaned positions.

### Critical Context: Sell Price -- buy_price, NOT Spread Price

Same as Story 4.1: game-start recovery sells at `buy_price` (breakeven), NOT at `buy_price + price_diff` (spread price). Maximize fill probability in the critical window.

```python
buy_record = order_tracker.get_buy_order(token_id)
sell_price = min(buy_record.buy_price, 0.99)  # NOT buy_record.sell_price
```

### Critical Context: Why NOT Query Sell Order Status First

The epics acceptance criteria say "queries the CLOB API for the sell order status" then "detects that Polymarket has automatically cancelled the sell order." In practice, this extra API call is **unnecessary and wasteful**:

1. Polymarket **always** cancels all open orders at game start. This is not conditional.
2. Querying the order status adds latency (100-500ms) to a time-critical recovery path (NFR4: 5-minute window).
3. The pre-kickoff sell's order ID may not even be in our `OrderTracker` if pre-kickoff failed.

**Recommended approach:** Skip the status query. Unconditionally:
- Remove old sell record from `OrderTracker` (if any)
- Place new sell at buy_price
- Record new sell in `OrderTracker`

This is both simpler and faster. The acceptance criteria's intent is "detect that we need to re-place" -- which we know unconditionally at game start.

**However**, if the developer prefers to follow the AC literally, a brief `get_order()` check is acceptable -- just don't gate the recovery on it. Even if `get_order()` fails, proceed with re-placement.

### Critical Context: Error Handling in Recovery Thread

The recovery thread MUST NOT crash with an unhandled exception. If the `handle_game_start()` method raises, the thread dies silently and the position is left unmanaged.

**Wrap the entire handler in a try/except:**
```python
def handle_game_start(self, token_id: str) -> None:
    try:
        self._do_game_start_recovery(token_id)
    except Exception:
        logger.exception(
            "Game-start recovery FAILED for token=%s — position may be unmanaged",
            token_id,
        )
```

Story 4.3 adds the verification + retry loop that catches failed recoveries. But the handler itself must never crash.

### Critical Context: SchedulerService Dependency Changes

The current `SchedulerService` constructor takes `daily_fetch_hour_utc`, `discovery_service`, `pre_kickoff_service`, `timing_config`. Story 4.2 adds `game_start_service`:

```python
class SchedulerService:
    def __init__(
        self,
        daily_fetch_hour_utc: int,
        discovery_service: MarketDiscoveryService,
        pre_kickoff_service: PreKickoffService,
        game_start_service: GameStartService,  # NEW
        timing_config: TimingConfig,
    ) -> None:
```

**Ripple effect:** `main.py` must update the `SchedulerService(...)` constructor call. All existing tests in `tests/test_scheduling.py` must update constructor calls to include the new parameter.

### Critical Context: OrderExecutionService -- Register Both Triggers

After a successful buy order placement, `OrderExecutionService.place_buy_order()` currently calls `schedule_pre_kickoff()`. Story 4.2 adds a second call:

```python
# Register pre-kickoff trigger for this game
if self._scheduler_service is not None:
    self._scheduler_service.schedule_pre_kickoff(token_id, entry.kickoff_time)
    self._scheduler_service.schedule_game_start(token_id, entry.kickoff_time)  # NEW
```

No change to `OrderExecutionService`'s constructor -- it already has `scheduler_service`.

### Lifecycle Transitions

Transitions used by this story:

**New transitions to add:**
- `SELL_PLACED -> GAME_STARTED` -- Polymarket cancelled sell at game start when pre-kickoff failed
- `FILLING -> GAME_STARTED` -- pre-kickoff failed, game started with fills but no sell
- `BUY_PLACED -> GAME_STARTED` -- pre-kickoff failed, game started with unfilled/partially-filled buy

**Existing transitions used:**
- `PRE_KICKOFF -> GAME_STARTED` -- normal path after successful pre-kickoff consolidation
- `PRE_KICKOFF -> DONE` -- no position at game start (0 fills)
- `SELL_PLACED -> DONE` -- no position scenario (edge case)
- `FILLING -> DONE` -- no fills scenario (edge case)
- `BUY_PLACED -> DONE` -- buy cancelled with no fills (this transition doesn't exist yet -- but BUY_PLACED -> PRE_KICKOFF -> DONE covers it via pre-kickoff. For game-start, we need `BUY_PLACED -> DONE` directly)

**REQUIRED ADDITIONS to VALID_TRANSITIONS in `game_lifecycle.py`:**
```python
GameState.BUY_PLACED: frozenset({
    GameState.FILLING, GameState.SKIPPED, GameState.EXPIRED,
    GameState.PRE_KICKOFF, GameState.GAME_STARTED, GameState.DONE,  # DONE + GAME_STARTED new
}),
GameState.FILLING: frozenset({
    GameState.SELL_PLACED, GameState.PRE_KICKOFF, GameState.EXPIRED,
    GameState.GAME_STARTED, GameState.DONE,  # GAME_STARTED + DONE new
}),
GameState.SELL_PLACED: frozenset({
    GameState.PRE_KICKOFF, GameState.DONE,
    GameState.GAME_STARTED,  # GAME_STARTED new
}),
```

### File Locations

**Files to create:**
- `btts_bot/core/game_start.py` -- NEW: `GameStartService` class
- `tests/test_game_start.py` -- NEW: tests for `GameStartService`
- `tests/test_thread_safety.py` -- NEW: thread-safety tests for state managers

**Files to modify:**
- `btts_bot/state/order_tracker.py` -- ADD: `threading.Lock`, `record_sell_if_absent()`, lock all public methods
- `btts_bot/state/position_tracker.py` -- ADD: `threading.Lock`, lock all public methods
- `btts_bot/state/market_registry.py` -- ADD: `threading.Lock`, lock all public methods
- `btts_bot/core/game_lifecycle.py` -- ADD: `threading.Lock` to `GameLifecycle`, lock `transition()` and `state`; ADD: new transitions (SELL_PLACED/FILLING/BUY_PLACED -> GAME_STARTED, BUY_PLACED/FILLING -> DONE)
- `btts_bot/clients/clob.py` -- ADD: `threading.Lock`, lock all methods calling `self._client`
- `btts_bot/core/scheduling.py` -- ADD: `game_start_service` dependency, `schedule_game_start()` method, `_launch_game_start_thread()` helper
- `btts_bot/core/order_execution.py` -- ADD: `schedule_game_start()` call after successful buy placement
- `btts_bot/main.py` -- MODIFY: wiring for `GameStartService`, updated `SchedulerService` constructor
- `tests/test_scheduling.py` -- MODIFY: update constructor calls, add `schedule_game_start` tests
- `tests/test_order_execution.py` -- MODIFY: add `schedule_game_start` call verification after buy placement
- `tests/test_main.py` -- MODIFY: add `GameStartService` mock + wiring tests

**Files NOT to touch:**
- `btts_bot/core/pre_kickoff.py` -- unchanged, already works correctly
- `btts_bot/core/fill_polling.py` -- unchanged; fill polling's state filter (`BUY_PLACED`, `FILLING`, `SELL_PLACED`) means once a game transitions to `GAME_STARTED`, polling stops for that game automatically
- `btts_bot/config.py` -- no new config fields needed (game-start fires at exact kickoff time, no configurable offset)
- `btts_bot/retry.py` -- unchanged
- `btts_bot/logging_setup.py` -- unchanged
- `btts_bot/clients/gamma.py` -- not involved
- `btts_bot/clients/data_api.py` -- not involved
- `btts_bot/core/market_discovery.py` -- unchanged
- `btts_bot/core/liquidity.py` -- unchanged
- `btts_bot/core/reconciliation.py` -- stub for Story 5.1

### Previous Story Intelligence (4.1)

From Story 4.1 completion notes:
- 328 tests pass (app tests), ruff check and format clean
- `PreKickoffService` is the pattern to follow for `GameStartService` (same constructor deps, same state-dispatch pattern)
- Pre-kickoff handler intentionally leaves games in non-terminal states on failure "for game-start recovery" -- Story 4.2 IS that recovery
- Pre-kickoff uses `buy_record.buy_price` (not `sell_price`) with 0.99 cap -- game-start recovery uses the same pricing
- `_cancel_buy_if_active()` helper pattern in `PreKickoffService` is a good template for the game-start handler's buy cleanup
- `_TERMINAL_STATES` frozenset pattern for early-return is reusable
- `record_sell()` currently records sell price and size -- game-start recovery should use the same method (or the new `record_sell_if_absent()` for thread safety)
- `mark_inactive()` on buy order already exists -- game-start handler should mark buy inactive since Polymarket cancelled it
- `remove_sell_order()` already exists -- use to clear stale sell records before re-placing

### Epic 4 Preparation Intelligence

From `epic-4-preparation-2026-04-05.md`:

**Thread-safety decision:** Add `threading.Lock` to each state manager and `ClobClientWrapper`. Use per-instance locks, not a global lock. This is the simplest correct solution for ~40 games/week throughput.

**Race condition #1 (most critical):** Check-then-act in duplicate prevention. Two threads reading `has_sell_order() == False` simultaneously, then both calling `record_sell()` -- one overwrites the other. Solution: `record_sell_if_absent()` atomic method.

**Race condition #2:** Non-atomic cancel-then-replace in `update_sell_order()`. One thread cancels and removes sell record, another thread reads `has_sell_order() == False` and places a new sell concurrently. For Story 4.2, `GameStartService` should use `record_sell_if_absent()` and handle the `False` return (meaning another thread already placed a sell -- that's fine, recovery is done).

**Sell price override decision (Option C):** `override_price` parameter on `place_sell_order()` + `update_sell_order()` with shared `_execute_sell()`. However, Story 4.1 did NOT implement this refactoring -- it created `PreKickoffService` with direct `clob_client.create_sell_order()` calls instead. **Story 4.2 should follow the same pattern as Story 4.1** and call `clob_client.create_sell_order()` directly from `GameStartService`, NOT go through `OrderExecutionService.place_sell_order()`. The reasoning:
1. Consistency with the pattern established in Story 4.1
2. `place_sell_order()` has lifecycle transition logic (`FILLING -> SELL_PLACED`) that doesn't apply at game-start
3. `place_sell_order()` uses `buy_record.sell_price` (spread price), not `buy_price`
4. Direct CLOB calls from `core/` modules via DI are architecturally valid

### Git Intelligence

Last 5 commits:
```
5d88a3c 4-1-pre-kickoff-sell-consolidation-and-buy-cancellation
749e7d4 3-3-automatic-sell-order-placement-on-fill-threshold
3f35e45 3-2-fill-accumulation-tracking-via-polling
0b19fd7 3-1-buy-order-placement-with-duplicate-prevention
2d148ff epic-2-retro
```

Consistent commit message format: story key only as commit message.

### Architecture Constraints to Enforce

- `core/` modules contain business logic -- receive client instances via DI, never import `requests` or `py-clob-client` directly. Import `ClobClientWrapper` at module level (matching `pre_kickoff.py`, `order_execution.py`, `liquidity.py` pattern).
- `state/` modules are pure data managers -- hold state and answer queries, NEVER initiate API calls or schedule jobs
- `clients/` modules are thin I/O wrappers -- only place that imports `py-clob-client`/`requests`
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` -- never set `_state` directly
- `@with_retry` on all API calls in `clients/` -- no bare API calls in business logic
- Check `OrderTracker` state before every order operation (duplicate prevention pattern)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries -- caller must handle gracefully
- `threading.Lock` on all state managers and `ClobClientWrapper` (NEW for this story)

### Architecture Anti-Patterns to Avoid

- Do NOT hold locks during API calls. Lock protects in-memory state; release before I/O. Exception: `ClobClientWrapper` lock protects `self._client` during the call itself (as the client is not thread-safe).
- Do NOT reuse `OrderExecutionService.place_sell_order()` for game-start sells -- follow Story 4.1 pattern of direct `clob_client.create_sell_order()` calls
- Do NOT add API call logic to `OrderTracker` or `PositionTracker` -- they are pure data managers in `state/`
- Do NOT import `py_clob_client` anywhere except `clients/clob.py`
- Do NOT crash on API errors -- log and continue. Recovery thread must survive all exceptions.
- Do NOT use `condition_id` as state key -- always use `token_id`
- Do NOT place game-start sell using `buy_record.sell_price` (that's `buy_price + spread`) -- use `buy_record.buy_price`
- Do NOT create a global lock -- use per-instance locks on each state manager
- Do NOT hold `OrderTracker._lock` while calling `clob_client.create_sell_order()` -- the lock protects dict operations, not API calls
- Do NOT make recovery threads non-daemon -- they should not block bot shutdown

### Scope Boundaries

**In scope:**
- `threading.Lock` on all state managers (`OrderTracker`, `PositionTracker`, `MarketRegistry`, `GameLifecycle`) and `ClobClientWrapper`
- `record_sell_if_absent()` atomic method on `OrderTracker`
- `GameStartService` with `handle_game_start(token_id)` for all game states
- APScheduler `DateTrigger` scheduling via `SchedulerService.schedule_game_start()` at exact kickoff time
- Dedicated `threading.Thread` per game for recovery (AC #4)
- Game-start sell at buy_price (not spread price)
- New lifecycle transitions: SELL_PLACED/FILLING/BUY_PLACED -> GAME_STARTED, BUY_PLACED/FILLING -> DONE
- Trigger registration after successful buy order placement (alongside pre-kickoff trigger)
- Updated wiring in `main.py`
- Comprehensive tests for all acceptance criteria + thread-safety tests

**Out of scope:**
- Post-game-start sell verification and retry (Story 4.3 -- the 1-minute verify + retry loop)
- Startup reconciliation (Story 5.1 -- rebuild state and re-schedule triggers from API)
- State pruning (Story 5.4)
- Any changes to `FillPollingService` (it naturally stops polling games in GAME_STARTED state)
- Any changes to `PreKickoffService` (it works correctly as-is)
- Refactoring `OrderExecutionService` to add `override_price` parameter (Story 4.1 established the pattern of direct CLOB calls for pre-kickoff/game-start sells)

### Project Structure Notes

This story adds the game-start recovery capability and thread-safety foundation:

```
main.py (composition root)
  +-- ClobClientWrapper (clients/)        -- MODIFIED: adds threading.Lock
  +-- MarketRegistry (state/)             -- MODIFIED: adds threading.Lock
  +-- OrderTracker (state/)               -- MODIFIED: adds threading.Lock + record_sell_if_absent()
  +-- PositionTracker (state/)            -- MODIFIED: adds threading.Lock
  +-- GammaClient (clients/)
  +-- MarketDiscoveryService (core/)
  +-- LiquidityAnalyser (core/)
  +-- MarketAnalysisPipeline (core/)
  +-- PreKickoffService (core/)
  +-- GameStartService (core/)            -- NEW: handles game-start recovery
  +-- SchedulerService (core/)            -- MODIFIED: adds game-start date trigger + thread launch
  +-- OrderExecutionService (core/)       -- MODIFIED: registers game-start trigger after buy
  +-- FillPollingService (core/)
```

Flow after this story:
```
discover -> analyse -> place buy orders
  -> [register pre-kickoff trigger + game-start trigger per game]
  -> [poll fills every 30s] -> [threshold met: place sell]
  -> [kickoff - N minutes: pre-kickoff consolidation: cancel sells/buys, re-sell at buy_price]
  -> [kickoff: game-start recovery: detect Polymarket cancellation, re-place sell at buy_price]
```

### References

- [Source: epics.md#Story 4.2: Game-Start Order Cancellation Detection and Sell Re-Placement] -- acceptance criteria
- [Source: epics.md#Epic 4 Overview] -- epic objectives, zero unmanaged positions
- [Source: architecture.md#Application Architecture & Process Model] -- synchronous main loop + dedicated threads for game-start recovery
- [Source: architecture.md#Scheduling & Timing Strategy] -- APScheduler BackgroundScheduler, DateTrigger per game
- [Source: architecture.md#State Management Architecture] -- domain-separated state managers
- [Source: architecture.md#Game Lifecycle Management] -- GAME_STARTED state, explicit transitions
- [Source: architecture.md#Process Patterns - Error Handling] -- @with_retry returns None, caller handles gracefully
- [Source: architecture.md#Implementation Patterns] -- duplicate prevention pattern, logging levels
- [Source: architecture.md#Data Flow - GAME-START RECOVERY] -- detect cancellation, re-place sell at buy_price, verify
- [Source: prd.md#FR19] -- detect when Polymarket automatically cancels all open orders at game start
- [Source: prd.md#FR20] -- re-place sell orders for all filled buy positions at the buy price
- [Source: prd.md#NFR4] -- game-start sell re-creation within 5 minutes
- [Source: prd.md#NFR1] -- 14-day continuous uptime (thread-safety critical for this)
- [Source: epic-4-preparation-2026-04-05.md#Thread-Safety Analysis] -- locking strategy per component, race condition inventory
- [Source: epic-4-preparation-2026-04-05.md#Sell Price Override Design] -- Option C selected but Story 4.1 used direct CLOB calls instead
- [Source: 4-1-pre-kickoff-sell-consolidation-and-buy-cancellation.md] -- previous story patterns, 328 tests baseline, pre-kickoff handler as template
- [Source: epic-3-retro-2026-04-04.md] -- thread-safety analysis as preparation task, "extend don't recreate" principle
- [Source: game_lifecycle.py#VALID_TRANSITIONS] -- current transitions, new ones needed
- [Source: order_tracker.py] -- current methods, no locks yet, record_sell_if_absent() needed
- [Source: scheduling.py] -- schedule_pre_kickoff() as template for schedule_game_start()
- [Source: pre_kickoff.py] -- handler pattern, _TERMINAL_STATES, _cancel_buy_if_active()

## Dev Agent Record

### Agent Model Used

claude-sonnet-4.6 (github-copilot/claude-sonnet-4.6)

### Debug Log References

None — all tasks completed without requiring debug investigation.

### Completion Notes List

- Task 1: Added `threading.Lock` to `OrderTracker`, `PositionTracker`, `MarketRegistry`, `GameLifecycle`, and `ClobClientWrapper`. All public methods wrapped with `with self._lock:`. `record_sell_if_absent()` atomic method added to `OrderTracker`. `GameLifecycle` locks are inside `transition()` checking against `self._state` (not `self.state` property to avoid recursive locking).
- Task 2: `GameStartService` created in `btts_bot/core/game_start.py` following `PreKickoffService` pattern. Handles all lifecycle states (PRE_KICKOFF, SELL_PLACED, FILLING, BUY_PLACED, terminal states, early states). Uses `record_sell_if_absent()` for atomic sell recording. Outer try/except in `handle_game_start()` prevents silent thread death.
- Task 3: New transitions added to `VALID_TRANSITIONS`: `SELL_PLACED → GAME_STARTED`, `FILLING → GAME_STARTED`, `FILLING → DONE`, `BUY_PLACED → GAME_STARTED`, `BUY_PLACED → DONE`.
- Task 4: `SchedulerService` updated with `game_start_service` parameter, `schedule_game_start()` method firing DateTrigger at exact kickoff time, and `_launch_game_start_thread()` callback that spawns a dedicated daemon thread per game.
- Task 5: `OrderExecutionService.place_buy_order()` now calls `schedule_game_start()` alongside `schedule_pre_kickoff()` after successful buy placement.
- Task 6: `main.py` updated: `GameStartService` instantiated after `PreKickoffService`, passed to `SchedulerService` constructor.
- Task 7: 25 tests in `tests/test_game_start.py` covering all state paths, error handling, logging, and atomic recording.
- Task 8: 6 thread-safety tests in `tests/test_thread_safety.py` covering `OrderTracker`, `PositionTracker`, and `GameLifecycle` concurrency.
- Task 9: 6 new `schedule_game_start` tests added to `tests/test_scheduling.py` including DateTrigger creation, past kickoff warning, idempotency, job ID format, daemon thread spawning, and callback registration.
- Task 10: Updated `tests/test_scheduling.py` `_make_service` helper, `tests/test_order_execution.py` added `schedule_game_start` test and updated failure test, `tests/test_main.py` added `GameStartService` mock + 3 wiring tests.
- Task 11: 371 tests pass (up from 328), ruff check zero issues, ruff format no changes.

### File List

- `btts_bot/state/order_tracker.py` — MODIFIED: threading.Lock, record_sell_if_absent()
- `btts_bot/state/position_tracker.py` — MODIFIED: threading.Lock
- `btts_bot/state/market_registry.py` — MODIFIED: threading.Lock
- `btts_bot/core/game_lifecycle.py` — MODIFIED: threading.Lock, new transitions (SELL_PLACED/FILLING/BUY_PLACED → GAME_STARTED, FILLING/BUY_PLACED → DONE)
- `btts_bot/clients/clob.py` — MODIFIED: threading.Lock on all methods
- `btts_bot/core/game_start.py` — NEW: GameStartService
- `btts_bot/core/scheduling.py` — MODIFIED: game_start_service dep, schedule_game_start(), _launch_game_start_thread()
- `btts_bot/core/order_execution.py` — MODIFIED: schedule_game_start() call after buy placement
- `btts_bot/main.py` — MODIFIED: GameStartService wiring, updated SchedulerService constructor
- `tests/test_game_start.py` — NEW: 25 tests for GameStartService
- `tests/test_thread_safety.py` — NEW: 6 thread-safety tests
- `tests/test_scheduling.py` — MODIFIED: updated _make_service helper, 6 new schedule_game_start tests
- `tests/test_order_execution.py` — MODIFIED: added schedule_game_start test, updated failure test
- `tests/test_main.py` — MODIFIED: GameStartService mock + 3 wiring tests
