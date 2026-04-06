# Story 4.1: Pre-Kickoff Sell Consolidation and Buy Cancellation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to consolidate my sell orders and cancel unfilled buys before kickoff,
so that I have one maximum-size sell at the buy price for the best fill probability in the final minutes.

## Acceptance Criteria

1. **Given** a game with an active sell order and a known kickoff time
   **When** the current time reaches `kickoff_time - timing.pre_kickoff_minutes`
   **Then** an APScheduler date trigger fires for that specific game

2. **Given** the pre-kickoff trigger fires for a game in SELL_PLACED state
   **When** the pre-kickoff handler runs
   **Then** it cancels all unfilled sell orders for that token via ClobClientWrapper
   **And** re-creates a single consolidated sell order at the buy price (not buy_price + spread) for the full accumulated position size
   **And** updates OrderTracker with the new sell order ID
   **And** the game transitions to PRE_KICKOFF via GameLifecycle
   **And** an INFO log is emitted: `[Home vs Away] Pre-kickoff consolidation: sell at buy_price=..., size=...`

3. **Given** the game has an unfilled buy order at pre-kickoff time
   **When** the pre-kickoff handler runs
   **Then** the unfilled buy order is cancelled via ClobClientWrapper
   **And** OrderTracker is updated to reflect the cancellation
   **And** an INFO log is emitted: `[Home vs Away] Pre-kickoff buy cancelled`

4. **Given** the game is in FILLING state (has fills but no sell yet -- fills below min threshold)
   **When** the pre-kickoff trigger fires
   **Then** a sell order is placed at the buy price for whatever accumulated fills exist (even if below min_order_size)
   **And** the unfilled buy is cancelled
   **And** the game transitions to PRE_KICKOFF

5. **Given** ClobClientWrapper returns `None` for a cancel or sell placement (retries exhausted)
   **When** the pre-kickoff handler encounters the failure
   **Then** the error is logged at ERROR level
   **And** the game is flagged for priority handling during game-start recovery

## Tasks / Subtasks

