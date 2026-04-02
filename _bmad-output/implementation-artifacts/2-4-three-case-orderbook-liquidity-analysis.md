# Story 2.4: Three-Case Orderbook Liquidity Analysis

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to analyse each market's orderbook and determine the optimal buy price using the three-case algorithm,
so that it enters at prices informed by real liquidity conditions rather than arbitrary levels.

## Acceptance Criteria

1. **Given** a viable BTTS-No token with `token_id`
   **When** the bot fetches the orderbook via ClobClientWrapper
   **Then** it retrieves the top three bid levels (L1, L2, L3) with their prices and sizes

2. **Given** an orderbook where total bid depth across top 3 levels >= `liquidity.standard_depth` and < `liquidity.deep_book_threshold` (Case A: standard)
   **When** liquidity analysis runs
   **Then** the buy price is set to the L3 bid price
   **And** the game transitions to ANALYSED state via GameLifecycle

3. **Given** an orderbook where total bid depth >= `liquidity.deep_book_threshold` (Case B: deep book)
   **When** liquidity analysis runs
   **Then** the buy price is set to the L2 bid price

4. **Given** an orderbook where total bid depth >= `liquidity.low_liquidity_total` but < `liquidity.standard_depth` (Case C: thin liquidity)
   **When** liquidity analysis runs
   **Then** the buy price is set to L3 price minus `liquidity.tick_offset`

5. **Given** an orderbook where total bid depth < `liquidity.low_liquidity_total`
   **When** liquidity analysis runs
   **Then** the market is skipped with an INFO log message including the market name and depth values
   **And** the game transitions to SKIPPED state

6. **Given** a determined buy price
   **When** sell price derivation runs
   **Then** the sell price is calculated as `buy_price + config.btts.price_diff`, capped at 0.99

7. **Given** the full per-market analysis pipeline (fetch orderbook + analyse + derive prices)
   **When** timed
   **Then** it completes within 10 seconds (NFR11)

## Tasks / Subtasks

