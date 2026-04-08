# Story 4.3: Post-Game-Start Sell Verification and Retry Loop

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to verify that sell orders are actually live after game-start re-placement and retry until confirmed,
so that transient API failures at the critical moment don't leave me with an unmanaged position.

## Acceptance Criteria

1. **Given** a sell order was re-placed during game-start recovery
   **When** 1 minute has elapsed since the re-placement
   **Then** the bot queries the CLOB API to verify the sell order exists and is active

2. **Given** the verification confirms the sell order is live
   **When** the check completes
   **Then** the game transitions to RECOVERY_COMPLETE via GameLifecycle
   **And** an INFO log is emitted: `[Home vs Away] Game-start recovery verified -- sell confirmed active`
   **And** the recovery thread exits

3. **Given** the verification finds the sell order is missing or was cancelled
   **When** the check detects the failure
   **Then** the bot immediately re-places the sell order at the buy price
   **And** waits 1 minute and verifies again
   **And** this retry cycle continues until the sell is confirmed active
   **And** each retry is logged at WARNING level: `[Home vs Away] Sell verification failed -- retry #N`

4. **Given** the entire recovery process (detection + re-placement + verification + retries)
   **When** timed from kickoff
   **Then** it completes within 5 minutes under normal conditions (NFR4)

## Tasks / Subtasks

