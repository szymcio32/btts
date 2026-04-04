# Story 3.3: Automatic Sell Order Placement on Fill Threshold

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to automatically place sell orders when enough buy fills accumulate,
so that my exit orders are live as early as possible to capture the spread.

## Acceptance Criteria

1. **Given** accumulated fills for a token reach or exceed `btts.min_order_size` (5 shares)
   **When** the fill tracking detects the threshold is crossed
   **Then** it checks `OrderTracker.has_sell_order(token_id)` for duplicate prevention
   **And** if no existing live sell order, it places a limit sell order at `buy_price + btts.price_diff` (capped at 0.99)
   **And** the sell order size equals the total accumulated fill amount
   **And** the order ID is recorded in OrderTracker via `record_sell(token_id, order_id)`
   **And** the game transitions to SELL_PLACED via GameLifecycle
   **And** an INFO log is emitted: `[Home vs Away] Sell order placed: token=..., price=..., size=...`

2. **Given** `OrderTracker.has_sell_order(token_id)` returns `True` (a live sell already covers the position)
   **When** a new sell placement is attempted
   **Then** the sell is skipped with a DEBUG log: `[Home vs Away] Duplicate sell prevented -- live sell exists`
   **And** no API call is made

3. **Given** additional fills arrive after the initial sell order was placed
   **When** the new accumulated total exceeds the existing sell order size
   **Then** the existing sell is cancelled and a new sell is placed for the updated total amount
   **And** OrderTracker is updated with the new sell order ID

## Tasks / Subtasks