- [x] Task 1: Implement `LiquidityAnalyser` in `btts_bot/core/liquidity.py` (AC: #1-#6)
  - [x] Create `AnalysisResult` dataclass with `buy_price: float`, `sell_price: float`, `case: str` fields
  - [x] Create `LiquidityAnalyser` class with constructor accepting `liquidity_config: LiquidityConfig` and `btts_config: BttsConfig`
  - [x] Implement `analyse(orderbook: OrderBookSummary, token_id: str, market_name: str) -> AnalysisResult | None`
  - [x] Extract top 3 bid levels from `orderbook.bids` (L1=index 0, L2=index 1, L3=index 2)
  - [x] Calculate total bid depth as sum of `float(bid.size)` for top 3 levels
  - [x] Implement Case B: deep book check (`total_depth >= deep_book_threshold`) — buy at L2 price
  - [x] Implement Case A: standard check (`total_depth >= standard_depth`) — buy at L3 price
  - [x] Implement Case C: thin liquidity check (`total_depth >= low_liquidity_total`) — buy at L3 price minus tick_offset
  - [x] Implement skip logic: `total_depth < low_liquidity_total` — return `None`
  - [x] Implement sell price derivation: `buy_price + btts_config.price_diff`, capped at `0.99`
  - [x] Handle edge case: fewer than 3 bid levels in orderbook — skip market (treat as insufficient liquidity)
  - [x] Add logging at DEBUG level for orderbook details, INFO level for case determination, INFO level for skip decisions

- [x] Task 2: Implement `MarketAnalysisPipeline` in `btts_bot/core/liquidity.py` (AC: #1-#7)
  - [x] Create `MarketAnalysisPipeline` class with constructor accepting `clob_client: ClobClientWrapper`, `liquidity_analyser: LiquidityAnalyser`, `market_registry: MarketRegistry`
  - [x] Implement `analyse_market(token_id: str) -> AnalysisResult | None`
  - [x] Fetch orderbook via `clob_client.get_order_book(token_id)` — handle `None` return (retry exhaustion)
  - [x] Look up `MarketEntry` from `market_registry.get(token_id)` for market name
  - [x] Call `liquidity_analyser.analyse(orderbook, token_id, market_name)`
  - [x] On success: transition lifecycle to `ANALYSED`, log result
  - [x] On skip: transition lifecycle to `SKIPPED`, log reason
  - [x] On orderbook fetch failure: transition lifecycle to `SKIPPED`, log error
  - [x] Implement `analyse_all_discovered() -> list[AnalysisResult]` — iterate all markets in DISCOVERED state, call `analyse_market` for each

- [x] Task 3: Wire `LiquidityAnalyser` and `MarketAnalysisPipeline` into `btts_bot/main.py` (AC: #1-#7)
  - [x] Store `ClobClientWrapper()` instance in a variable (currently instantiated but discarded)
  - [x] Import `LiquidityAnalyser`, `MarketAnalysisPipeline`, and `AnalysisResult` from `btts_bot.core.liquidity`
  - [x] Instantiate `LiquidityAnalyser(config.liquidity, config.btts)` after config load
  - [x] Instantiate `MarketAnalysisPipeline(clob_client, liquidity_analyser, market_registry)` after state managers
  - [x] Call `analysis_pipeline.analyse_all_discovered()` after `discovery_service.discover_markets()`
  - [x] Log analysis results summary (count analysed, count skipped)

- [x] Task 4: Write tests in `tests/test_liquidity.py` (AC: #1-#7)
  - [x] Test Case B (deep book): total depth >= deep_book_threshold → buy at L2 price
  - [x] Test Case A (standard): total depth >= standard_depth and < deep_book_threshold → buy at L3 price
  - [x] Test Case C (thin liquidity): total depth >= low_liquidity_total and < standard_depth → buy at L3 - tick_offset
  - [x] Test skip: total depth < low_liquidity_total → returns None
  - [x] Test sell price derivation: buy_price + price_diff
  - [x] Test sell price cap: buy_price + price_diff capped at 0.99
  - [x] Test fewer than 3 bids: returns None (skip)
  - [x] Test empty orderbook (no bids): returns None (skip)
  - [x] Test `MarketAnalysisPipeline.analyse_market`: success path with lifecycle transition to ANALYSED
  - [x] Test `MarketAnalysisPipeline.analyse_market`: skip path with lifecycle transition to SKIPPED
  - [x] Test `MarketAnalysisPipeline.analyse_market`: orderbook fetch returns None → skip
  - [x] Test `analyse_all_discovered`: processes only DISCOVERED markets
  - [x] Test boundary values: total depth exactly equal to thresholds

- [x] Task 5: Update `tests/test_main.py` (AC: #7)
  - [x] Update tests to account for ClobClientWrapper being stored in variable
  - [x] Add mock/patch for `LiquidityAnalyser`, `MarketAnalysisPipeline` in main wiring tests
  - [x] Verify `analyse_all_discovered()` is called after discovery

- [x] Task 6: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### Orderbook Data Structure (py-clob-client)

The `ClobClientWrapper.get_order_book(token_id)` method returns an `OrderBookSummary` dataclass from py-clob-client. Critical type details:

```python
# From py_clob_client/clob_types.py
@dataclass
class OrderSummary:
    price: str = None  # STRING, not float! Must convert with float()
    size: str = None    # STRING, not float! Must convert with float()

@dataclass
class OrderBookSummary:
    market: str = None
    asset_id: str = None
    timestamp: str = None
    bids: list[OrderSummary] = None  # Sorted by price DESCENDING (highest first)
    asks: list[OrderSummary] = None  # Sorted by price ASCENDING (lowest first)
    min_order_size: str = None
    tick_size: str = None
    ...
```

**Critical: `price` and `size` are strings!** The analyser must call `float(bid.price)` and `float(bid.size)` to work with numeric values. Failure to convert will cause silent comparison bugs (string comparison vs numeric comparison).

**Bids are sorted by price descending.** L1 (index 0) is the highest bid, L2 (index 1) is next, L3 (index 2) is the lowest of the top 3. The buy price determination uses these specific levels.

### Three-Case Algorithm Detail

The algorithm determines the buy price based on the total bid depth across the top 3 levels:

```
total_depth = sum of size for bids[0], bids[1], bids[2]

if total_depth >= deep_book_threshold:        # Case B: deep book
    buy_price = float(bids[1].price)          # L2 price (more aggressive)
elif total_depth >= standard_depth:            # Case A: standard
    buy_price = float(bids[2].price)          # L3 price (conservative)
elif total_depth >= low_liquidity_total:       # Case C: thin liquidity
    buy_price = float(bids[2].price) - tick_offset  # Even more conservative
else:                                          # Insufficient liquidity
    return None  # Skip market
```

**Why this order?** Case B is checked first because `deep_book_threshold > standard_depth`. If total depth is very large, we can afford the more aggressive L2 price. Case A is the standard case. Case C applies a safety margin on top of L3.

**Config example values:**
- `standard_depth: 1000` (shares)
- `deep_book_threshold: 2000` (shares)
- `low_liquidity_total: 500` (shares)
- `tick_offset: 0.01`

### Sell Price Derivation

```python
sell_price = min(buy_price + btts_config.price_diff, 0.99)
```

The cap at 0.99 is because Polymarket prediction market prices cannot exceed 0.99 (they range from tick_size to 1-tick_size). The `price_diff` is typically 0.02 (2 cents spread).

### ClobClientWrapper Storage Fix in main.py

Currently, `main.py` line 32 instantiates `ClobClientWrapper()` but doesn't store the result:
```python
ClobClientWrapper()  # Auth verification only, DISCARDED
```

This must be changed to:
```python
clob_client = ClobClientWrapper()
```

This is not just a style fix — the liquidity analysis pipeline needs the client to call `get_order_book()`. All existing tests in `test_main.py` will need to account for this change.

### `analyse_all_discovered()` Pattern

The pipeline should iterate all markets and filter for DISCOVERED state:

```python
def analyse_all_discovered(self) -> list[AnalysisResult]:
    results = []
    for entry in self._market_registry.all_markets():
        if entry.lifecycle.state != GameState.DISCOVERED:
            continue
        result = self.analyse_market(entry.token_id)
        if result is not None:
            results.append(result)
    return results
```

This reads lifecycle state directly (read-only property, not mutation), which respects the architecture rule that only `GameLifecycle.transition()` can change state.

### Edge Cases to Handle

1. **`get_order_book()` returns `None`** (retry exhaustion): Skip market, transition to SKIPPED, log ERROR
2. **Fewer than 3 bid levels**: Skip market — the three-case algorithm requires at least 3 levels. Do NOT crash if orderbook has 0, 1, or 2 bids. Transition to SKIPPED, log WARNING with actual bid count.
3. **`orderbook.bids` is `None`**: py-clob-client initializes `bids` to `None` by default. Must check `if orderbook.bids is None or len(orderbook.bids) < 3`.
4. **Empty string prices/sizes**: If `bid.price` or `bid.size` is None or empty string, skip the market. Use a try/except around `float()` conversions.
5. **Negative buy price after tick_offset**: In Case C, if `L3_price - tick_offset <= 0`, skip the market.
6. **All markets already analysed**: `analyse_all_discovered()` should return empty list gracefully, not error.

### `LiquidityAnalyser` Constructor Dependency Injection

```python
class LiquidityAnalyser:
    def __init__(self, liquidity_config: LiquidityConfig, btts_config: BttsConfig) -> None:
        self._liquidity = liquidity_config
        self._btts = btts_config
```

The analyser receives config objects — it does NOT import `config.py` or load config. This follows the constructor dependency injection pattern used throughout the project.

### `MarketAnalysisPipeline` Constructor Dependency Injection

```python
class MarketAnalysisPipeline:
    def __init__(
        self,
        clob_client: ClobClientWrapper,
        liquidity_analyser: LiquidityAnalyser,
        market_registry: MarketRegistry,
    ) -> None:
        self._clob_client = clob_client
        self._analyser = liquidity_analyser
        self._market_registry = market_registry
```

The pipeline orchestrates: fetch orderbook (client) → analyse (analyser) → update state (registry/lifecycle). It is a `core/` module that receives dependencies via DI and never imports `clients/` internals directly.

### Project Structure Notes

This story adds the liquidity analysis as the bridge between market discovery (Story 2.1-2.3) and order execution (Story 3.1):

```
main.py (composition root)
  ├── ClobClientWrapper (clients/)        -- NOW STORED in variable
  ├── MarketRegistry (state/)
  ├── OrderTracker (state/)
  ├── GammaClient (clients/)
  ├── MarketDiscoveryService (core/)
  ├── LiquidityAnalyser (core/)           -- NEW
  ├── MarketAnalysisPipeline (core/)      -- NEW
  └── SchedulerService (core/)
```

Flow after this story:
```
discover_markets() → analyse_all_discovered() → [future: place_buy_orders()]
```

### File Locations

**Files to implement/modify:**
- `btts_bot/core/liquidity.py` — **replace stub entirely**: implement `AnalysisResult`, `LiquidityAnalyser`, `MarketAnalysisPipeline`
- `btts_bot/main.py` — **modify**: store `ClobClientWrapper`, instantiate analyser + pipeline, call `analyse_all_discovered()` after discovery
- `tests/test_liquidity.py` — **new file**: comprehensive tests for all three cases, edge cases, pipeline, lifecycle transitions
- `tests/test_main.py` — **modify**: update for stored ClobClient, add analysis pipeline mock/patch

**Files NOT to touch:**
- `btts_bot/config.py` — `LiquidityConfig` and `BttsConfig` already have all needed fields
- `btts_bot/clients/clob.py` — `get_order_book()` already returns `OrderBookSummary`, no changes needed
- `btts_bot/core/game_lifecycle.py` — transitions DISCOVERED→ANALYSED and DISCOVERED→SKIPPED already exist
- `btts_bot/state/market_registry.py` — `MarketEntry.lifecycle` already accessible, `all_markets()` exists
- `btts_bot/state/order_tracker.py` — not involved in liquidity analysis
- `btts_bot/core/market_discovery.py` — discovery pipeline unchanged; analysis is a separate step
- `btts_bot/core/scheduling.py` — no scheduling changes in this story
- `btts_bot/logging_setup.py` — no logging infrastructure changes
- `btts_bot/retry.py` — retry already applied to `get_order_book()`
- `btts_bot/constants.py` — no new constants needed (thresholds come from config)
- `btts_bot/clients/gamma.py` — not involved
- `btts_bot/clients/data_api.py` — stub, not involved
- `btts_bot/state/position_tracker.py` — stub, not involved
- `btts_bot/core/order_execution.py` — stub, not involved (Story 3.1)
- `btts_bot/core/reconciliation.py` — stub, not involved (Story 5.1)

### Previous Story Intelligence (2.3)

From Story 2.3 completion:
- 147 tests pass after Story 2.3
- `OrderTracker` implemented with `has_buy_order`, `record_buy`, `get_buy_order`
- `MarketDiscoveryService` has 4 constructor params: `gamma_client`, `market_registry`, `leagues`, `order_tracker`
- `ruff check` and `ruff format` must pass with zero issues
- Tests use `pytest` with `MagicMock`, `patch`, and `caplog`
- Both `unittest.TestCase` and plain pytest function styles are used in the test suite
- `from __future__ import annotations` is used in `core/` and `state/` modules
- Module-level `logger = logging.getLogger(__name__)` in every module
- Type hints on all function signatures
- `@dataclasses.dataclass` for data records

### Git Intelligence

Last 5 commits:
```
c8f0393 2-3-btts-no-token-selection-and-market-deduplication
1bdd1d9 2-2-scheduled-daily-market-fetch
a2d9cea 2-1-market-discovery-from-json-data-file
97b2c29 1-6-game-lifecycle-state-machine-and-market-registry
6f6c926 1-5-polymarket-clob-client-authentication
```

Consistent commit message format: story key only as commit message.

### Architecture Constraints to Enforce

- `core/` modules contain business logic — receive client instances via DI, never import `requests` or `py-clob-client` directly
- `state/` modules are pure data managers — `LiquidityAnalyser` does NOT store analysis results in state. It returns them; the pipeline or caller stores/uses them.
- `token_id` is the canonical identifier for all lookups
- All state transitions through `GameLifecycle.transition()` — never set `_state` directly
- `@with_retry` is already on `get_order_book()` in `ClobClientWrapper` — the pipeline should NOT add additional retry logic
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix
- Return `None` from analyse methods on failure/skip — never crash the bot

### Architecture Anti-Patterns to Avoid

- Do NOT import `py_clob_client` types directly in `liquidity.py`. The analyser works with the `OrderBookSummary` returned by `ClobClientWrapper.get_order_book()`. Since `OrderBookSummary` is a type from py-clob-client, importing it for type hints is acceptable, but the analyser should treat the orderbook as a data object, not call any py-clob-client methods.
- Do NOT add retry logic in the pipeline — `get_order_book()` already has `@with_retry`
- Do NOT store analysis results in `MarketRegistry` or any state manager. The `AnalysisResult` is returned to the caller. Future Story 3.1 will use these results to place orders.
- Do NOT modify `GameLifecycle` transitions — DISCOVERED→ANALYSED and DISCOVERED→SKIPPED already exist
- Do NOT make `LiquidityAnalyser` depend on `ClobClientWrapper` — the analyser is pure business logic that receives an already-fetched orderbook

### Testing Pattern

```python
# tests/test_liquidity.py
from unittest.mock import MagicMock
from btts_bot.config import BttsConfig, LiquidityConfig
from btts_bot.core.liquidity import AnalysisResult, LiquidityAnalyser, MarketAnalysisPipeline
from btts_bot.core.game_lifecycle import GameState

def _make_liquidity_config(**overrides):
    defaults = {
        "standard_depth": 1000,
        "deep_book_threshold": 2000,
        "low_liquidity_total": 500,
        "tick_offset": 0.01,
    }
    defaults.update(overrides)
    return LiquidityConfig(**defaults)

def _make_btts_config(**overrides):
    defaults = {
        "order_size": 30,
        "price_diff": 0.02,
        "min_order_size": 5,
        "buy_expiration_hours": 12,
    }
    defaults.update(overrides)
    return BttsConfig(**defaults)

def _make_orderbook(bids):
    """Create a mock OrderBookSummary with the given bids.

    Each bid is a tuple of (price_str, size_str).
    """
    ob = MagicMock()
    ob.bids = [MagicMock(price=p, size=s) for p, s in bids]
    return ob


def test_case_b_deep_book():
    """Case B: total depth >= deep_book_threshold → buy at L2 price."""
    config = _make_liquidity_config(deep_book_threshold=2000)
    btts = _make_btts_config(price_diff=0.02)
    analyser = LiquidityAnalyser(config, btts)
    # 3 levels: 800 + 700 + 600 = 2100 >= 2000 (deep book)
    ob = _make_orderbook([("0.50", "800"), ("0.49", "700"), ("0.48", "600")])
    result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
    assert result is not None
    assert result.buy_price == 0.49  # L2 price
    assert result.case == "B"


def test_case_a_standard():
    """Case A: total depth >= standard_depth and < deep_book_threshold → buy at L3 price."""
    config = _make_liquidity_config(standard_depth=1000, deep_book_threshold=2000)
    btts = _make_btts_config(price_diff=0.02)
    analyser = LiquidityAnalyser(config, btts)
    # 3 levels: 500 + 400 + 300 = 1200 >= 1000 and < 2000 (standard)
    ob = _make_orderbook([("0.50", "500"), ("0.49", "400"), ("0.48", "300")])
    result = analyser.analyse(ob, "token-1", "[Arsenal vs Chelsea]")
    assert result is not None
    assert result.buy_price == 0.48  # L3 price
    assert result.case == "A"
```

### Scope Boundaries

**In scope:**
- `LiquidityAnalyser` with three-case bid-depth analysis
- `AnalysisResult` dataclass
- `MarketAnalysisPipeline` orchestrating fetch → analyse → state transition
- Sell price derivation (buy_price + price_diff, capped at 0.99)
- Wiring in `main.py` (including fixing ClobClientWrapper storage)
- Tests for all cases, edge cases, and pipeline
- Lifecycle transitions: DISCOVERED → ANALYSED and DISCOVERED → SKIPPED

**Out of scope:**
- Buy order placement (Story 3.1)
- Fill tracking (Story 3.2)
- Sell order placement (Story 3.3)
- Scheduling analysis on a recurring basis (analysis runs once after discovery; daily re-analysis is not yet needed)
- Tick-size validation of buy/sell prices (Story 3.1 handles this when building orders)
- Any changes to config models, GameLifecycle transitions, MarketRegistry, or API clients

### References

- [Source: epics.md#Story 2.4: Three-Case Orderbook Liquidity Analysis] — acceptance criteria
- [Source: architecture.md#Liquidity Analysis & Pricing] — `core/liquidity.py` location
- [Source: architecture.md#API Client Architecture & Retry Strategy] — ClobClientWrapper get_order_book
- [Source: architecture.md#State Management Architecture] — domain-separated state managers
- [Source: architecture.md#Game Lifecycle Management] — DISCOVERED → ANALYSED, DISCOVERED → SKIPPED transitions
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — DI pattern, logging levels
- [Source: prd.md#FR9] — three-case orderbook bid-depth analysis
- [Source: prd.md#FR10] — sell price derivation (buy + spread, capped 0.99)
- [Source: prd.md#FR11] — skip unsuitable liquidity markets
- [Source: prd.md#NFR11] — 10-second per-market analysis requirement
- [Source: py_clob_client/clob_types.py] — OrderBookSummary, OrderSummary dataclass (price/size are strings)
- [Source: 2-3-btts-no-token-selection-and-market-deduplication.md#Completion Notes] — 147 tests pass, code conventions

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

No debug issues encountered. Implementation followed Dev Notes specifications exactly.

### Completion Notes List

- Implemented `AnalysisResult` dataclass with `buy_price`, `sell_price`, `case` fields in `btts_bot/core/liquidity.py`
- Implemented `LiquidityAnalyser` with three-case algorithm (B: deep book → L2, A: standard → L3, C: thin → L3-tick_offset, skip: insufficient)
- Handled all edge cases: None bids, fewer than 3 bids, invalid price strings, negative Case C buy price
- Implemented `MarketAnalysisPipeline` orchestrating fetch → analyse → lifecycle transition (DISCOVERED→ANALYSED or DISCOVERED→SKIPPED)
- Fixed `main.py`: `ClobClientWrapper()` now stored in `clob_client` variable (was discarded previously)
- Wired `LiquidityAnalyser` and `MarketAnalysisPipeline` into `main.py`; `analyse_all_discovered()` called after `discover_markets()`
- 34 new tests in `tests/test_liquidity.py` covering all ACs, all 3 cases, boundary values, edge cases, pipeline success/skip/fail paths
- 5 new tests added to `tests/test_main.py` for Story 2.4 wiring; `_run_main_with_patches` updated to patch `LiquidityAnalyser` and `MarketAnalysisPipeline`
- Full regression suite: 186 tests pass (147 prior + 39 new)
- `ruff check` and `ruff format` clean (also fixed pre-existing format issue in `market_discovery.py`)

### File List

- `btts_bot/core/liquidity.py` — replaced stub with `AnalysisResult`, `LiquidityAnalyser`, `MarketAnalysisPipeline`
- `btts_bot/main.py` — stored `ClobClientWrapper`, imported and wired `LiquidityAnalyser`/`MarketAnalysisPipeline`, added analysis log
- `tests/test_liquidity.py` — new file with 34 comprehensive tests
- `tests/test_main.py` — updated `_run_main_with_patches` to patch new classes; added 5 new tests; patched inline test
- `btts_bot/core/market_discovery.py` — ruff format fix only (pre-existing issue)

## Change Log

- 2026-04-02: Implemented Story 2.4 — three-case orderbook liquidity analysis with `LiquidityAnalyser`, `MarketAnalysisPipeline`, main.py wiring, and comprehensive tests (186 tests pass)