- [x] Task 1: Add sell verification and retry loop to `GameStartService` in `btts_bot/core/game_start.py` (AC: #1-#4)
  - [x] Add `_verify_and_retry_sell(token_id, market_name, entry, buy_price, sell_size) -> None` method
  - [x] After successful sell placement in `_place_sell_and_transition()`, call `_verify_and_retry_sell()` in the same recovery thread (the thread already exists from Story 4.2)
  - [x] Implement 1-minute wait via `time.sleep(60)` then query `clob_client.get_order(order_id)` to check sell order status
  - [x] If sell is active (order status indicates live/open): transition to `RECOVERY_COMPLETE`, log INFO, return
  - [x] If sell is missing, cancelled, or `get_order()` returns None: log WARNING with retry count, remove old sell record, re-place sell at buy_price, record new sell, wait 1 minute, verify again
  - [x] Continue retry loop until sell is confirmed active (no max retry limit -- position safety is paramount)
  - [x] Wrap entire verify loop in try/except so the recovery thread never crashes silently
  - [x] Each retry iteration logs: `[Home vs Away] Sell verification failed -- retry #N`

- [x] Task 2: Handle the case where game-start recovery failed to place the initial sell (AC: #3)
  - [x] In `_place_sell_and_transition()`, when `create_sell_order()` returns None: currently logs ERROR and returns without transitioning
  - [x] Add a retry loop for the initial sell placement: wait 1 minute, attempt sell placement again, continue until successful
  - [x] Once sell is placed, proceed with normal verification loop
  - [x] This ensures NFR4 (5-minute recovery window) is honored even if the first attempt fails

- [x] Task 3: Add `GAME_STARTED -> RECOVERY_COMPLETE` transition verification (AC: #2)
  - [x] Verify `VALID_TRANSITIONS` in `game_lifecycle.py` already includes `GAME_STARTED -> RECOVERY_COMPLETE` (it does -- from existing definition)
  - [x] No code change needed, just verification

- [x] Task 4: Add configurable verification interval (optional enhancement)
  - [x] Add `sell_verify_interval_seconds: int = 60` to `TimingConfig` in `config.py`
  - [x] Use this config value instead of hardcoded 60s in the verification loop
  - [x] Default of 60 matches the AC requirement
  - [x] Add to `config_btts.example.yaml` under `timing` section

- [x] Task 5: Write tests for sell verification and retry loop in `tests/test_game_start.py` (AC: #1-#4)
  - [x] Test: sell placed successfully + verification confirms active -> transition to RECOVERY_COMPLETE, INFO log emitted
  - [x] Test: sell placed successfully + verification finds order missing -> re-place sell, wait, verify again, second check succeeds -> RECOVERY_COMPLETE
  - [x] Test: sell placed successfully + verification finds order cancelled -> re-place sell, retry loop
  - [x] Test: sell placed successfully + get_order returns None (API error) -> treat as failed, re-place sell, retry
  - [x] Test: initial sell placement fails (returns None) -> retry loop places sell, then verification succeeds
  - [x] Test: multiple retries before success (simulate 3 failures then success) -> verify retry count in log messages
  - [x] Test: re-placed sell also fails (create_sell_order returns None repeatedly then succeeds) -> resilient retry
  - [x] Test: verify `time.sleep` is called with correct interval (mock time.sleep)
  - [x] Test: recovery thread exception does not crash (outer try/except in handle_game_start catches it)

- [x] Task 6: Update existing tests for modified `_place_sell_and_transition` behavior
  - [x] Update existing `GameStartService` tests that mock `_place_sell_and_transition` or verify its behavior
  - [x] Ensure tests that don't need the verify loop mock `time.sleep` to avoid blocking
  - [x] Update any tests that assert `_place_sell_and_transition` returns immediately after sell placement

- [x] Task 7: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` -- zero issues
  - [x] `uv run ruff format btts_bot/ tests/` -- no changes needed
  - [x] All existing tests still pass (406 baseline, no regressions)

## Dev Notes

### Critical Context: This Story Completes the Game-Start Recovery Safety Chain

Story 4.2 created `GameStartService` which detects Polymarket's automatic order cancellation at game start and re-places sell orders. However, Story 4.2 explicitly left a gap: **what if the re-placed sell order also fails?** The `_place_sell_and_transition()` method currently logs an ERROR and returns without transitioning when `create_sell_order()` returns None, with the comment "Story 4.3 retry will handle."

This story closes that gap by adding:
1. A retry loop for initial sell placement failures
2. A 1-minute verification check after successful sell placement
3. A retry-until-confirmed loop when verification fails

**This is the most critical safety mechanism in the entire bot.** After this story, the bot guarantees: every filled position will have an active sell order after game start, regardless of transient API failures.

### Critical Context: Verification Logic -- What "Active" Means

The `clob_client.get_order(order_id)` method returns the order object from Polymarket. The key field to check is the order status. Based on Polymarket CLOB API:

- **LIVE** / **OPEN**: Order is active on the book -- verification passes
- **MATCHED**: Order was filled -- also good (position was sold)
- **CANCELLED**: Order was cancelled -- verification fails, need to re-place
- **None response**: API error (retries exhausted) -- treat as failed, re-place defensively

```python
def _is_sell_active(self, order_id: str, market_name: str) -> bool:
    """Check if a sell order is still active on the CLOB.

    Returns True if the order is live/open or matched (filled).
    Returns False if cancelled, missing, or API error.
    """
    order_data = self._clob_client.get_order(order_id)
    if order_data is None:
        logger.warning(
            "%s Sell verification: get_order returned None for order=%s",
            market_name,
            order_id,
        )
        return False

    # py-clob-client returns order data with various status fields
    # Check the order_status or status field
    status = ""
    if hasattr(order_data, "status"):
        status = order_data.status
    elif isinstance(order_data, dict):
        status = order_data.get("status", "")

    if status.upper() in ("LIVE", "OPEN", "MATCHED"):
        return True

    logger.warning(
        "%s Sell verification: order=%s has status=%s (not active)",
        market_name,
        order_id,
        status,
    )
    return False
```

### Critical Context: Verification Loop Architecture

The verify-and-retry loop runs **in the same dedicated daemon thread** that Story 4.2 created for game-start recovery. No new threads are needed. The flow is:

```
APScheduler DateTrigger (kickoff) 
  -> _launch_game_start_thread() [spawns daemon Thread]
    -> handle_game_start(token_id) [try/except wrapper]
      -> _do_game_start_recovery(token_id) [state dispatch]
        -> _handle_pre_kickoff_state / _handle_sell_placed_state / etc.
          -> _place_sell_and_transition()
            -> Place sell via CLOB
            -> If sell fails: retry loop until sell succeeds
            -> Record sell, transition to GAME_STARTED
            -> _verify_and_retry_sell()
              -> sleep(60)
              -> Check sell status via get_order()
              -> If active: transition RECOVERY_COMPLETE, return
              -> If not active: re-place sell, sleep(60), check again
              -> Loop until confirmed
```

The entire verification loop runs within `handle_game_start()` which has the outer try/except. The thread is daemon=True so bot shutdown won't hang.

### Critical Context: Modifying _place_sell_and_transition()

The current `_place_sell_and_transition()` in `game_start.py` (lines 261-326) does:
1. Place sell via CLOB
2. If None: log ERROR, return (no transition)
3. Record sell in OrderTracker
4. Transition to GAME_STARTED
5. Log success

Story 4.3 modifies this to:
1. Place sell via CLOB
2. If None: enter retry loop (wait 60s, try again) until sell succeeds
3. Record sell in OrderTracker
4. Transition to GAME_STARTED
5. Log success
6. Call `_verify_and_retry_sell()` -- the new verification loop

**Key design decision:** The sell placement retry and the verification retry are separate loops:
- **Sell placement retry:** Handles the case where `create_sell_order()` returns None. Retries until the sell is placed.
- **Sell verification retry:** Handles the case where the sell was placed but later got cancelled (or we can't confirm it's active). Verifies and re-places if needed.

### Critical Context: Sell Verification Interval

The AC specifies "1 minute has elapsed since the re-placement." This maps to `time.sleep(60)` in the recovery thread. The thread is already daemon=True, so it won't block shutdown.

For testability, extract the interval as a configurable value in `TimingConfig`:

```python
class TimingConfig(BaseModel):
    daily_fetch_hour_utc: int
    fill_poll_interval_seconds: int = 30
    pre_kickoff_minutes: int = 10
    sell_verify_interval_seconds: int = 60  # NEW -- Story 4.3
```

Pass `TimingConfig` to `GameStartService` constructor so the interval is configurable and testable (tests can use 0 or very small values).

### Critical Context: Constructor Change for GameStartService

`GameStartService.__init__` currently takes: `clob_client, order_tracker, position_tracker, market_registry`. Story 4.3 adds `timing_config: TimingConfig` for the verification interval:

```python
class GameStartService:
    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        position_tracker: PositionTracker,
        market_registry: MarketRegistry,
        timing_config: TimingConfig,  # NEW
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._position_tracker = position_tracker
        self._market_registry = market_registry
        self._timing = timing_config
        self._inflight_lock = threading.Lock()
        self._inflight_tokens: set[str] = set()
```

**Ripple effect:** `main.py` must update `GameStartService(...)` to include `config.timing`. All tests in `tests/test_game_start.py` must update constructor calls.

### Critical Context: No Maximum Retry Limit

The AC says "this retry cycle continues until the sell is confirmed active." There is no max retry count. Position safety is paramount -- the bot must keep trying until:
1. The sell is confirmed active (RECOVERY_COMPLETE), OR
2. The sell is confirmed filled/matched (also RECOVERY_COMPLETE), OR
3. The bot is shut down (daemon thread terminates)

However, to prevent infinite tight loops on persistent failures, each retry cycle waits the full verification interval (60s default). This means ~5 retries in the 5-minute NFR4 window.

### Critical Context: Order ID Tracking Across Retries

When the verification loop detects a cancelled sell and re-places it, the new order has a NEW order ID. The loop must:
1. Remove old sell record from OrderTracker
2. Place new sell via `create_sell_order()`
3. Record new sell in OrderTracker (use `record_sell_if_absent()` for thread safety, or `remove_sell_order()` then `record_sell()`)
4. Use the NEW order ID for the next verification check

```python
def _verify_and_retry_sell(
    self,
    token_id: str,
    market_name: str,
    entry: object,
    buy_price: float,
    sell_size: float,
) -> None:
    sell_record = self._order_tracker.get_sell_order(token_id)
    if sell_record is None:
        logger.error(
            "%s Verify: no sell record for token=%s after placement",
            market_name, token_id,
        )
        return

    retry_count = 0
    current_order_id = sell_record.order_id

    while True:
        time.sleep(self._timing.sell_verify_interval_seconds)

        if self._is_sell_active(current_order_id, market_name):
            entry.lifecycle.transition(GameState.RECOVERY_COMPLETE)
            logger.info(
                "%s Game-start recovery verified -- sell confirmed active",
                market_name,
            )
            return

        # Sell is not active -- re-place
        retry_count += 1
        logger.warning(
            "%s Sell verification failed -- retry #%d",
            market_name,
            retry_count,
        )

        self._order_tracker.remove_sell_order(token_id)
        sell_price = min(buy_price, 0.99)

        result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
        if result is None:
            logger.error(
                "%s Sell re-placement failed on retry #%d for token=%s",
                market_name, retry_count, token_id,
            )
            # Don't return -- keep looping, next iteration will try again
            continue

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Sell re-placement returned no orderID on retry #%d",
                market_name, retry_count,
            )
            continue

        self._order_tracker.record_sell(token_id, order_id, sell_price, sell_size)
        current_order_id = order_id
        # Loop continues -- will sleep and verify the new sell
```

### Critical Context: Handling Initial Sell Placement Failure

Currently in `_place_sell_and_transition()` (line 278), when `create_sell_order()` returns None, the method logs ERROR and returns. Story 4.3 must change this to retry:

```python
# Replace the early return on failure with a retry loop:
sell_price = min(buy_price, 0.99)
result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)

retry_count = 0
while result is None:
    retry_count += 1
    logger.warning(
        "%s Game-start recovery: sell placement failed, retrying #%d (token=%s)",
        market_name, retry_count, token_id,
    )
    time.sleep(self._timing.sell_verify_interval_seconds)
    result = self._clob_client.create_sell_order(token_id, sell_price, sell_size)
```

### Lifecycle Transitions

Transitions used by this story:

**Existing transitions (no additions needed):**
- `GAME_STARTED -> RECOVERY_COMPLETE` -- already defined in `VALID_TRANSITIONS`
- `GAME_STARTED -> DONE` -- already defined

No new transitions required. The `RECOVERY_COMPLETE` transition was already defined in Story 1.6 when the lifecycle was created.

### File Locations

**Files to modify:**
- `btts_bot/core/game_start.py` -- MODIFY: add `_verify_and_retry_sell()` method, add `_is_sell_active()` helper, modify `_place_sell_and_transition()` to retry on failure and call verification loop, add `timing_config` to constructor
- `btts_bot/config.py` -- MODIFY: add `sell_verify_interval_seconds: int = 60` to `TimingConfig`
- `btts_bot/main.py` -- MODIFY: pass `config.timing` to `GameStartService` constructor
- `config_btts.example.yaml` -- MODIFY: add `sell_verify_interval_seconds: 60` under `timing`
- `tests/test_game_start.py` -- MODIFY: update constructor calls to include `timing_config`, add verification/retry tests
- `tests/test_main.py` -- MODIFY: update `GameStartService` mock constructor for new parameter

**Files NOT to touch:**
- `btts_bot/core/game_lifecycle.py` -- no new transitions needed
- `btts_bot/core/scheduling.py` -- unchanged
- `btts_bot/core/order_execution.py` -- unchanged
- `btts_bot/core/pre_kickoff.py` -- unchanged
- `btts_bot/core/fill_polling.py` -- unchanged
- `btts_bot/state/order_tracker.py` -- unchanged (all needed methods exist)
- `btts_bot/state/position_tracker.py` -- unchanged
- `btts_bot/state/market_registry.py` -- unchanged
- `btts_bot/clients/clob.py` -- unchanged (`get_order()` already exists)
- `btts_bot/retry.py` -- unchanged
- `btts_bot/logging_setup.py` -- unchanged

### Previous Story Intelligence (4.2)

From Story 4.2 completion notes:
- 371 tests pass (now 406 after subsequent work), ruff check and format clean
- `GameStartService` follows `PreKickoffService` pattern: same constructor deps, same state-dispatch pattern
- Thread-safety locks added to all state managers and `ClobClientWrapper` in Story 4.2 -- already in place
- `record_sell_if_absent()` atomic method exists on `OrderTracker` for thread-safe sell recording
- `_place_sell_and_transition()` currently logs ERROR and returns when sell fails -- this is the gap Story 4.3 fills
- `_inflight_lock` + `_inflight_tokens` prevent duplicate recovery threads for the same game
- `handle_game_start()` has outer try/except that catches all exceptions -- the verification loop runs within this protection
- `remove_sell_order()` exists and is thread-safe (locked) -- use before re-placing
- `InvalidTransitionError` handling exists in `_place_sell_and_transition()` for race conditions where another thread already transitioned

### Git Intelligence

Last 2 commits:
```
33ec73f 4-2-game-start-order-cancellation-detection-and-sell-re-placement
5d88a3c 4-1-pre-kickoff-sell-consolidation-and-buy-cancellation
```

Consistent commit message format: story key only.

### Architecture Constraints to Enforce

- `core/` modules contain business logic -- receive client instances via DI, never import `requests` or `py-clob-client` directly
- `state/` modules are pure data managers -- hold state and answer queries, NEVER initiate API calls
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` -- never set `_state` directly
- `@with_retry` on all API calls in `clients/` -- no bare API calls in business logic
- Check `OrderTracker` state before every order operation (duplicate prevention pattern)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries -- caller must handle gracefully
- `threading.Lock` on all state managers and `ClobClientWrapper` (added in Story 4.2)
- Sell at `buy_price` (breakeven), NOT `buy_price + spread` -- same as Story 4.1 and 4.2
- Recovery thread is `daemon=True` -- don't block shutdown

### Architecture Anti-Patterns to Avoid

- Do NOT add a max retry limit to the verification loop -- position safety is paramount, keep retrying
- Do NOT hold locks during `time.sleep()` -- sleep is I/O waiting, locks protect in-memory state only
- Do NOT reuse `OrderExecutionService.place_sell_order()` -- follow Story 4.1/4.2 pattern of direct `clob_client.create_sell_order()` calls
- Do NOT import `py_clob_client` anywhere except `clients/clob.py`
- Do NOT crash on API errors in the verification loop -- log and retry
- Do NOT use `buy_record.sell_price` (that's buy_price + spread) -- use `buy_record.buy_price`
- Do NOT create new threads for verification -- reuse the existing game-start recovery thread
- Do NOT block the main loop or APScheduler thread pool -- verification runs in the dedicated daemon thread

### Scope Boundaries

**In scope:**
- `_verify_and_retry_sell()` method on `GameStartService` for 1-minute verification + retry loop
- `_is_sell_active()` helper to check order status via CLOB API
- Modification of `_place_sell_and_transition()` to retry initial sell placement on failure
- `sell_verify_interval_seconds` config in `TimingConfig` (default 60s)
- `timing_config` parameter added to `GameStartService` constructor
- Transition to `RECOVERY_COMPLETE` on verified sell
- Comprehensive tests for verification and retry scenarios

**Out of scope:**
- Startup reconciliation (Story 5.1) -- rebuild state and re-schedule triggers from API
- State pruning (Story 5.4)
- Any changes to `SchedulerService` -- no new scheduling needed
- Any changes to `PreKickoffService` -- works correctly as-is
- Any changes to `FillPollingService` -- stops polling once game reaches GAME_STARTED
- New lifecycle transitions -- `GAME_STARTED -> RECOVERY_COMPLETE` already exists
- Max retry limit on verification -- not in scope per AC
- Graceful shutdown signaling for the verification loop -- daemon thread handles this

### Project Structure Notes

This story completes the game-start recovery chain within the existing architecture:

```
main.py (composition root)
  +-- GameStartService (core/)            -- MODIFIED: adds verification loop, timing_config dep
  +-- TimingConfig (config.py)            -- MODIFIED: adds sell_verify_interval_seconds
```

Flow after this story (complete Epic 4 chain):
```
discover -> analyse -> place buy orders
  -> [register pre-kickoff trigger + game-start trigger per game]
  -> [poll fills every 30s] -> [threshold met: place sell]
  -> [kickoff - N minutes: pre-kickoff consolidation]
  -> [kickoff: game-start recovery: re-place sell at buy_price]
  -> [+60s: verify sell is active on CLOB]
  -> [if active: RECOVERY_COMPLETE, thread exits]
  -> [if not active: re-place sell, wait 60s, verify again, loop until confirmed]
```

### References

- [Source: epics.md#Story 4.3: Post-Game-Start Sell Verification and Retry Loop] -- acceptance criteria
- [Source: epics.md#Epic 4 Overview] -- epic objectives, zero unmanaged positions
- [Source: architecture.md#Application Architecture & Process Model] -- synchronous main loop + dedicated threads for game-start recovery
- [Source: architecture.md#Scheduling & Timing Strategy] -- APScheduler BackgroundScheduler
- [Source: architecture.md#Game Lifecycle Management] -- RECOVERY_COMPLETE state
- [Source: architecture.md#Process Patterns - Error Handling] -- @with_retry returns None, caller handles gracefully
- [Source: prd.md#FR21] -- verify sell order placement 1 minute after game-start re-creation and retry until confirmed
- [Source: prd.md#NFR4] -- game-start sell re-creation within 5 minutes
- [Source: prd.md#NFR1] -- 14-day continuous uptime
- [Source: prd.md#NFR2] -- no single API failure may terminate the bot
- [Source: 4-2-game-start-order-cancellation-detection-and-sell-re-placement.md] -- previous story patterns, GameStartService architecture, 371->406 tests baseline
- [Source: game_start.py#_place_sell_and_transition] -- current gap: returns on sell failure instead of retrying
- [Source: game_lifecycle.py#VALID_TRANSITIONS] -- GAME_STARTED -> RECOVERY_COMPLETE already defined
- [Source: order_tracker.py#record_sell_if_absent] -- thread-safe atomic sell recording
- [Source: clob.py#get_order] -- existing method for checking order status

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

- Story baseline was 373 tests (dev notes said 406 — discrepancy in story doc). 373 → 384 after this story (+11 tests).
- `sell_verify_interval_seconds` Field constraint set to `gt=0` (consistent with other timing fields). Tests use `autouse` fixture patching `time.sleep` to avoid real delays.
- When re-placement fails (returns None) in `_verify_and_retry_sell`, `current_order_id` remains the old (cancelled) ID. The loop continues with stale ID — next `get_order` will fail again (CANCELLED), triggering another re-placement attempt. This is safe: eventually re-placement succeeds and `current_order_id` is updated.

### Completion Notes List

- ✅ Added `sell_verify_interval_seconds: int = 60` to `TimingConfig` in `config.py` with `gt=0` validation
- ✅ Updated `config_btts.example.yaml` with `sell_verify_interval_seconds: 60` under timing section
- ✅ Added `timing_config: TimingConfig` parameter to `GameStartService.__init__`, stored as `self._timing`
- ✅ Added `import time` to `game_start.py`
- ✅ Added `_is_sell_active(order_id, market_name) -> bool` helper: checks LIVE/OPEN/MATCHED statuses
- ✅ Added `_verify_and_retry_sell(token_id, market_name, entry, buy_price, sell_size) -> None`: infinite retry loop with 1-min sleep, transitions to RECOVERY_COMPLETE on success
- ✅ Modified `_place_sell_and_transition()`: replaced early-return-on-None with retry loop; calls `_verify_and_retry_sell()` after successful placement + GAME_STARTED transition
- ✅ Updated `main.py`: `GameStartService(clob_client, order_tracker, position_tracker, market_registry, config.timing)`
- ✅ Rewrote `tests/test_game_start.py`: added `autouse` `no_sleep` fixture (monkeypatches `time.sleep`); updated all existing tests to expect RECOVERY_COMPLETE (not GAME_STARTED) as final state; added 11 new verification/retry tests
- ✅ Updated `tests/test_main.py`: added assertion that `GameStartService` receives `config.timing` as 5th positional arg
- ✅ All 384 tests pass (373 baseline + 11 new), zero ruff issues

### File List

- `btts_bot/config.py` — MODIFIED: added `sell_verify_interval_seconds: int = Field(default=60, gt=0)` to `TimingConfig`
- `btts_bot/core/game_start.py` — MODIFIED: added `import time`, `timing_config` constructor param, `_is_sell_active()`, `_verify_and_retry_sell()`, modified `_place_sell_and_transition()` with retry + verification call
- `btts_bot/main.py` — MODIFIED: pass `config.timing` to `GameStartService`
- `config_btts.example.yaml` — MODIFIED: added `sell_verify_interval_seconds: 60` under timing
- `tests/test_game_start.py` — MODIFIED: autouse `no_sleep` fixture, updated constructor calls, updated state assertions (GAME_STARTED → RECOVERY_COMPLETE), 11 new verification/retry tests
- `tests/test_main.py` — MODIFIED: updated `test_main_game_start_service_receives_correct_deps` to assert `config.timing` is 5th arg

### Change Log

- 2026-04-07: Implemented Story 4.3 — post-game-start sell verification and retry loop. Added `sell_verify_interval_seconds` config, `timing_config` DI to `GameStartService`, `_is_sell_active()` and `_verify_and_retry_sell()` methods, modified `_place_sell_and_transition()` to retry initial placement and call verification loop. 11 new tests added (373 → 384 total).
