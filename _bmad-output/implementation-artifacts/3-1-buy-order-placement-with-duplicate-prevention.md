# Story 3.1: Buy Order Placement with Duplicate Prevention

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to place limit buy orders at the analysed price for each viable market,
so that it enters positions automatically at optimal prices without risking duplicate orders.

## Acceptance Criteria

1. **Given** the `btts_bot/state/` package from Story 1.1
   **When** the order tracking module is implemented
   **Then** `order_tracker.py` provides an `OrderTracker` class that stores buy and sell orders keyed by `token_id`
   **And** `OrderTracker` provides methods: `record_buy(token_id, order_id, buy_price)`, `record_sell(token_id, order_id)`, `has_buy_order(token_id)`, `has_sell_order(token_id)`, `get_order(token_id)`
   **And** `OrderTracker` is a pure data manager — it holds state and answers queries but never initiates API calls

2. **Given** a market that has been analysed with a valid buy price (GameState: ANALYSED)
   **When** the order execution module processes the market
   **Then** it checks `OrderTracker.has_buy_order(token_id)` first
   **And** if no existing buy order, it fetches the tick size for the token via ClobClientWrapper (cached per-session)
   **And** places a limit buy order on the Polymarket CLOB with the configured share amount (`btts.order_size`)
   **And** the order uses GTD (Good Til Date) type with expiration timestamp calculated as `now + btts.buy_expiration_hours`
   **And** the order ID is recorded in OrderTracker via `record_buy(token_id, order_id, buy_price)`
   **And** the game transitions to BUY_PLACED via GameLifecycle
   **And** an INFO log is emitted: `[Home vs Away] Buy order placed: token=..., price=..., size=...`

3. **Given** `OrderTracker.has_buy_order(token_id)` returns `True`
   **When** order placement is attempted
   **Then** the buy is skipped with a WARNING log: `[Home vs Away] Duplicate buy prevented`
   **And** no API call is made

4. **Given** the ClobClientWrapper returns `None` for the buy order (retries exhausted)
   **When** the placement fails
   **Then** the error is logged at ERROR level
   **And** the game transitions to SKIPPED state
   **And** the bot continues to the next market

## Tasks / Subtasks