- [x] Task 1: Create `PreKickoffService` in `btts_bot/core/pre_kickoff.py` (AC: #1-#5)
  - [x] Constructor dependencies: `clob_client`, `order_tracker`, `position_tracker`, `market_registry` (no `btts_config` needed -- buy_price comes from BuyOrderRecord, sell size from PositionTracker)
  - [x] Implement `handle_pre_kickoff(token_id: str) -> None` -- main handler for a single game
  - [x] Handle SELL_PLACED state: cancel existing sell, re-create at buy_price for full position size (AC #2)
  - [x] Handle FILLING state: place sell at buy_price for accumulated fills, cancel buy (AC #4)
  - [x] Handle BUY_PLACED state (no fills): cancel buy, transition to PRE_KICKOFF if no position, DONE if no fills (AC #3)
  - [x] Handle failure cases: log ERROR, set flag for game-start recovery priority (AC #5)

- [x] Task 2: Add pre-kickoff scheduling to `SchedulerService` in `btts_bot/core/scheduling.py` (AC: #1)
  - [x] Add `pre_kickoff_service: PreKickoffService` as constructor dependency
  - [x] Add `timing_config: TimingConfig` as constructor dependency
  - [x] Implement `schedule_pre_kickoff(token_id: str, kickoff_time: datetime) -> None`
  - [x] Create APScheduler `DateTrigger` for `kickoff_time - pre_kickoff_minutes`
  - [x] Job ID format: `pre_kickoff_{token_id}` for idempotent scheduling
  - [x] Skip scheduling if trigger time is already in the past (log WARNING)

- [x] Task 3: Wire pre-kickoff scheduling into buy order placement flow (AC: #1)
  - [x] After successful buy order placement in `OrderExecutionService.place_buy_order()`, call scheduler to register pre-kickoff trigger
  - [x] Pass `token_id` and `kickoff_time` from `MarketEntry`
  - [x] This ensures every game with a buy order gets a pre-kickoff trigger

- [x] Task 4: Add `cancel_buy_order` helper method to `OrderTracker` (AC: #3)
  - [x] Add `mark_buy_cancelled(token_id: str) -> None` -- marks buy as inactive AND records cancellation
  - [x] Alternative: reuse `mark_inactive()` which already exists -- evaluate if sufficient

- [x] Task 5: Update `main.py` wiring (AC: #1-#5)
  - [x] **BREAKING CHANGE: Reorder `main.py` dependency creation** -- current code creates `OrderExecutionService` (line 67) BEFORE `SchedulerService` (line 88). New order: `PreKickoffService` -> `SchedulerService` -> `OrderExecutionService` -> `FillPollingService`. Move `execute_all_analysed()` call AFTER all services are wired.
  - [x] Create `PreKickoffService` with `clob_client, order_tracker, position_tracker, market_registry`
  - [x] Update `SchedulerService` constructor to accept `pre_kickoff_service` and `timing_config`
  - [x] Update `OrderExecutionService` to accept `scheduler_service` for trigger registration
  - [x] Jobs can be added to the scheduler before `scheduler_service.start()` -- APScheduler queues them

- [x] Task 6: Write tests for `PreKickoffService` in `tests/test_pre_kickoff.py` (AC: #2-#5)
  - [x] Test: SELL_PLACED state -- cancel old sell, place new sell at buy_price, transition to PRE_KICKOFF
  - [x] Test: SELL_PLACED state -- sell price is buy_price (NOT buy_price + spread)
  - [x] Test: SELL_PLACED state -- sell size equals full accumulated position size from PositionTracker
  - [x] Test: FILLING state -- place sell at buy_price for accumulated fills (even below min_order_size)
  - [x] Test: FILLING state -- cancel unfilled buy order
  - [x] Test: BUY_PLACED state (no fills) -- cancel buy, handle no-position scenario
  - [x] Test: cancel_order failure -- logs ERROR, does not crash
  - [x] Test: create_sell_order failure -- logs ERROR, does not crash
  - [x] Test: game already in PRE_KICKOFF or later state -- skip processing

- [x] Task 7: Write tests for scheduling in `tests/test_scheduling.py` (AC: #1)
  - [x] Test: `schedule_pre_kickoff` adds DateTrigger job with correct run_date
  - [x] Test: trigger time in the past -- job not added, WARNING logged
  - [x] Test: duplicate scheduling (same token_id) -- `replace_existing=True` handles it

- [x] Task 8: Write tests for wiring in `tests/test_main.py` (AC: #1)
  - [x] Update existing `main.py` tests to account for new constructor signatures
  - [x] Add wiring verification for `PreKickoffService`

- [x] Task 9: Write tests for buy order scheduling trigger in `tests/test_order_execution.py`
  - [x] Test: after successful buy placement, scheduler is called with correct token_id and kickoff_time
  - [x] Test: after failed buy placement, scheduler is NOT called

- [x] Task 10: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` -- zero issues
  - [x] `uv run ruff format btts_bot/ tests/` -- no changes needed
  - [x] All existing tests still pass (no regressions)

## Dev Notes

### Critical Context: Sell Price Override -- Buy Price, NOT Spread Price

This is the most important behavioral change in Epic 4. Pre-kickoff sells are placed at the **buy price** (breakeven), NOT at `buy_price + price_diff` (spread price). The rationale: in the final minutes before kickoff, maximizing fill probability is more important than capturing the spread.

```python
# CORRECT: Pre-kickoff sell at buy_price
buy_record = order_tracker.get_buy_order(token_id)
sell_price = buy_record.buy_price  # NOT buy_record.sell_price

# WRONG: Do NOT use the spread price
# sell_price = buy_record.sell_price  # This is buy_price + price_diff
```

This means `PreKickoffService` does NOT reuse `OrderExecutionService.place_sell_order()` as-is because that method uses `buy_record.sell_price`. Options:
1. **New method on PreKickoffService** that calls `clob_client.create_sell_order()` directly with `buy_price` -- RECOMMENDED
2. Add a `price_override` parameter to `OrderExecutionService.place_sell_order()` -- adds complexity to existing tested method

Use option 1. `PreKickoffService` is in `core/` so it can receive `ClobClientWrapper` via DI and call it directly. Keep `OrderExecutionService.place_sell_order()` unchanged -- it remains the "normal" sell path with spread pricing.

Apply the same defensive `0.99` price cap used by `OrderExecutionService.place_sell_order()`:
```python
sell_price = min(buy_record.buy_price, 0.99)
```

### Critical Context: Thread-Safety Consideration

The Epic 3 retro flagged thread-safety analysis as a prerequisite for Epic 4. Key finding:

- `PreKickoffService.handle_pre_kickoff()` runs in an APScheduler thread (not the main thread)
- `FillPollingService.poll_all_active_orders()` also runs in an APScheduler thread
- Both access `OrderTracker`, `PositionTracker`, and `MarketRegistry` concurrently

**For Story 4.1:** The risk is LOW because:
- APScheduler's default `ThreadPoolExecutor` with `max_workers=10` means concurrent execution is possible
- However, pre-kickoff and fill polling operate on different phases of a game's lifecycle
- Pre-kickoff fires once per game (date trigger), fill polling fires every 30s (interval)
- The overlap window is small: pre-kickoff fires minutes before kickoff, while polling should have already detected most fills

**Decision:** Do NOT add locks in Story 4.1. Instead:
- Design the handler to be idempotent (check current state before acting)
- Add state checks at the start: only process if game is in SELL_PLACED, FILLING, or BUY_PLACED
- Document that thread-safety may need revisiting in Story 4.2 when dedicated recovery threads are added

**Known TOCTOU risk for Story 4.2:** Both fill-polling (`place_sell_order`) and pre-kickoff handler could simultaneously read `has_sell_order() == False` and both proceed to create sells. For Story 4.1 this is acceptable -- the overlap window is small and the worst case is a duplicate sell that game-start recovery handles. Story 4.2 should evaluate adding locks if dedicated recovery threads increase concurrency.

### Critical Context: APScheduler DateTrigger for Per-Game Timing

The `SchedulerService` already has an APScheduler `BackgroundScheduler` instance exposed via the `scheduler` property. Per-game pre-kickoff triggers use `DateTrigger`:

```python
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone

def schedule_pre_kickoff(self, token_id: str, kickoff_time: datetime) -> None:
    pre_kickoff_time = kickoff_time - timedelta(minutes=self._timing.pre_kickoff_minutes)
    
    # Skip if trigger time is already past
    if pre_kickoff_time <= datetime.now(timezone.utc):
        logger.warning(
            "Pre-kickoff trigger for token=%s is in the past (kickoff=%s), skipping",
            token_id,
            kickoff_time.isoformat(),
        )
        return
    
    self._scheduler.add_job(
        func=self._pre_kickoff_service.handle_pre_kickoff,
        trigger=DateTrigger(run_date=pre_kickoff_time),
        args=[token_id],
        id=f"pre_kickoff_{token_id}",
        name=f"Pre-kickoff: {token_id}",
        replace_existing=True,
        misfire_grace_time=300,  # 5 minute grace for misfired triggers
    )
```

**Key details:**
- `DateTrigger` fires once at the specified `run_date` and is then automatically removed from the scheduler's job store -- it will NOT fire again. If the handler fails and the game stays in SELL_PLACED/FILLING, Story 4.2 (game-start recovery) is the safety net.
- `replace_existing=True` makes scheduling idempotent
- `misfire_grace_time=300` (5 minutes) ensures the trigger still fires if the scheduler was briefly busy
- Job runs in APScheduler's thread pool (not main thread)
- `kickoff_time` comes from `MarketEntry.kickoff_time` (a `datetime` object)
- The `<=` comparison for past-time check intentionally skips triggers at exactly "now" -- use strict `<` only if you want to allow triggers scheduled for the current second

### Critical Context: SchedulerService Dependency Changes

The current `SchedulerService` constructor takes `daily_fetch_hour_utc` and `discovery_service`. For Story 4.1, it needs additional dependencies:

```python
class SchedulerService:
    def __init__(
        self,
        daily_fetch_hour_utc: int,
        discovery_service: MarketDiscoveryService,
        pre_kickoff_service: PreKickoffService,  # NEW
        timing_config: TimingConfig,              # NEW -- for pre_kickoff_minutes
    ) -> None:
```

**Ripple effect:** `main.py` must update the `SchedulerService(...)` constructor call. All existing tests in `tests/test_scheduling.py` must update constructor calls.

### Critical Context: OrderExecutionService Needs Scheduler Reference

After placing a buy order successfully, `OrderExecutionService` must register a pre-kickoff trigger. This means `OrderExecutionService` needs a reference to `SchedulerService`.

**Circular dependency risk:** `SchedulerService` depends on `PreKickoffService`, and `OrderExecutionService` depends on `SchedulerService`. `PreKickoffService` does NOT depend on `OrderExecutionService` (it uses `ClobClientWrapper` directly), so no cycle.

Wiring order in `main.py` (**this is a significant reordering from current code -- see current `main.py` where `OrderExecutionService` is created at line 67, used at line 70, but `SchedulerService` is not created until line 88**):
```python
# 1. State managers (no deps)
market_registry = MarketRegistry()
order_tracker = OrderTracker()
position_tracker = PositionTracker()

# 2. Clients
clob_client = ClobClientWrapper()
gamma_client = GammaClient(config.data_file)

# 3. Core services
pre_kickoff_service = PreKickoffService(
    clob_client, order_tracker, position_tracker, market_registry,
)
discovery_service = MarketDiscoveryService(...)

# 4. Scheduler (depends on pre_kickoff_service and discovery_service)
scheduler_service = SchedulerService(
    config.timing.daily_fetch_hour_utc, discovery_service,
    pre_kickoff_service, config.timing,
)

# 5. Order execution (depends on scheduler_service for trigger registration)
order_execution_service = OrderExecutionService(
    clob_client, order_tracker, position_tracker, market_registry, config.btts,
    scheduler_service,  # NEW dependency
)

# 6. Fill polling (depends on order_execution_service)
fill_polling_service = FillPollingService(
    clob_client, order_tracker, position_tracker, market_registry, config.btts,
    order_execution_service,
)

# 7. execute_all_analysed() must be called AFTER all services are wired
#    (moved from its current position between OrderExecutionService and SchedulerService)
```

**Note:** Jobs can be added to the APScheduler before `scheduler_service.start()` is called -- they queue and execute once `start()` runs. So the buy order flow registering pre-kickoff triggers during `execute_all_analysed()` is safe even before the scheduler starts.

### Critical Context: Pre-Kickoff Handler Logic for Each Game State

The handler must be robust to all possible game states when the trigger fires:

**SELL_PLACED (normal path):**
1. Get existing `SellOrderRecord` from `OrderTracker`
2. Cancel existing sell via `clob_client.cancel_order(existing_sell.order_id)`
3. If cancel fails (returns None): log ERROR, return (game-start recovery will handle)
4. Remove old sell record from `OrderTracker`
5. Get `buy_price` from `BuyOrderRecord` (NOT `sell_price`)
6. Get `accumulated_fills` from `PositionTracker`
7. Place new sell at `buy_price` for `accumulated_fills` via `clob_client.create_sell_order()`
8. If sell placement fails: log ERROR, return (game-start recovery will handle -- position has no sell coverage)
9. Record new sell in `OrderTracker`
10. Cancel any active buy order if it exists (may have been partially filled)
11. Mark buy as inactive
12. Transition game to `PRE_KICKOFF`

**FILLING (has fills, no sell yet):**
1. Get `buy_price` from `BuyOrderRecord`
2. Get `accumulated_fills` from `PositionTracker`
3. Place sell at `buy_price` for `accumulated_fills` (even if < `min_order_size`)
4. If sell fails: log ERROR, return
5. Record sell in `OrderTracker`
6. Cancel active buy order
7. Mark buy as inactive
8. Transition game to `PRE_KICKOFF`

**BUY_PLACED (no fills at all):**
1. Cancel buy order via `clob_client.cancel_order(buy_record.order_id)`
2. Mark buy as inactive
3. Check `accumulated_fills` from `PositionTracker` (should be 0)
4. If 0 fills: no sell needed, transition to `PRE_KICKOFF` then `DONE`
5. If somehow fills > 0 (race condition with fill polling): place sell at buy_price

**DISCOVERED or ANALYSED (buy never placed):**
1. Nothing to do. Transition to `SKIPPED` or `DONE` if applicable.
2. Or just return -- no action needed.

**PRE_KICKOFF, GAME_STARTED, RECOVERY_COMPLETE, DONE, SKIPPED, EXPIRED:**
1. Already handled or terminal. Log DEBUG and return.

### Critical Context: The "Flag for Priority" Mechanism (AC #5)

When a pre-kickoff operation fails, the game needs priority handling at game-start. The simplest mechanism: add a boolean flag on the `MarketEntry` or use the game state itself.

**Recommended approach:** Do NOT add a new flag. Instead, if pre-kickoff fails:
- The game stays in its current state (SELL_PLACED or FILLING) instead of transitioning to PRE_KICKOFF
- Game-start recovery (Story 4.2) will check all games that should be in PRE_KICKOFF but aren't
- This is implicit flagging via state: `SELL_PLACED` at game-start time = needs recovery

This avoids adding new data model fields and uses the existing state machine as the signaling mechanism.

### Lifecycle Transitions

Transitions used by this story:
- `SELL_PLACED -> PRE_KICKOFF` -- on successful pre-kickoff consolidation
- `FILLING -> PRE_KICKOFF` -- on successful pre-kickoff with sub-threshold fills
- `BUY_PLACED -> PRE_KICKOFF` -- cancelling an unfilled buy (but check if fills exist)
- `PRE_KICKOFF -> DONE` -- when there's no position to manage (0 fills, buy cancelled)

All these transitions already exist in `VALID_TRANSITIONS` except `BUY_PLACED -> PRE_KICKOFF`.

**REQUIRED: Add `BUY_PLACED -> PRE_KICKOFF` to VALID_TRANSITIONS** in `game_lifecycle.py`:
```python
GameState.BUY_PLACED: frozenset({GameState.FILLING, GameState.SKIPPED, GameState.EXPIRED, GameState.PRE_KICKOFF}),
```

Also need `FILLING -> PRE_KICKOFF` -- this already exists in the current VALID_TRANSITIONS.

### Cancel Order via ClobClientWrapper

`ClobClientWrapper.cancel_order(order_id: str)` already exists and is decorated with `@with_retry`. It calls `self._client.cancel({"orderID": order_id})`. Returns the cancel response or `None` on retry exhaustion.

`ClobClientWrapper.cancel_orders(order_ids: list[str])` also exists for batch cancellation. Use `cancel_order` for individual cancellations in pre-kickoff (one sell + optionally one buy per game).

### File Locations

**Files to create:**
- `btts_bot/core/pre_kickoff.py` -- NEW: `PreKickoffService` class
- `tests/test_pre_kickoff.py` -- NEW: tests for `PreKickoffService`

**Files to modify:**
- `btts_bot/core/game_lifecycle.py` -- ADD: `PRE_KICKOFF` to `BUY_PLACED` transitions
- `btts_bot/core/scheduling.py` -- ADD: `pre_kickoff_service` + `timing_config` deps, `schedule_pre_kickoff()` method
- `btts_bot/core/order_execution.py` -- ADD: `scheduler_service` dependency, call `schedule_pre_kickoff()` after successful buy
- `btts_bot/main.py` -- MODIFY: wiring for `PreKickoffService`, updated `SchedulerService` and `OrderExecutionService` constructors
- `tests/test_scheduling.py` -- MODIFY: update constructor calls, add `schedule_pre_kickoff` tests
- `tests/test_order_execution.py` -- MODIFY: update constructor, add trigger registration tests
- `tests/test_main.py` -- MODIFY: update wiring tests for new dependencies

**Files NOT to touch:**
- `btts_bot/state/order_tracker.py` -- `mark_inactive()`, `remove_sell_order()`, `record_sell()` all exist. Note: `get_order()` is an alias for `get_buy_order()` -- use `get_buy_order()` for clarity.
- `btts_bot/state/position_tracker.py` -- `get_accumulated_fills()` already implemented
- `btts_bot/state/market_registry.py` -- unchanged
- `btts_bot/clients/clob.py` -- `cancel_order()`, `create_sell_order()` already exist
- `btts_bot/config.py` -- `pre_kickoff_minutes` already in `TimingConfig`
- `btts_bot/retry.py` -- unchanged
- `btts_bot/logging_setup.py` -- unchanged
- `btts_bot/clients/gamma.py` -- not involved
- `btts_bot/clients/data_api.py` -- not involved
- `btts_bot/core/market_discovery.py` -- unchanged
- `btts_bot/core/liquidity.py` -- unchanged
- `btts_bot/core/fill_polling.py` -- unchanged. Note: fill polling's `_poll_single_order` only processes games in BUY_PLACED, FILLING, or SELL_PLACED states, so once pre-kickoff transitions a game to PRE_KICKOFF and marks the buy as inactive, fill polling correctly stops processing that game.
- `btts_bot/core/reconciliation.py` -- stub for Story 5.1

### Previous Story Intelligence (3.3 / Epic 3 Retro)

From Story 3.3 completion and Epic 3 retro:
- 289 app tests pass, 322 full suite tests pass
- `OrderTracker` is fully implemented: `SellOrderRecord`, `record_sell`, `get_sell_order`, `remove_sell_order`, `mark_inactive`, `get_active_buy_orders`
- `ClobClientWrapper.create_sell_order()` uses GTC (Good Til Cancelled) with `expiration=0`
- `ClobClientWrapper.cancel_order()` exists and works
- `OrderExecutionService.place_sell_order()` uses `buy_record.sell_price` (spread price) -- pre-kickoff MUST NOT reuse this method
- `OrderExecutionService.update_sell_order()` does cancel-and-replace -- similar flow to pre-kickoff but different price
- Fill polling registered as APScheduler interval job in `main.py`
- Tests use pytest with `MagicMock`, `patch`, and `caplog`
- Both `unittest.TestCase` and plain pytest function styles in test suite
- `from __future__ import annotations` in `core/` and `state/` modules
- Module-level `logger = logging.getLogger(__name__)` in every module
- Type hints on all function signatures
- `@dataclasses.dataclass` for data records
- `ruff check` and `ruff format` must pass with zero issues

**Epic 3 Retro Action Items relevant to this story:**
- "Ripple effects from evolving data models" -- minimize constructor signature changes
- "Cross-story data model review" -- this story does NOT change any data models in `state/`
- "Thread-safety analysis" -- handled in Dev Notes section above

### Git Intelligence

Last 5 commits:
```
749e7d4 3-3-automatic-sell-order-placement-on-fill-threshold
3f35e45 3-2-fill-accumulation-tracking-via-polling
0b19fd7 3-1-buy-order-placement-with-duplicate-prevention
2d148ff epic-2-retro
9ddd5a4 2-4-three-case-orderbook-liquidity-analysis
```

Consistent commit message format: story key only as commit message.

### Architecture Constraints to Enforce

- `core/` modules contain business logic -- receive client instances via DI, never import `requests` or `py-clob-client` directly. Import `ClobClientWrapper` at module level (matching `order_execution.py`, `liquidity.py` pattern).
- `state/` modules are pure data managers -- hold state and answer queries, NEVER initiate API calls or schedule jobs
- `clients/` modules are thin I/O wrappers -- only place that imports `py-clob-client`/`requests`
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` -- never set `_state` directly
- `@with_retry` on all API calls in `clients/` -- no bare API calls in business logic
- Check `OrderTracker` state before every order operation (duplicate prevention pattern)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries -- caller must handle gracefully

### Architecture Anti-Patterns to Avoid

- Do NOT reuse `OrderExecutionService.place_sell_order()` for pre-kickoff sells -- it uses spread price, pre-kickoff needs buy_price
- Do NOT add API call logic to `OrderTracker` or `PositionTracker` -- they are pure data managers in `state/`
- **Import pattern for `PreKickoffService`:** The architecture calls for `TYPE_CHECKING` guard imports from `clients/` in `core/` modules. In practice, `order_execution.py` and `liquidity.py` use module-level imports while only `fill_polling.py` uses the `TYPE_CHECKING` guard. For `PreKickoffService`, follow the module-level import pattern (matching `order_execution.py`) for consistency with the majority of existing `core/` modules.
- Do NOT import `py_clob_client` anywhere except `clients/clob.py`
- Do NOT add threading locks in this story -- not needed yet, revisit in Story 4.2
- Do NOT crash on API errors -- log and continue (game-start recovery is the safety net)
- Do NOT use `condition_id` as state key -- always use `token_id`
- Do NOT transition to PRE_KICKOFF if the pre-kickoff operation fails -- leave in current state as implicit flag for game-start recovery
- Do NOT place pre-kickoff sell using `buy_record.sell_price` (that's `buy_price + spread`) -- use `buy_record.buy_price`

### Scope Boundaries

**In scope:**
- `PreKickoffService` with `handle_pre_kickoff(token_id)` for all game states
- APScheduler `DateTrigger` scheduling via `SchedulerService.schedule_pre_kickoff()`
- Trigger registration after successful buy order placement
- Pre-kickoff sell at buy_price (not spread price)
- Buy order cancellation at pre-kickoff
- Handling of sub-threshold fills (FILLING state with < min_order_size)
- Updated wiring in `main.py`
- Comprehensive tests for all acceptance criteria

**Out of scope:**
- Game-start sell re-placement (Story 4.2 -- detect cancellation at kickoff and re-place)
- Post-game-start sell verification and retry (Story 4.3)
- Startup reconciliation (Story 5.1 -- rebuild state and re-schedule triggers from API)
- State pruning (Story 5.4)
- Threading locks or synchronization (evaluate in Story 4.2)
- Any changes to `PositionTracker` or `OrderTracker` data models

### Project Structure Notes

This story begins Epic 4 and adds the first per-game timing capability:

```
main.py (composition root)
  +-- ClobClientWrapper (clients/)
  +-- MarketRegistry (state/)
  +-- OrderTracker (state/)
  +-- PositionTracker (state/)
  +-- GammaClient (clients/)
  +-- MarketDiscoveryService (core/)
  +-- LiquidityAnalyser (core/)
  +-- MarketAnalysisPipeline (core/)
  +-- PreKickoffService (core/)            -- NEW: handles pre-kickoff consolidation
  +-- SchedulerService (core/)             -- MODIFIED: adds per-game date triggers
  +-- OrderExecutionService (core/)        -- MODIFIED: registers pre-kickoff trigger after buy
  +-- FillPollingService (core/)
```

Flow after this story:
```
discover -> analyse -> place buy orders -> [register pre-kickoff trigger per game]
  -> [poll fills every 30s] -> [threshold met: place sell]
  -> [kickoff - N minutes: pre-kickoff consolidation: cancel sells/buys, re-sell at buy_price]
```

### References

- [Source: epics.md#Story 4.1: Pre-Kickoff Sell Consolidation and Buy Cancellation] -- acceptance criteria
- [Source: epics.md#Epic 4 Overview] -- epic objectives, zero unmanaged positions
- [Source: architecture.md#Scheduling & Timing Strategy] -- APScheduler BackgroundScheduler, DateTrigger per game
- [Source: architecture.md#State Management Architecture] -- domain-separated state managers
- [Source: architecture.md#Game Lifecycle Management] -- PRE_KICKOFF state, explicit transitions
- [Source: architecture.md#Process Patterns - Error Handling] -- @with_retry returns None, caller handles gracefully
- [Source: architecture.md#Implementation Patterns] -- duplicate prevention pattern, logging levels
- [Source: architecture.md#Data Flow - PRE-KICKOFF CONSOLIDATION] -- cancel unfilled sells, re-create at buy_price, cancel unfilled buy
- [Source: prd.md#FR17] -- cancel unfilled sells at configurable time before kickoff, re-create consolidated sell at buy price
- [Source: prd.md#FR18] -- cancel unfilled buy orders before kickoff
- [Source: prd.md#NFR4] -- game-start sell re-creation within 5 minutes (relevant to failure flag)
- [Source: config.py#TimingConfig] -- `pre_kickoff_minutes` already defined (default=10)
- [Source: game_lifecycle.py#VALID_TRANSITIONS] -- SELL_PLACED->PRE_KICKOFF confirmed, BUY_PLACED->PRE_KICKOFF needs adding
- [Source: order_tracker.py] -- mark_inactive(), remove_sell_order(), record_sell() all exist
- [Source: position_tracker.py] -- get_accumulated_fills() exists
- [Source: clients/clob.py] -- cancel_order(), create_sell_order() exist with @with_retry
- [Source: scheduling.py] -- BackgroundScheduler exposed via scheduler property, add_job pattern established
- [Source: epic-3-retro-2026-04-04.md] -- thread-safety analysis, sell price override design, 289 tests baseline
- [Source: 3-3-automatic-sell-order-placement-on-fill-threshold.md] -- sell order patterns, OrderTracker state, FillPollingService integration

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

None.

### Completion Notes List

- Source code for Tasks 1-5 was already implemented in pre-session work (pre_kickoff.py, scheduling.py, order_execution.py, game_lifecycle.py, main.py all contained complete implementations).
- Task 4: `mark_inactive()` was reused (sufficient — evaluated per subtask guidance); no new method added to OrderTracker.
- Task 6 (test_pre_kickoff.py) and Task 7 (test_scheduling.py) were already fully written.
- Task 8: Added `PreKickoffService` mock to `_run_main_with_patches` helper; added `PreKickoffService` patch to `test_main_logs_loaded_config_path`; added 5 new wiring-verification tests: PreKickoffService instantiation, deps, SchedulerService receives pre_kickoff_service, SchedulerService receives timing_config, OrderExecutionService receives scheduler_service.
- Task 9: Added 3 new tests verifying scheduler trigger registration: success calls schedule_pre_kickoff with correct args; API failure does NOT call scheduler; no scheduler_service (None) does not crash.
- Task 10: Fixed 2 pre-existing test failures: (1) `test_order_execution.py` used hardcoded kickoff date `2026-04-05` now in the past — updated `_register_market` to use `datetime.now() + timedelta(days=30)` and updated timestamp-comparison tests to use `entry.kickoff_time` instead; (2) `test_scheduling.py::test_schedule_pre_kickoff_at_exactly_now_skips` used `pre_kickoff_minutes=0` which violates `TimingConfig.pre_kickoff_minutes > 0` validation — replaced with `pre_kickoff_minutes=1` and a kickoff 30s in the past.
- Final result: 328 tests pass, 0 failures, ruff check clean, ruff format no changes.

### File List

- `btts_bot/core/pre_kickoff.py` (new)
- `btts_bot/core/scheduling.py` (modified)
- `btts_bot/core/order_execution.py` (modified)
- `btts_bot/core/game_lifecycle.py` (modified — BUY_PLACED->PRE_KICKOFF added to VALID_TRANSITIONS)
- `btts_bot/main.py` (modified — dependency wiring reordered)
- `tests/test_pre_kickoff.py` (new)
- `tests/test_scheduling.py` (modified — fixed test + new schedule_pre_kickoff tests)
- `tests/test_order_execution.py` (modified — fixed stale dates + new scheduler trigger tests)
- `tests/test_main.py` (modified — added PreKickoffService mock + new wiring tests)