- [x] Task 1: Add `create_sell_order` method to `ClobClientWrapper` in `btts_bot/clients/clob.py` (AC: #1)
  - [x] Add `create_sell_order(token_id, price, size)` method with `@with_retry`
  - [x] Use `side="SELL"` in `OrderArgs`
  - [x] Use `OrderType.GTC` (no expiration -- sell stays live until filled or cancelled)
  - [x] Set `expiration=0` in `OrderArgs` for GTC
  - [x] Returns API response dict (contains `orderID`) or `None` on retry exhaustion

- [x] Task 2: Enhance `OrderTracker` sell-order tracking in `btts_bot/state/order_tracker.py` (AC: #1-#3)
  - [x] Create `SellOrderRecord` dataclass: `token_id: str`, `order_id: str`, `sell_price: float`, `sell_size: float`
  - [x] Change `_sell_orders` type from `dict[str, str]` to `dict[str, SellOrderRecord]`
  - [x] Update `record_sell(token_id, order_id, sell_price, sell_size)` -- store full `SellOrderRecord`
  - [x] Update `has_sell_order(token_id)` -- still returns `bool`, unchanged semantics
  - [x] Add `get_sell_order(token_id) -> SellOrderRecord | None`
  - [x] Add `remove_sell_order(token_id)` -- deletes sell record (used before re-placing after additional fills)

- [x] Task 3: Add `place_sell_order` method to `OrderExecutionService` in `btts_bot/core/order_execution.py` (AC: #1-#2)
  - [x] Add `position_tracker: PositionTracker` as new constructor dependency
  - [x] Implement `place_sell_order(token_id: str) -> bool`:
    - Get `BuyOrderRecord` from `order_tracker.get_buy_order(token_id)` for `sell_price`
    - Get `MarketEntry` from `market_registry.get(token_id)` for market name
    - Check `order_tracker.has_sell_order(token_id)` -- if True, log DEBUG and return False (AC #2)
    - Get accumulated fills from `position_tracker.get_accumulated_fills(token_id)` -- this is the sell size
    - Cap sell price at 0.99: `sell_price = min(buy_record.sell_price, 0.99)`
    - Call `clob_client.create_sell_order(token_id, sell_price, accumulated_fills)`
    - If result is `None`: log ERROR, return False (do NOT transition to SKIPPED -- position still exists)
    - Extract `orderID` from result
    - Call `order_tracker.record_sell(token_id, order_id, sell_price, accumulated_fills)`
    - Transition lifecycle to SELL_PLACED
    - Log INFO: `[Home vs Away] Sell order placed: token=..., price=..., size=...`
    - Return True

- [x] Task 4: Add `update_sell_order` method to `OrderExecutionService` (AC: #3)
  - [x] Implement `update_sell_order(token_id: str) -> bool`:
    - Get existing `SellOrderRecord` via `order_tracker.get_sell_order(token_id)`
    - Get current accumulated fills from `position_tracker.get_accumulated_fills(token_id)`
    - If `accumulated_fills <= existing_record.sell_size`: return False (no update needed)
    - Cancel existing sell order via `clob_client.cancel_order(existing_record.order_id)`
    - If cancel returns `None`: log ERROR, return False
    - Remove old sell record: `order_tracker.remove_sell_order(token_id)`
    - Place new sell order at same price for full accumulated amount
    - Record new sell in `order_tracker`
    - Log INFO: `[Home vs Away] Sell order updated: token=..., new_size=..., old_size=...`
    - Return True

- [x] Task 5: Integrate sell placement trigger into `FillPollingService` in `btts_bot/core/fill_polling.py` (AC: #1, #3)
  - [x] Add `order_execution_service: OrderExecutionService` as new constructor dependency
  - [x] After fill accumulation (delta > 0), check `position_tracker.has_reached_threshold(token_id, btts_config.min_order_size)`
  - [x] If threshold reached AND no sell order exists: call `order_execution_service.place_sell_order(token_id)`
  - [x] If threshold reached AND sell order already exists AND accumulated > existing sell size: call `order_execution_service.update_sell_order(token_id)`
  - [x] Also check threshold after processing terminal statuses (fully matched order with partial fills already above threshold)

- [x] Task 6: Update `main.py` wiring (AC: #1)
  - [x] Update `OrderExecutionService` constructor to pass `position_tracker`
  - [x] Update `FillPollingService` constructor to pass `order_execution_service`
  - [x] Ensure circular dependency is avoided: create `OrderExecutionService` first, then `FillPollingService` with it

- [x] Task 7: Write tests for `create_sell_order` in `tests/test_clob_client.py` (AC: #1)
  - [x] Test: `create_sell_order` constructs `OrderArgs` with `side="SELL"`, `expiration=0`
  - [x] Test: `create_sell_order` passes `OrderType.GTC` to `post_order`
  - [x] Test: `create_sell_order` returns `None` when retry exhausted

- [x] Task 8: Write tests for `OrderTracker` sell enhancements in `tests/test_order_tracker.py` (AC: #1-#3)
  - [x] Test: `record_sell` stores `SellOrderRecord` with all fields
  - [x] Test: `has_sell_order` returns True after `record_sell`
  - [x] Test: `get_sell_order` returns `SellOrderRecord` with correct fields
  - [x] Test: `get_sell_order` returns `None` for unknown token
  - [x] Test: `remove_sell_order` removes the record
  - [x] Test: `has_sell_order` returns False after `remove_sell_order`

- [x] Task 9: Write tests for sell placement in `tests/test_order_execution.py` (AC: #1-#3)
  - [x] Test: `place_sell_order` success -- API called, recorded in tracker, lifecycle transitions to SELL_PLACED
  - [x] Test: `place_sell_order` duplicate prevented -- has_sell_order True, DEBUG logged, no API call
  - [x] Test: `place_sell_order` API failure -- returns `None`, ERROR logged, no state transition (stays in FILLING)
  - [x] Test: `place_sell_order` uses sell_price from BuyOrderRecord, capped at 0.99
  - [x] Test: `place_sell_order` uses accumulated fills as sell size (not config.order_size)
  - [x] Test: `update_sell_order` cancels old sell, places new sell with updated size
  - [x] Test: `update_sell_order` no-op when accumulated <= existing size
  - [x] Test: `update_sell_order` cancel failure -- logs ERROR, returns False

- [x] Task 10: Write tests for sell trigger in `tests/test_fill_polling.py` (AC: #1, #3)
  - [x] Test: threshold reached on first fill -- `place_sell_order` called
  - [x] Test: threshold NOT reached -- no sell placement called
  - [x] Test: additional fills after sell exists -- `update_sell_order` called
  - [x] Test: additional fills but accumulated <= existing sell size -- no update
  - [x] Test: fully matched buy order triggers sell if threshold met and no sell exists

- [x] Task 11: Update `tests/test_main.py` for new wiring
  - [x] Update `OrderExecutionService` mock to include `position_tracker`
  - [x] Update `FillPollingService` mock to include `order_execution_service`
  - [x] Add wiring verification tests

- [x] Task 12: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` -- zero issues
  - [x] `uv run ruff format btts_bot/ tests/` -- no changes needed
  - [x] All existing tests still pass (no regressions)

## Dev Notes

### Critical Context: OrderTracker Sell Stubs -- Extend, Do Not Recreate

`btts_bot/state/order_tracker.py` currently has sell-related stubs:

```python
_sell_orders: dict[str, str] = {}  # token_id -> order_id

def has_sell_order(self, token_id: str) -> bool:
    """Stub -- full implementation in Story 3.3."""
    return token_id in self._sell_orders

def record_sell(self, token_id: str, order_id: str) -> None:
    """Stub -- full implementation in Story 3.3."""
    self._sell_orders[token_id] = order_id
    logger.info("Sell order recorded: token=%s order=%s", token_id, order_id)
```

**Required changes:**
1. Create `SellOrderRecord` dataclass with `token_id`, `order_id`, `sell_price`, `sell_size`
2. Change `_sell_orders` type from `dict[str, str]` to `dict[str, SellOrderRecord]`
3. Update `record_sell` signature to accept `sell_price` and `sell_size`
4. Update `has_sell_order` -- semantics unchanged but internally checks `SellOrderRecord` presence
5. Add `get_sell_order(token_id) -> SellOrderRecord | None`
6. Add `remove_sell_order(token_id)` -- needed for cancel-and-replace flow (AC #3)

**Ripple effect:** Any existing code calling `record_sell(token_id, order_id)` must be updated. Currently no code calls it (stubs only), so no ripple effect outside tests.

### Critical Context: Sell Price is Already Stored on Buy Record

`BuyOrderRecord` already has `sell_price: float` computed during liquidity analysis as `buy_price + btts.price_diff`. This was stored at buy-record time (Story 3.2 added it). The sell order placement should use this stored value, capped at 0.99:

```python
buy_record = order_tracker.get_buy_order(token_id)
sell_price = min(buy_record.sell_price, 0.99)
```

Do NOT recompute `sell_price` from `buy_price + price_diff` -- use the pre-computed value from the `BuyOrderRecord`.

### Critical Context: Sell Order Size is Accumulated Fills, NOT Config Order Size

The sell order size must equal the **total accumulated fill amount** from `PositionTracker`, not `config.btts.order_size`. The buy may be partially filled:

```python
sell_size = position_tracker.get_accumulated_fills(token_id)
```

### py-clob-client Sell Order Creation

Sell orders use `GTC` (Good Til Cancelled) type, not `GTD`. They should stay live until filled, cancelled at pre-kickoff, or cancelled at game-start. The creation pattern:

```python
from py_clob_client.clob_types import OrderArgs, OrderType

@with_retry
def create_sell_order(
    self, token_id: str, price: float, size: float
) -> dict | None:
    """Create and post a GTC limit sell order.

    Returns the API response dict containing the order ID,
    or None if the retry decorator exhausts retries.
    """
    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=float(size),
        side="SELL",
        expiration=0,  # GTC -- no expiration
    )
    signed_order = self._client.create_order(order_args)
    return self._client.post_order(signed_order, orderType=OrderType.GTC)
```

**Important:** `expiration=0` signals GTC to the CLOB API. The `create_order()` method auto-fetches tick size (cached) and resolves `neg_risk`/`fee_rate_bps` from server -- no manual tick-size handling needed.

### Fill Polling Integration Point

The sell placement trigger belongs in `FillPollingService._poll_single_order()` after fill accumulation. The logic flow:

```python
# After accumulating new fills (delta > 0):
if delta > 0:
    self._position_tracker.accumulate(token_id, delta)
    # ... existing logging and BUY_PLACED -> FILLING transition ...

    # Check sell threshold
    if self._position_tracker.has_reached_threshold(token_id, self._btts.min_order_size):
        if not self._order_tracker.has_sell_order(token_id):
            # First sell placement
            self._order_execution.place_sell_order(token_id)
        else:
            # Additional fills after initial sell -- check if update needed
            self._order_execution.update_sell_order(token_id)
```

Also check after terminal status handling (fully matched buy order):
```python
# After terminal status marking inactive:
if order_status == "MATCHED":
    # Buy fully filled -- ensure sell exists if threshold met
    if self._position_tracker.has_reached_threshold(token_id, self._btts.min_order_size):
        if not self._order_tracker.has_sell_order(token_id):
            self._order_execution.place_sell_order(token_id)
        else:
            self._order_execution.update_sell_order(token_id)
```

### OrderExecutionService Constructor Change

Add `position_tracker` as a new dependency:

```python
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
```

**Ripple effect:** `main.py` must update the `OrderExecutionService(...)` constructor call to pass `position_tracker`. All existing tests in `tests/test_order_execution.py` that construct `OrderExecutionService` must be updated.

### FillPollingService Constructor Change

Add `order_execution_service` as a new dependency:

```python
def __init__(
    self,
    clob_client: ClobClientWrapper,
    order_tracker: OrderTracker,
    position_tracker: PositionTracker,
    market_registry: MarketRegistry,
    btts_config: BttsConfig,
    order_execution_service: OrderExecutionService,
) -> None:
    # ... existing fields ...
    self._order_execution = order_execution_service
```

**Ripple effect:** `main.py` must update `FillPollingService(...)` constructor call. All existing tests in `tests/test_fill_polling.py` that construct `FillPollingService` must be updated.

**Dependency ordering in main.py:** `OrderExecutionService` must be created BEFORE `FillPollingService` since the latter depends on the former:
```python
order_execution_service = OrderExecutionService(
    clob_client, order_tracker, position_tracker, market_registry, config.btts
)
fill_polling_service = FillPollingService(
    clob_client, order_tracker, position_tracker, market_registry, config.btts,
    order_execution_service,
)
```

### Sell Failure Handling: Do NOT Transition to SKIPPED

If sell order placement fails (API returns `None`), do NOT transition the game to SKIPPED. The position still exists and needs to be managed. Leave the game in FILLING state. The next fill poll cycle will retry the sell placement when it detects the threshold is still met and no sell order exists.

This is different from buy order failure where SKIPPED is appropriate because no position is held.

### AC #3 Cancel-and-Replace Logic

When additional fills arrive after an initial sell is placed, the new accumulated total may exceed the existing sell order size. The update flow:

1. Get existing `SellOrderRecord` -- check `sell_size` vs current `accumulated_fills`
2. If accumulated > existing sell size:
   a. Cancel old sell via `clob_client.cancel_order(existing_order_id)`
   b. Remove old record from `OrderTracker`
   c. Place new sell for full accumulated amount
   d. Record new sell in `OrderTracker`
3. Log the update

**Edge case:** If cancel succeeds but new sell fails, the position temporarily has no sell coverage. This is acceptable -- the next poll cycle will detect no sell exists and retry. Log at ERROR level so the operator is aware.

**Edge case:** If cancel fails, do NOT remove the old sell record or try to place a new one. The old sell order may still be live. Log at ERROR level and retry next poll cycle.

### Lifecycle Transitions to Use

Transitions already defined in `game_lifecycle.py`:
- `FILLING -> SELL_PLACED` -- on successful sell order placement (AC #1)

This transition already exists in `VALID_TRANSITIONS`. No changes to `game_lifecycle.py` needed.

**Note:** The transition should only happen on the FIRST sell placement. The cancel-and-replace flow (AC #3) does not change the game state -- it stays in SELL_PLACED.

### File Locations

**Files to modify:**
- `btts_bot/clients/clob.py` -- ADD: `create_sell_order()` method
- `btts_bot/state/order_tracker.py` -- MODIFY: `SellOrderRecord` dataclass, enhance `record_sell()`, add `get_sell_order()`, `remove_sell_order()`
- `btts_bot/core/order_execution.py` -- MODIFY: add `position_tracker` dependency, add `place_sell_order()`, `update_sell_order()` methods
- `btts_bot/core/fill_polling.py` -- MODIFY: add `order_execution_service` dependency, add sell threshold check after fill accumulation
- `btts_bot/main.py` -- MODIFY: update constructor calls for `OrderExecutionService` and `FillPollingService`
- `tests/test_clob_client.py` -- MODIFY: add `create_sell_order` tests
- `tests/test_order_tracker.py` -- MODIFY: add `SellOrderRecord`, `get_sell_order`, `remove_sell_order` tests, update `record_sell` calls
- `tests/test_order_execution.py` -- MODIFY: add `place_sell_order`/`update_sell_order` tests, update constructor calls
- `tests/test_fill_polling.py` -- MODIFY: add sell trigger tests, update constructor calls
- `tests/test_main.py` -- MODIFY: update constructor mocks/patches

**Files NOT to touch:**
- `btts_bot/core/game_lifecycle.py` -- `FILLING -> SELL_PLACED` already exists
- `btts_bot/state/position_tracker.py` -- `has_reached_threshold()` already implemented
- `btts_bot/state/market_registry.py` -- unchanged
- `btts_bot/config.py` -- `min_order_size` and `price_diff` already exist
- `btts_bot/constants.py` -- `SELL_SIDE` already defined
- `btts_bot/retry.py` -- unchanged
- `btts_bot/logging_setup.py` -- unchanged
- `btts_bot/clients/gamma.py` -- not involved
- `btts_bot/clients/data_api.py` -- stub, not involved
- `btts_bot/core/market_discovery.py` -- unchanged
- `btts_bot/core/liquidity.py` -- unchanged
- `btts_bot/core/scheduling.py` -- unchanged
- `btts_bot/core/reconciliation.py` -- stub for Story 5.1

### Previous Story Intelligence (3.2)

From Story 3.2 completion:
- 258 tests pass (full test suite)
- `PositionTracker` fully implemented with `accumulate()`, `get_accumulated_fills()`, `has_reached_threshold()`
- `FillPollingService` fully implemented with `poll_all_active_orders()` and `_poll_single_order()`
- `OrderTracker` has `BuyOrderRecord` with `sell_price` and `active` fields
- `OrderTracker.mark_inactive()` and `get_active_buy_orders()` work correctly
- Fill polling registered as APScheduler interval job in `main.py`
- `ClobClientWrapper.get_order(order_id)` returns object with `.status`, `.size_matched`, `.original_size`
- `_parse_fixed_math()` converts CLOB fixed-math strings to float shares
- CLOB terminal statuses: `{"MATCHED", "CANCELED", "INVALID", "CANCELED_MARKET_RESOLVED"}`
- `ruff check` and `ruff format` must pass with zero issues
- Tests use pytest with `MagicMock`, `patch`, and `caplog`
- Both `unittest.TestCase` and plain pytest function styles in test suite
- `from __future__ import annotations` in `core/` and `state/` modules
- Module-level `logger = logging.getLogger(__name__)` in every module
- Type hints on all function signatures
- `@dataclasses.dataclass` for data records

### Git Intelligence

Last 5 commits:
```
3f35e45 3-2-fill-accumulation-tracking-via-polling
0b19fd7 3-1-buy-order-placement-with-duplicate-prevention
2d148ff epic-2-retro
9ddd5a4 2-4-three-case-orderbook-liquidity-analysis
c8f0393 2-3-btts-no-token-selection-and-market-deduplication
```

Consistent commit message format: story key only as commit message.

### Architecture Constraints to Enforce

- `core/` modules contain business logic -- receive client instances via DI, never import `requests` or `py-clob-client` directly (use `TYPE_CHECKING` for type hints only)
- `state/` modules are pure data managers -- hold state and answer queries, NEVER initiate API calls or schedule jobs
- `clients/` modules are thin I/O wrappers -- only place that imports `py-clob-client`/`requests`
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` -- never set `_state` directly
- `@with_retry` on all API calls in `clients/` -- no bare API calls in business logic
- Check `OrderTracker.has_sell_order()` before every sell order placement (duplicate prevention pattern)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries -- caller must handle gracefully

### Architecture Anti-Patterns to Avoid

- Do NOT put sell placement logic in `FillPollingService` directly -- it belongs in `OrderExecutionService` (business logic in `core/`, but sell is an execution concern)
- Do NOT put API call logic in `OrderTracker` -- it is a pure data manager in `state/`
- Do NOT import from `btts_bot.clients` at module level in `core/` modules -- use `TYPE_CHECKING` guard
- Do NOT import `py_clob_client` anywhere except `clients/clob.py`
- Do NOT recompute sell_price from buy_price + price_diff -- use `BuyOrderRecord.sell_price`
- Do NOT use `config.btts.order_size` as sell size -- use `position_tracker.get_accumulated_fills()`
- Do NOT transition to SKIPPED on sell failure -- position still needs to be managed
- Do NOT recreate `OrderTracker` from scratch -- extend the existing implementation
- Do NOT transition state on cancel-and-replace -- game stays in SELL_PLACED
- Do NOT use `condition_id` as state key -- always use `token_id`
- Do NOT crash on API errors -- log and continue

### Scope Boundaries

**In scope:**
- `ClobClientWrapper.create_sell_order()` for GTC limit sell orders
- `SellOrderRecord` dataclass and enhanced sell tracking in `OrderTracker`
- `OrderExecutionService.place_sell_order()` and `update_sell_order()` methods
- Sell threshold check and trigger in `FillPollingService`
- Updated wiring in `main.py`
- Comprehensive tests for all acceptance criteria

**Out of scope:**
- Pre-kickoff sell consolidation (Story 4.1 -- cancel sells and re-create at buy price)
- Game-start sell re-placement (Story 4.2 -- detect cancellation and re-place)
- Startup reconciliation (Story 5.1 -- rebuild sell state from API)
- Position pruning (Story 5.4)
- Any changes to `PositionTracker` (already complete)
- Any changes to `GameLifecycle` transitions (FILLING->SELL_PLACED already exists)
- Any changes to `config.py` (min_order_size already exists)

### Project Structure Notes

This story completes the order execution lifecycle within Epic 3:

```
main.py (composition root)
  +-- ClobClientWrapper (clients/)        -- MODIFIED: add create_sell_order()
  +-- MarketRegistry (state/)
  +-- OrderTracker (state/)               -- MODIFIED: SellOrderRecord, get_sell_order, remove_sell_order
  +-- PositionTracker (state/)
  +-- GammaClient (clients/)
  +-- MarketDiscoveryService (core/)
  +-- LiquidityAnalyser (core/)
  +-- MarketAnalysisPipeline (core/)
  +-- OrderExecutionService (core/)       -- MODIFIED: add position_tracker dep, place_sell_order, update_sell_order
  +-- FillPollingService (core/)          -- MODIFIED: add order_execution dep, sell trigger logic
  +-- SchedulerService (core/)
```

Flow after this story:
```
discover -> analyse -> place buy orders -> [poll fills every 30s] -> [threshold met: place sell] -> [more fills: update sell]
```

### References

- [Source: epics.md#Story 3.3: Automatic Sell Order Placement on Fill Threshold] -- acceptance criteria
- [Source: architecture.md#State Management Architecture] -- OrderTracker: duplicate sell prevention, PositionTracker: min-threshold logic
- [Source: architecture.md#Order Execution & Position Mgmt] -- `core/order_execution.py`, `state/order_tracker.py`
- [Source: architecture.md#API Client Architecture & Retry Strategy] -- ClobClientWrapper, @with_retry, returns None on exhaustion
- [Source: architecture.md#Game Lifecycle Management] -- FILLING->SELL_PLACED transition
- [Source: architecture.md#Implementation Patterns & Consistency Rules] -- duplicate prevention, logging patterns, error handling
- [Source: architecture.md#Enforcement Guidelines] -- check OrderTracker before every placement, token_id canonical key
- [Source: prd.md#FR14] -- place sell when fills reach threshold (5 shares)
- [Source: prd.md#FR16] -- prevent duplicate sell orders
- [Source: prd.md#FR10] -- sell price = buy price + spread, capped at 0.99
- [Source: prd.md#FR22] -- in-memory state maintenance
- [Source: config.py#BttsConfig] -- min_order_size (default=5), price_diff already computed into BuyOrderRecord.sell_price
- [Source: game_lifecycle.py#VALID_TRANSITIONS] -- FILLING->SELL_PLACED confirmed
- [Source: order_tracker.py] -- sell stubs: has_sell_order(), record_sell() exist but need enhancement
- [Source: position_tracker.py] -- has_reached_threshold() already implemented
- [Source: 3-2-fill-accumulation-tracking-via-polling.md] -- FillPollingService design, OrderTracker extensions, 258 tests
- [Source: 3-1-buy-order-placement-with-duplicate-prevention.md] -- OrderExecutionService design, create_buy_order pattern
- [Source: py_clob_client/clob_types.py] -- OrderArgs, OrderType.GTC for sell orders

## Dev Agent Record

### Agent Model Used

claude-sonnet-4.6 (github-copilot/claude-sonnet-4.6)

### Debug Log References

N/A

### Completion Notes List

- `_make_service()` in `test_fill_polling.py` now sets `btts.min_order_size = 5.0` on the default mock to prevent `TypeError` from `float >= MagicMock` in `has_reached_threshold`.
- `test_sell_triggered_on_matched_status` pre-accumulates fills to the full amount so delta=0, ensuring `_check_and_trigger_sell` is called exactly once from the MATCHED terminal branch.
- `SellOrderRecord` import removed from `test_order_execution.py` (unused — sell record fields accessed via attribute access without isinstance checks).

### File List

- `btts_bot/clients/clob.py`
- `btts_bot/state/order_tracker.py`
- `btts_bot/core/order_execution.py`
- `btts_bot/core/fill_polling.py`
- `btts_bot/main.py`
- `tests/test_clob_client.py`
- `tests/test_order_tracker.py`
- `tests/test_order_execution.py`
- `tests/test_fill_polling.py`
- `tests/test_main.py`