- [x] Task 1: Extend `OrderTracker` in `btts_bot/state/order_tracker.py` (AC: #1)
  - [x] Verify existing `record_buy`, `has_buy_order`, `get_buy_order`, `has_sell_order`, `record_sell`, `get_order` methods are present (from Story 2.3)
  - [x] No structural changes needed — the existing `OrderTracker` already satisfies AC #1
  - [x] Confirm `OrderTracker` remains a pure data manager — no API calls

- [x] Task 2: Add `create_order` and `post_order` wrapper methods to `ClobClientWrapper` in `btts_bot/clients/clob.py` (AC: #2)
  - [x] Add `create_buy_order(token_id, price, size, expiration_ts)` method that:
    - Creates `OrderArgs(token_id=token_id, price=price, size=size, side="BUY", expiration=expiration_ts)`
    - Calls `self._client.create_order(order_args)` to build a `SignedOrder`
    - Calls `self._client.post_order(signed_order, orderType=OrderType.GTD)` to post
    - Returns the response (contains order ID) or `None` on failure
  - [x] Decorate with `@with_retry`
  - [x] Import `OrderArgs` and `OrderType` from `py_clob_client.clob_types`

- [x] Task 3: Implement `OrderExecutionService` in `btts_bot/core/order_execution.py` (AC: #2-#4)
  - [x] Create `OrderExecutionService` class with constructor accepting:
    - `clob_client: ClobClientWrapper`
    - `order_tracker: OrderTracker`
    - `market_registry: MarketRegistry`
    - `btts_config: BttsConfig`
  - [x] Implement `place_buy_order(token_id: str, buy_price: float, sell_price: float) -> bool`:
    - Get `MarketEntry` from `market_registry.get(token_id)` for market name and logging
    - Check `order_tracker.has_buy_order(token_id)` — if True, log WARNING and return False (AC #3)
    - Calculate expiration as `int(time.time()) + btts_config.buy_expiration_hours * 3600`
    - Call `clob_client.create_buy_order(token_id, buy_price, btts_config.order_size, expiration_ts)`
    - If result is `None`: log ERROR, transition to SKIPPED, return False (AC #4)
    - Extract order ID from result
    - Call `order_tracker.record_buy(token_id, order_id, buy_price)`
    - Transition lifecycle to BUY_PLACED
    - Log INFO: `[Home vs Away] Buy order placed: token=..., price=..., size=...`
    - Return True
  - [x] Implement `execute_all_analysed(analysis_results: list[AnalysisResult]) -> int`:
    - For each result, look up the market in `market_registry` by iterating markets in ANALYSED state
    - Call `place_buy_order(token_id, result.buy_price, result.sell_price)` for each
    - Return count of successfully placed orders

- [x] Task 4: Wire `OrderExecutionService` into `btts_bot/main.py` (AC: #2)
  - [x] Import `OrderExecutionService` from `btts_bot.core.order_execution`
  - [x] Instantiate `order_execution_service = OrderExecutionService(clob_client, order_tracker, market_registry, config.btts)` after analysis pipeline
  - [x] Call `order_execution_service.execute_all_analysed(analysis_results)` after `analyse_all_discovered()`
  - [x] Log summary: `"Buy orders placed: N out of M analysed markets"`

- [x] Task 5: Write tests in `tests/test_order_execution.py` (AC: #1-#4)
  - [x] Test: `place_buy_order` success path — order placed, recorded in tracker, lifecycle transitions to BUY_PLACED
  - [x] Test: `place_buy_order` duplicate prevention — has_buy_order returns True, WARNING logged, no API call
  - [x] Test: `place_buy_order` API failure — create_buy_order returns None, ERROR logged, lifecycle transitions to SKIPPED
  - [x] Test: `execute_all_analysed` — processes only ANALYSED markets, returns correct count
  - [x] Test: `execute_all_analysed` — skips markets where buy order already exists
  - [x] Test: expiration timestamp calculation is correct (buy_expiration_hours * 3600 added to current time)

- [x] Task 6: Update `tests/test_clob.py` or add clob wrapper tests
  - [x] Test `create_buy_order` constructs correct `OrderArgs` with BUY side and expiration
  - [x] Test `create_buy_order` passes `OrderType.GTD` to `post_order`
  - [x] Test `create_buy_order` returns None when retry exhausted

- [x] Task 7: Update `tests/test_main.py` (AC: #2)
  - [x] Add mock/patch for `OrderExecutionService` in main wiring tests
  - [x] Verify `execute_all_analysed` is called after `analyse_all_discovered()`
  - [x] Verify `analysis_results` are passed to `execute_all_analysed`

- [x] Task 8: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### Critical Context: OrderTracker Already Exists

Story 2.3 already implemented `OrderTracker` in `btts_bot/state/order_tracker.py` with:
- `BuyOrderRecord` dataclass: `token_id`, `order_id`, `buy_price`
- `record_buy(token_id, order_id, buy_price)` — records buy order
- `has_buy_order(token_id)` — duplicate check
- `get_buy_order(token_id)` — returns `BuyOrderRecord | None`
- `has_sell_order(token_id)` — checks sell orders (stub, functional for Story 3.3)
- `record_sell(token_id, order_id)` — records sell order (stub, functional for Story 3.3)
- `get_order(token_id)` — alias for `get_buy_order`

**AC #1 is already satisfied.** Do NOT recreate `OrderTracker` from scratch. The existing implementation is complete for this story's needs.

### py-clob-client Order Creation API (Critical Technical Detail)

The py-clob-client requires a **two-step process** for GTD orders because `create_and_post_order()` hardcodes `OrderType.GTC`:

```python
from py_clob_client.clob_types import OrderArgs, OrderType

# Step 1: Create a signed order
order_args = OrderArgs(
    token_id="0xabc...",
    price=0.48,
    size=30.0,
    side="BUY",
    expiration=int(time.time()) + 12 * 3600,  # 12 hours from now
)
signed_order = client.create_order(order_args)

# Step 2: Post with GTD type
result = client.post_order(signed_order, orderType=OrderType.GTD)
```

**Critical details:**
- `OrderArgs.price` and `OrderArgs.size` are `float` (not string)
- `OrderArgs.side` is `"BUY"` or `"SELL"` (string, not enum)
- `OrderArgs.expiration` is `int` (UNIX timestamp in seconds). Set to `0` for GTC.
- `create_order()` auto-fetches and caches tick_size from server — no need to pass it explicitly
- `create_order()` auto-resolves `neg_risk` and `fee_rate_bps` from server
- `post_order()` returns the API response dict. The order ID is in the response.
- **Do NOT use `create_and_post_order()`** — it doesn't support GTD

### ClobClientWrapper Extension Pattern

Add a high-level method to `ClobClientWrapper` that encapsulates the two-step process:

```python
from py_clob_client.clob_types import OrderArgs, OrderType

@with_retry
def create_buy_order(
    self, token_id: str, price: float, size: float, expiration_ts: int
) -> dict | None:
    """Create and post a GTD limit buy order.

    Returns the API response dict containing the order ID,
    or None if the retry decorator exhausts retries.
    """
    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=float(size),
        side="BUY",
        expiration=expiration_ts,
    )
    signed_order = self._client.create_order(order_args)
    return self._client.post_order(signed_order, orderType=OrderType.GTD)
```

**Important:** The `@with_retry` decorator wraps the entire two-step process. If `create_order` succeeds but `post_order` fails with a retryable error, the retry will re-run both steps (which is correct — signed orders are idempotent for the same nonce).

### Extracting Order ID from Response

The `post_order()` response is a dict. The order ID field is `"orderID"`:

```python
result = clob_client.create_buy_order(token_id, buy_price, order_size, expiration_ts)
if result is None:
    # Retry exhausted
    return False
order_id = result.get("orderID", "")
if not order_id:
    logger.error("%s [%s]: Order posted but no orderID in response", market_name, token_id)
    return False
```

### Expiration Timestamp Calculation

```python
import time

expiration_ts = int(time.time()) + config.btts.buy_expiration_hours * 3600
```

Default `buy_expiration_hours` is 12 (from `BttsConfig`). The expiration is a **UNIX timestamp** (seconds since epoch), NOT a duration.

### OrderExecutionService Design

```python
"""Order execution logic for placing buy/sell orders."""

from __future__ import annotations

import logging
import time

from btts_bot.clients.clob import ClobClientWrapper
from btts_bot.config import BttsConfig
from btts_bot.core.game_lifecycle import GameState
from btts_bot.core.liquidity import AnalysisResult
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker

logger = logging.getLogger(__name__)


class OrderExecutionService:
    """Places buy orders for analysed markets with duplicate prevention."""

    def __init__(
        self,
        clob_client: ClobClientWrapper,
        order_tracker: OrderTracker,
        market_registry: MarketRegistry,
        btts_config: BttsConfig,
    ) -> None:
        self._clob_client = clob_client
        self._order_tracker = order_tracker
        self._market_registry = market_registry
        self._btts = btts_config

    def place_buy_order(self, token_id: str, buy_price: float, sell_price: float) -> bool:
        """Place a limit buy order for a single token.

        Returns True if order was placed successfully, False otherwise.
        """
        entry = self._market_registry.get(token_id)
        market_name = (
            f"[{entry.home_team} vs {entry.away_team}]"
            if entry is not None
            else f"[{token_id}]"
        )

        # Duplicate prevention (AC #3)
        if self._order_tracker.has_buy_order(token_id):
            logger.warning(
                "%s Duplicate buy prevented (token=%s)",
                market_name,
                token_id,
            )
            return False

        # Calculate GTD expiration
        expiration_ts = int(time.time()) + self._btts.buy_expiration_hours * 3600

        # Place buy order via CLOB (AC #2)
        result = self._clob_client.create_buy_order(
            token_id=token_id,
            price=buy_price,
            size=float(self._btts.order_size),
            expiration_ts=expiration_ts,
        )

        if result is None:
            # API failure after retries (AC #4)
            logger.error(
                "%s Buy order failed (retry exhausted): token=%s price=%.4f",
                market_name,
                token_id,
                buy_price,
            )
            if entry is not None:
                entry.lifecycle.transition(GameState.SKIPPED)
            return False

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error(
                "%s Buy order posted but no orderID in response: token=%s",
                market_name,
                token_id,
            )
            if entry is not None:
                entry.lifecycle.transition(GameState.SKIPPED)
            return False

        # Record and transition
        self._order_tracker.record_buy(token_id, order_id, buy_price)
        if entry is not None:
            entry.lifecycle.transition(GameState.BUY_PLACED)
        logger.info(
            "%s Buy order placed: token=%s, price=%.4f, size=%d, order=%s",
            market_name,
            token_id,
            buy_price,
            self._btts.order_size,
            order_id,
        )
        return True

    def execute_all_analysed(self, analysis_results: list[AnalysisResult]) -> int:
        """Place buy orders for all analysed markets.

        Returns count of successfully placed orders.
        """
        placed_count = 0
        for entry in self._market_registry.all_markets():
            if entry.lifecycle.state != GameState.ANALYSED:
                continue
            # Find matching analysis result by token_id
            result = next(
                (r for r in analysis_results if r.token_id == entry.token_id),
                None,
            )
            if result is None:
                continue
            if self.place_buy_order(entry.token_id, result.buy_price, result.sell_price):
                placed_count += 1
        return placed_count
```

**Note on `execute_all_analysed`:** The method needs to match `AnalysisResult` objects to markets. Since `AnalysisResult` does not currently contain a `token_id` field, the simplest approach is to iterate markets in ANALYSED state and pass the corresponding analysis results. There are two options:

**Option A (preferred):** Add `token_id: str` field to `AnalysisResult` dataclass in `liquidity.py` so results can be matched to markets directly. This is a minor, backward-compatible change.

**Option B:** Accept a `dict[str, AnalysisResult]` keyed by `token_id` instead of a list. This requires modifying `analyse_all_discovered()` to return a dict.

**Option C:** Simply iterate markets in ANALYSED state and call `analyse_market` to re-derive prices. This is wasteful.

**Recommendation:** Use Option A — add `token_id` to `AnalysisResult`. Modify `MarketAnalysisPipeline.analyse_market()` to populate it. Then `execute_all_analysed` can match results to markets by token_id.

### AnalysisResult Enhancement (Required Minor Change)

In `btts_bot/core/liquidity.py`, add `token_id` to `AnalysisResult`:

```python
@dataclasses.dataclass
class AnalysisResult:
    token_id: str    # NEW — identifies which market this result belongs to
    buy_price: float
    sell_price: float
    case: str
```

Update `LiquidityAnalyser.analyse()` to accept and pass through `token_id`:
- Already receives `token_id` as a parameter — just include it in the returned `AnalysisResult`

Update `MarketAnalysisPipeline.analyse_market()` to pass `token_id` when constructing `AnalysisResult`:
- Already has `token_id` available — just pass it to `AnalysisResult(..., token_id=token_id)`

**Impact:** Update existing tests in `tests/test_liquidity.py` to include `token_id` in expected `AnalysisResult` objects. This is a minor test update.

### main.py Wiring Pattern

```python
from btts_bot.core.order_execution import OrderExecutionService

# After analysis pipeline:
order_execution_service = OrderExecutionService(
    clob_client, order_tracker, market_registry, config.btts
)

# After analyse_all_discovered():
analysis_results = analysis_pipeline.analyse_all_discovered()
# ...existing logging...

# Buy order placement (FR12)
placed_count = order_execution_service.execute_all_analysed(analysis_results)
logger.info(
    "Buy orders placed: %d out of %d analysed markets",
    placed_count,
    analysed_count,
)
```

### File Locations

**Files to implement/modify:**
- `btts_bot/core/order_execution.py` — **replace stub entirely**: implement `OrderExecutionService`
- `btts_bot/clients/clob.py` — **modify**: add `create_buy_order()` method
- `btts_bot/core/liquidity.py` — **modify**: add `token_id` field to `AnalysisResult`, update `analyse()` and `analyse_market()` to populate it
- `btts_bot/main.py` — **modify**: instantiate `OrderExecutionService`, call `execute_all_analysed()` after analysis
- `tests/test_order_execution.py` — **new file**: comprehensive tests for buy order placement and duplicate prevention
- `tests/test_main.py` — **modify**: add `OrderExecutionService` mock/patch, verify wiring
- `tests/test_liquidity.py` — **modify**: update tests for `token_id` field in `AnalysisResult`

**Files NOT to touch:**
- `btts_bot/state/order_tracker.py` — already complete from Story 2.3 (AC #1 satisfied)
- `btts_bot/state/market_registry.py` — no changes needed
- `btts_bot/core/game_lifecycle.py` — ANALYSED→BUY_PLACED and ANALYSED→SKIPPED transitions already exist
- `btts_bot/config.py` — `BttsConfig` already has `order_size`, `buy_expiration_hours`, `price_diff`
- `btts_bot/constants.py` — `BUY_SIDE`/`SELL_SIDE` already defined (use string `"BUY"` directly per py-clob-client API)
- `btts_bot/retry.py` — no changes needed
- `btts_bot/logging_setup.py` — no changes needed
- `btts_bot/clients/gamma.py` — not involved
- `btts_bot/clients/data_api.py` — stub, not involved
- `btts_bot/state/position_tracker.py` — stub for Story 3.2
- `btts_bot/core/market_discovery.py` — unchanged
- `btts_bot/core/scheduling.py` — unchanged
- `btts_bot/core/reconciliation.py` — stub for Story 5.1

### Lifecycle Transitions to Use

Transitions already defined in `game_lifecycle.py`:
- `ANALYSED → BUY_PLACED` — on successful buy order placement
- `ANALYSED → SKIPPED` — on buy order failure (retry exhaustion)

Both transitions are already in `VALID_TRANSITIONS`. No changes to `game_lifecycle.py` needed.

### Previous Story Intelligence (2.4)

From Story 2.4 completion:
- 186 tests pass (full app suite)
- 219 tests pass (full repo suite including BMAD tests)
- `LiquidityAnalyser` and `MarketAnalysisPipeline` are wired in `main.py`
- `analyse_all_discovered()` returns `list[AnalysisResult]`
- `ClobClientWrapper` is stored in `clob_client` variable in `main.py`
- `AnalysisResult` has fields: `buy_price`, `sell_price`, `case` (no `token_id` yet)
- `ruff check` and `ruff format` must pass with zero issues
- Tests use `pytest` with `MagicMock`, `patch`, and `caplog`
- Both `unittest.TestCase` and plain pytest function styles used in test suite
- `from __future__ import annotations` in `core/` and `state/` modules
- Module-level `logger = logging.getLogger(__name__)` in every module
- Type hints on all function signatures
- `@dataclasses.dataclass` for data records

### Git Intelligence

Last 5 commits:
```
2d148ff epic-2-retro
9ddd5a4 2-4-three-case-orderbook-liquidity-analysis
c8f0393 2-3-btts-no-token-selection-and-market-deduplication
1bdd1d9 2-2-scheduled-daily-market-fetch
a2d9cea 2-1-market-discovery-from-json-data-file
```

Consistent commit message format: story key only as commit message.
Code conventions from recent commits:
- Module docstrings at top of every file
- `from __future__ import annotations` used in `core/` and `state/` modules
- `logger = logging.getLogger(__name__)` at module level
- Type hints on all function signatures
- Constructor dependency injection throughout
- `@dataclasses.dataclass` for data records
- Tests follow pattern: `test_{description}` with docstrings

### Architecture Constraints to Enforce

- `core/` modules contain business logic — receive client instances via DI, never import `requests` or `py-clob-client` directly (except type imports for hints)
- `state/` modules are pure data managers — hold state and answer queries, NEVER initiate API calls
- `clients/` modules are thin I/O wrappers — translate between Polymarket API formats and internal types
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions through `GameLifecycle.transition()` — never set `_state` directly
- `@with_retry` on all API calls in `clients/` — no bare API calls in business logic
- Check `OrderTracker.has_buy_order()` before every buy order placement (duplicate prevention pattern)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from client methods on exhausted retries — caller must handle gracefully

### Architecture Anti-Patterns to Avoid

- Do NOT recreate `OrderTracker` — it already exists and is complete for this story
- Do NOT import `py_clob_client` in `order_execution.py` — only `clients/clob.py` should reference it
- Do NOT use `create_and_post_order()` — it doesn't support GTD orders
- Do NOT place duplicate prevention logic inside `OrderTracker` — it's a data manager, not business logic
- Do NOT modify `GameLifecycle` transitions — ANALYSED→BUY_PLACED and ANALYSED→SKIPPED already exist
- Do NOT make `OrderExecutionService` a state manager — it's business logic in `core/`
- Do NOT catch and silently swallow exceptions — every `except` block must log
- Do NOT use `condition_id` as state key — always use `token_id`

### Testing Pattern

```python
# tests/test_order_execution.py
from unittest.mock import MagicMock, patch
from btts_bot.config import BttsConfig
from btts_bot.core.order_execution import OrderExecutionService
from btts_bot.core.game_lifecycle import GameState
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.market_registry import MarketRegistry


def _make_btts_config(**overrides):
    defaults = {
        "order_size": 30,
        "price_diff": 0.02,
        "min_order_size": 5,
        "buy_expiration_hours": 12,
    }
    defaults.update(overrides)
    return BttsConfig(**defaults)


def _make_service(clob=None, tracker=None, registry=None, btts=None):
    return OrderExecutionService(
        clob_client=clob or MagicMock(),
        order_tracker=tracker or OrderTracker(),
        market_registry=registry or MarketRegistry(),
        btts_config=btts or _make_btts_config(),
    )


def test_place_buy_order_success():
    """Successful buy order: API call made, recorded in tracker, lifecycle transitions."""
    clob = MagicMock()
    clob.create_buy_order.return_value = {"orderID": "order-123"}
    tracker = OrderTracker()
    registry = MarketRegistry()
    # Register a market in ANALYSED state
    entry = registry.register(
        token_id="token-1", condition_id="cond-1", token_ids=["t0", "t1"],
        kickoff_time=datetime(2026, 4, 5, 15, 0), league="EPL",
        home_team="Arsenal", away_team="Chelsea",
    )
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is True
    assert tracker.has_buy_order("token-1")
    assert tracker.get_buy_order("token-1").order_id == "order-123"
    assert entry.lifecycle.state == GameState.BUY_PLACED
    clob.create_buy_order.assert_called_once()


def test_place_buy_order_duplicate_prevented(caplog):
    """Duplicate buy order is prevented with WARNING log and no API call."""
    clob = MagicMock()
    tracker = OrderTracker()
    tracker.record_buy("token-1", "existing-order", 0.48)
    registry = MarketRegistry()
    registry.register(
        token_id="token-1", condition_id="cond-1", token_ids=["t0", "t1"],
        kickoff_time=datetime(2026, 4, 5, 15, 0), league="EPL",
        home_team="Arsenal", away_team="Chelsea",
    )

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    clob.create_buy_order.assert_not_called()
    assert "Duplicate buy prevented" in caplog.text


def test_place_buy_order_api_failure():
    """API failure transitions to SKIPPED and logs ERROR."""
    clob = MagicMock()
    clob.create_buy_order.return_value = None  # Retry exhausted
    tracker = OrderTracker()
    registry = MarketRegistry()
    entry = registry.register(
        token_id="token-1", condition_id="cond-1", token_ids=["t0", "t1"],
        kickoff_time=datetime(2026, 4, 5, 15, 0), league="EPL",
        home_team="Arsenal", away_team="Chelsea",
    )
    entry.lifecycle.transition(GameState.ANALYSED)

    service = _make_service(clob=clob, tracker=tracker, registry=registry)
    result = service.place_buy_order("token-1", buy_price=0.48, sell_price=0.50)

    assert result is False
    assert not tracker.has_buy_order("token-1")
    assert entry.lifecycle.state == GameState.SKIPPED
```

### Scope Boundaries

**In scope:**
- `OrderExecutionService` with buy order placement and duplicate prevention
- `ClobClientWrapper.create_buy_order()` method for GTD limit buy orders
- Adding `token_id` to `AnalysisResult` for market-to-result matching
- Wiring in `main.py` (instantiate service, call after analysis)
- Tests for all acceptance criteria

**Out of scope:**
- Fill accumulation tracking (Story 3.2 — introduces `PositionTracker`)
- Sell order placement (Story 3.3 — extends `OrderTracker` and adds sell logic)
- Tick-size price rounding (handled internally by `py-clob-client` `create_order()`)
- Pre-kickoff consolidation (Story 4.1)
- Game-start recovery (Story 4.2)
- Startup reconciliation (Story 5.1)
- Any changes to scheduling (no polling yet — that's Story 3.2)

### Project Structure Notes

This story adds order execution as the bridge between liquidity analysis and fill tracking:

```
main.py (composition root)
  ├── ClobClientWrapper (clients/)       — MODIFIED: add create_buy_order()
  ├── MarketRegistry (state/)
  ├── OrderTracker (state/)
  ├── GammaClient (clients/)
  ├── MarketDiscoveryService (core/)
  ├── LiquidityAnalyser (core/)          — MODIFIED: AnalysisResult gets token_id
  ├── MarketAnalysisPipeline (core/)
  ├── OrderExecutionService (core/)      — NEW
  └── SchedulerService (core/)
```

Flow after this story:
```
discover_markets() → analyse_all_discovered() → execute_all_analysed() → [future: poll fills]
```

### References

- [Source: epics.md#Story 3.1: Buy Order Placement with Duplicate Prevention] — acceptance criteria
- [Source: architecture.md#Order Execution & Position Mgmt] — `core/order_execution.py`, `state/order_tracker.py`
- [Source: architecture.md#API Client Architecture & Retry Strategy] — ClobClientWrapper, @with_retry
- [Source: architecture.md#State Management Architecture] — OrderTracker duplicate prevention
- [Source: architecture.md#Game Lifecycle Management] — ANALYSED→BUY_PLACED transition
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — duplicate prevention pattern
- [Source: architecture.md#Enforcement Guidelines] — check OrderTracker before every placement
- [Source: prd.md#FR12] — place limit buy orders
- [Source: prd.md#FR15] — prevent duplicate buy orders
- [Source: prd.md#FR22] — in-memory state maintenance (OrderTracker)
- [Source: py_clob_client/clob_types.py] — OrderArgs, OrderType.GTD, TickSize
- [Source: py_clob_client/client.py#create_order] — two-step order creation (create + post separately for GTD)
- [Source: 2-4-three-case-orderbook-liquidity-analysis.md] — AnalysisResult, MarketAnalysisPipeline, 186 tests
- [Source: 2-3-btts-no-token-selection-and-market-deduplication.md] — OrderTracker implementation
- [Source: epic-2-retro-2026-04-02.md#Next Epic Preview] — Story 3.1 should extend existing OrderTracker

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

None — implementation completed without blocking issues.

### Completion Notes List

- `OrderTracker` from Story 2.3 already fully satisfied AC #1; no changes needed to `btts_bot/state/order_tracker.py`.
- `AnalysisResult` did not originally have a `token_id` field; added it to enable `execute_all_analysed()` to match results to markets by token ID.
- `LiquidityAnalyser.analyse()` already received `token_id` as a parameter — only needed to include it in the returned `AnalysisResult`.
- py-clob-client requires a two-step GTD order process: `create_order(OrderArgs)` then `post_order(signed_order, orderType=OrderType.GTD)` — `create_and_post_order()` only supports GTC and cannot be used.
- `test_main_logs_loaded_config_path` used direct patching (not the `_run_main_with_patches` helper) and required a manual `OrderExecutionService` mock addition.
- Full test suite: 213 tests, 0 failures, 0 regressions (up from 186 at Story 2.4 baseline).
- `ruff check` and `ruff format` both pass with zero issues after fixing: unused `patch` import and unused `entry2` variable in `test_order_execution.py`.

### File List

- `btts_bot/clients/clob.py` — MODIFIED: added `create_buy_order()` method with `@with_retry`, imported `OrderArgs` and `OrderType` from `py_clob_client.clob_types`
- `btts_bot/core/liquidity.py` — MODIFIED: added `token_id: str` field to `AnalysisResult` dataclass; updated `LiquidityAnalyser.analyse()` to include `token_id` in returned result
- `btts_bot/core/order_execution.py` — REPLACED stub: full `OrderExecutionService` implementation with `place_buy_order()` and `execute_all_analysed()`
- `btts_bot/main.py` — MODIFIED: added `OrderExecutionService` import, instantiation, `execute_all_analysed()` call, and buy orders summary log
- `tests/test_order_execution.py` — NEW: 18 tests covering all ACs (success path, duplicate prevention, API failure, execute_all_analysed, expiration calculation)
- `tests/test_clob_client.py` — MODIFIED: added `TestClobClientWrapperCreateBuyOrder` class with 4 tests
- `tests/test_main.py` — MODIFIED: added `OrderExecutionService` to `_run_main_with_patches` helper, updated `test_main_logs_loaded_config_path`, added 5 new Story 3.1 wiring tests, updated `AnalysisResult` constructions to include `token_id`
- `tests/test_liquidity.py` — MODIFIED: updated all `AnalysisResult` constructions to include `token_id`; added `token_id` assertion to `test_case_b_returns_l2_price`; updated pipeline tests

### Change Log

| Date | Change |
|------|--------|
| 2026-04-03 | Implemented Story 3.1: Buy Order Placement with Duplicate Prevention. Added `create_buy_order()` to `ClobClientWrapper`, added `token_id` to `AnalysisResult`, implemented full `OrderExecutionService`, wired into `main.py`, added 27 new tests (213 total). All linting passes. |
| 2026-04-03 | AC change: renamed `buy_expiration_hours` → `expiration_hour_offset` (default 1) in `config.py` and `config_btts.example.yaml`; updated expiration calc in `order_execution.py` to `kickoff_ts - offset * 3600`; updated all tests (`test_order_execution.py`, `test_config.py`, `test_liquidity.py`) for new field name and assertion logic. 213/213 tests pass, ruff clean. |
