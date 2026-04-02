# Story 2.3: BTTS-No Token Selection and Market Deduplication

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to correctly identify the "No" outcome token from each BTTS market and skip markets already being processed,
so that it targets the right token and never double-processes a market.

## Acceptance Criteria

1. **Given** a discovered BTTS market with multiple outcome tokens
   **When** the bot processes the market
   **Then** it identifies and selects the "No" outcome token using the token metadata
   **And** records the `token_id` as the canonical identifier in MarketRegistry

2. **Given** a market whose `token_id` already exists in MarketRegistry (from current session or API reconciliation)
   **When** the bot encounters it during discovery
   **Then** it skips the market with a DEBUG log message
   **And** no duplicate entry is created in MarketRegistry

3. **Given** a market whose `token_id` has an existing buy order in OrderTracker
   **When** the bot encounters it during discovery
   **Then** it skips the market with an INFO log message indicating a buy order already exists

## Tasks / Subtasks

- [x] Task 1: Add `OrderTracker` read-only query interface to `btts_bot/state/order_tracker.py` (AC: #3)
  - [x] Implement `OrderTracker` class with `has_buy_order(token_id: str) -> bool` method
  - [x] Implement internal storage `_buy_orders: dict[str, BuyOrderRecord]` keyed by `token_id`
  - [x] Implement `BuyOrderRecord` dataclass with `token_id: str`, `order_id: str`, `buy_price: float` fields
  - [x] Implement `record_buy(token_id: str, order_id: str, buy_price: float) -> None` method (needed for tests and future Story 3.1)
  - [x] Implement `has_sell_order(token_id: str) -> bool` (returns False — stub for Story 3.3)
  - [x] Implement `record_sell(token_id: str, order_id: str) -> None` (stub — raises `NotImplementedError` or is a no-op for now)
  - [x] Implement `get_buy_order(token_id: str) -> BuyOrderRecord | None` query method
  - [x] Add module-level logger
  - [x] `OrderTracker` is a pure data manager — holds state and answers queries, never initiates API calls

- [x] Task 2: Inject `OrderTracker` into `MarketDiscoveryService` and add buy-order deduplication (AC: #3)
  - [x] Add `order_tracker: OrderTracker` parameter to `MarketDiscoveryService.__init__()`
  - [x] After the `is_processed(token_id)` check, add `order_tracker.has_buy_order(token_id)` check
  - [x] If buy order exists: skip with INFO log `"[Home vs Away] Buy order already exists, skipping (token=...)"` and `continue`
  - [x] Fix bug on line 163: `except ValueError, TypeError:` -> `except (ValueError, TypeError):`

- [x] Task 3: Wire `OrderTracker` into `btts_bot/main.py` (AC: #3)
  - [x] Import `OrderTracker` from `btts_bot.state.order_tracker`
  - [x] Instantiate `order_tracker = OrderTracker()` alongside `market_registry` in state managers initialization
  - [x] Pass `order_tracker` to `MarketDiscoveryService` constructor
  - [x] Log `OrderTracker` in state managers initialized message

- [x] Task 4: Write tests (AC: #1-#3)
  - [x] `tests/test_order_tracker.py` (new file):
    - [x] Test: `has_buy_order()` returns False for unknown token_id
    - [x] Test: `has_buy_order()` returns True after `record_buy()`
    - [x] Test: `get_buy_order()` returns None for unknown token_id
    - [x] Test: `get_buy_order()` returns `BuyOrderRecord` after `record_buy()`
    - [x] Test: `has_sell_order()` returns False (stub behavior)
    - [x] Test: `record_buy()` overwrites existing buy order for same token_id (or raises — decide based on architecture)
  - [x] `tests/test_market_discovery.py` (update existing):
    - [x] Test: skips market when `order_tracker.has_buy_order(token_id)` returns True, with INFO log
    - [x] Test: processes market normally when `has_buy_order()` returns False
    - [x] Update all existing `MarketDiscoveryService` tests to pass `order_tracker` parameter
  - [x] `tests/test_main.py` (update existing):
    - [x] Update tests to account for `OrderTracker` instantiation and injection

- [x] Task 5: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### Critical Context: AC #1 and #2 Are Already Implemented

Story 2.1 already implemented the core BTTS-No token selection and MarketRegistry deduplication logic in `btts_bot/core/market_discovery.py`:

- **AC #1 (No token selection):** Lines 14-15 define `BTTS_NO_TOKEN_INDEX = 1` and line 84 extracts `no_token_id = token_ids[BTTS_NO_TOKEN_INDEX]`. The "No" token is correctly selected as index 1 from the `token_ids` array.
- **AC #2 (MarketRegistry deduplication):** Lines 87-94 check `self._registry.is_processed(no_token_id)` before registration, skipping with a DEBUG log on duplicate.

**The new work in this story is AC #3: OrderTracker-based deduplication.** This adds a second layer of duplicate prevention — checking if a buy order has already been placed for a token_id, which catches cases where a market was processed in a previous session and detected via API reconciliation (Story 5.1).

### Bug Fix Required

`btts_bot/core/market_discovery.py` line 163 has a Python 2 syntax bug:
```python
# CURRENT (broken):
except ValueError, TypeError:

# FIXED:
except (ValueError, TypeError):
```
This must be fixed as part of this story since the dev agent is modifying `market_discovery.py`.

### `OrderTracker` Design Rationale

The epics define `OrderTracker` as a Story 3.1 component with full buy/sell tracking. This story introduces a **minimal version** with only the methods needed for deduplication (`has_buy_order`, `record_buy`, `get_buy_order`), plus stubs for sell-order methods that Story 3.1/3.3 will complete.

This is the correct approach because:
1. `MarketDiscoveryService` needs `has_buy_order()` for AC #3
2. Story 5.1 (Startup Reconciliation) will call `record_buy()` to populate `OrderTracker` from API data
3. The full `OrderTracker` implementation (sell orders, order status tracking) belongs in Story 3.1

**Key constraint:** `OrderTracker` is a **pure data manager** per the architecture — it holds state and answers queries but NEVER initiates API calls. This is enforced by the `state/` boundary rule.

### `MarketDiscoveryService` Constructor Change

The constructor signature changes from:
```python
def __init__(self, gamma_client, market_registry, leagues) -> None:
```
to:
```python
def __init__(self, gamma_client, market_registry, leagues, order_tracker) -> None:
```

This is a **breaking change** to the constructor. All existing tests in `tests/test_market_discovery.py` must be updated to pass an `OrderTracker` instance (or mock). The order tracker should be optional with a default that creates an empty `OrderTracker()` if not provided — **no, do NOT make it optional**. The architecture mandates explicit dependency injection. All callers must provide it.

### Deduplication Flow After This Story

After this story, the discovery pipeline has two deduplication checks in sequence:

```python
# Check 1: Already in MarketRegistry (from current session or discovered previously)
if self._registry.is_processed(no_token_id):
    logger.debug("[%s vs %s] Already processed, skipping (token=%s)", ...)
    continue

# Check 2: Has existing buy order (from API reconciliation on startup)
if self._order_tracker.has_buy_order(no_token_id):
    logger.info("[%s vs %s] Buy order already exists, skipping (token=%s)", ...)
    continue
```

**Why two checks?**
- Check 1 catches markets discovered in the current session (fast, in-memory)
- Check 2 catches markets with orders from a previous session (populated by startup reconciliation in Story 5.1)

The Check 2 log is at INFO level (not DEBUG) because it represents a more significant event — the bot detected that a real order already exists on Polymarket for this market.

### `OrderTracker` Implementation Pattern

```python
"""Order tracker for monitoring active buy and sell orders."""

from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class BuyOrderRecord:
    """Record of a placed buy order."""
    token_id: str
    order_id: str
    buy_price: float


class OrderTracker:
    """Tracks buy and sell orders keyed by token_id.

    Pure data manager — holds state and answers queries.
    Never initiates API calls.
    """

    def __init__(self) -> None:
        self._buy_orders: dict[str, BuyOrderRecord] = {}
        self._sell_orders: dict[str, str] = {}  # token_id -> order_id (stub)

    def record_buy(self, token_id: str, order_id: str, buy_price: float) -> None:
        """Record a buy order for a token."""
        self._buy_orders[token_id] = BuyOrderRecord(
            token_id=token_id,
            order_id=order_id,
            buy_price=buy_price,
        )
        logger.info(
            "Buy order recorded: token=%s order=%s price=%.4f",
            token_id, order_id, buy_price,
        )

    def has_buy_order(self, token_id: str) -> bool:
        """Check if a buy order exists for the given token."""
        return token_id in self._buy_orders

    def get_buy_order(self, token_id: str) -> BuyOrderRecord | None:
        """Get the buy order record for a token, or None if not found."""
        return self._buy_orders.get(token_id)

    def has_sell_order(self, token_id: str) -> bool:
        """Check if a sell order exists for the given token."""
        return token_id in self._sell_orders

    def record_sell(self, token_id: str, order_id: str) -> None:
        """Record a sell order for a token. (Stub — full implementation in Story 3.3.)"""
        self._sell_orders[token_id] = order_id
        logger.info("Sell order recorded: token=%s order=%s", token_id, order_id)

    def get_order(self, token_id: str) -> BuyOrderRecord | None:
        """Get buy order info for a token. Alias for get_buy_order."""
        return self.get_buy_order(token_id)
```

### `market_discovery.py` Modification Pattern

In `__init__`:
```python
from btts_bot.state.order_tracker import OrderTracker

class MarketDiscoveryService:
    def __init__(
        self,
        gamma_client: GammaClient,
        market_registry: MarketRegistry,
        leagues: list[LeagueConfig],
        order_tracker: OrderTracker,
    ) -> None:
        self._gamma_client = gamma_client
        self._registry = market_registry
        self._order_tracker = order_tracker
        self._league_abbreviations: set[str] = {league.abbreviation.lower() for league in leagues}
```

In `discover_markets()`, after the `is_processed()` check:
```python
            # Duplicate check: already in registry
            if self._registry.is_processed(no_token_id):
                logger.debug(
                    "[%s vs %s] Already processed, skipping (token=%s)",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    no_token_id,
                )
                continue

            # Duplicate check: existing buy order (from API reconciliation)
            if self._order_tracker.has_buy_order(no_token_id):
                logger.info(
                    "[%s vs %s] Buy order already exists, skipping (token=%s)",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    no_token_id,
                )
                continue
```

### `main.py` Wiring Pattern

```python
from btts_bot.state.order_tracker import OrderTracker

# In main():
market_registry = MarketRegistry()
order_tracker = OrderTracker()
logger.info("State managers initialized")

gamma_client = GammaClient(config.data_file)
discovery_service = MarketDiscoveryService(
    gamma_client, market_registry, config.leagues, order_tracker
)
```

### File Locations

- `btts_bot/state/order_tracker.py` — **replace stub entirely**: implement `OrderTracker` with `BuyOrderRecord`
- `btts_bot/core/market_discovery.py` — **modify**: add `order_tracker` param to constructor, add `has_buy_order()` check after `is_processed()`, fix `except` bug on line 163
- `btts_bot/main.py` — **modify**: instantiate `OrderTracker`, pass to `MarketDiscoveryService`
- `tests/test_order_tracker.py` — **new file**: tests for `OrderTracker`
- `tests/test_market_discovery.py` — **modify**: update all tests to pass `order_tracker`, add buy-order deduplication tests
- `tests/test_main.py` — **modify**: update tests for `OrderTracker` wiring

Files NOT to touch:
- `btts_bot/config.py` — no config changes needed
- `btts_bot/clients/gamma.py` — complete from Story 2.1, no changes
- `btts_bot/clients/clob.py` — complete from Story 1.5, not needed in this story
- `btts_bot/state/market_registry.py` — complete from Story 1.6, no changes
- `btts_bot/core/game_lifecycle.py` — complete from Story 1.6, no changes
- `btts_bot/core/scheduling.py` — complete from Story 2.2, no changes
- `btts_bot/logging_setup.py` — complete from Story 1.3
- `btts_bot/retry.py` — complete from Story 1.4
- `btts_bot/state/position_tracker.py` — stub for Story 3.2
- `btts_bot/core/liquidity.py` — stub for Story 2.4
- `btts_bot/core/order_execution.py` — stub for Story 3.1
- `btts_bot/core/reconciliation.py` — stub for Story 5.1
- `btts_bot/clients/data_api.py` — stub for Story 5.1

### Testing Pattern

```python
# tests/test_order_tracker.py
from btts_bot.state.order_tracker import BuyOrderRecord, OrderTracker


def test_has_buy_order_returns_false_for_unknown():
    tracker = OrderTracker()
    assert tracker.has_buy_order("unknown-token") is False


def test_has_buy_order_returns_true_after_record():
    tracker = OrderTracker()
    tracker.record_buy("token-1", "order-1", 0.48)
    assert tracker.has_buy_order("token-1") is True


def test_get_buy_order_returns_none_for_unknown():
    tracker = OrderTracker()
    assert tracker.get_buy_order("unknown-token") is None


def test_get_buy_order_returns_record_after_record():
    tracker = OrderTracker()
    tracker.record_buy("token-1", "order-1", 0.48)
    record = tracker.get_buy_order("token-1")
    assert isinstance(record, BuyOrderRecord)
    assert record.token_id == "token-1"
    assert record.order_id == "order-1"
    assert record.buy_price == 0.48


def test_has_sell_order_returns_false_initially():
    tracker = OrderTracker()
    assert tracker.has_sell_order("token-1") is False


def test_record_buy_overwrites_existing():
    tracker = OrderTracker()
    tracker.record_buy("token-1", "order-1", 0.48)
    tracker.record_buy("token-1", "order-2", 0.50)
    record = tracker.get_buy_order("token-1")
    assert record.order_id == "order-2"
    assert record.buy_price == 0.50


# tests/test_market_discovery.py — updates needed:
# All existing tests must pass order_tracker=OrderTracker() to MarketDiscoveryService()
# New tests:

def test_skips_market_with_existing_buy_order(caplog):
    """Markets with existing buy orders are skipped with INFO log."""
    gamma = MagicMock()
    gamma.fetch_games.return_value = [_make_game()]
    registry = MarketRegistry()
    order_tracker = OrderTracker()
    order_tracker.record_buy("no-token-id", "existing-order", 0.48)
    leagues = [LeagueConfig(name="Premier League", abbreviation="epl")]
    service = MarketDiscoveryService(gamma, registry, leagues, order_tracker)
    with caplog.at_level(logging.INFO):
        count = service.discover_markets()
    assert count == 0
    assert "Buy order already exists" in caplog.text


def test_processes_market_when_no_buy_order():
    """Markets without existing buy orders are processed normally."""
    gamma = MagicMock()
    gamma.fetch_games.return_value = [_make_game()]
    registry = MarketRegistry()
    order_tracker = OrderTracker()  # empty — no buy orders
    leagues = [LeagueConfig(name="Premier League", abbreviation="epl")]
    service = MarketDiscoveryService(gamma, registry, leagues, order_tracker)
    count = service.discover_markets()
    assert count == 1
    assert registry.is_processed("no-token-id")
```

### Previous Story Intelligence (2.2)

From Story 2.2 completion:
- `SchedulerService` is wired in `main.py` after discovery, receives `discovery_service`
- 165 total tests pass after Story 2.2
- `ruff check` and `ruff format` must pass with zero issues
- Tests use `pytest` with `MagicMock`, `patch`, and `caplog`
- `MarketDiscoveryService.discover_markets()` returns `int` (count of new markets)
- The main loop uses `while True: time.sleep(1)` with `KeyboardInterrupt` handling

### Git Intelligence

Last 5 commits:
```
1bdd1d9 2-2-scheduled-daily-market-fetch
a2d9cea 2-1-market-discovery-from-json-data-file
97b2c29 1-6-game-lifecycle-state-machine-and-market-registry
6f6c926 1-5-polymarket-clob-client-authentication
9a194cf 1-4-retry-decorator-for-api-resilience
```

Code conventions from recent commits:
- Module docstrings at top of every file
- `from __future__ import annotations` used in `core/` and `state/` modules
- `logger = logging.getLogger(__name__)` at module level
- Type hints on all function signatures
- Constructor dependency injection throughout
- `@dataclasses.dataclass` for data records (see `MarketEntry` in `market_registry.py`)
- Tests follow pattern: `test_{description}` with docstrings

### Architecture Constraints to Enforce

From project enforcement guidelines:
- `state/` modules are pure data managers — hold state and answer queries, NEVER initiate API calls
- `core/` modules receive dependencies via constructor injection
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- Check `OrderTracker` before every order placement for duplicates (this story adds the first such check)
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix

From architecture anti-patterns to avoid:
- Do NOT place deduplication logic inside `OrderTracker` (it's a data manager, not business logic)
- Do NOT import `OrderTracker` in `clients/` modules
- Do NOT make `OrderTracker` initiate any API calls
- Do NOT remove or modify the existing `is_processed()` check in `MarketDiscoveryService` — the new `has_buy_order()` check is an **additional** layer
- Do NOT use `condition_id` as state key — always use `token_id`

### Project Structure Notes

This story adds the `OrderTracker` as the second state manager (after `MarketRegistry`). It establishes the pattern for state manager injection into business logic modules:

```
main.py (composition root)
  ├── MarketRegistry (state/)
  ├── OrderTracker (state/)     <-- NEW
  └── MarketDiscoveryService (core/)
        ├── receives MarketRegistry via DI
        └── receives OrderTracker via DI  <-- NEW
```

Story 3.1 will extend `OrderTracker` with full buy-order lifecycle tracking. Story 3.2 introduces `PositionTracker`. Story 3.3 extends `OrderTracker` with sell-order tracking. All follow the same DI pattern established here.

### Scope Boundaries

**In scope:**
- `OrderTracker` with buy-order recording and querying
- `has_buy_order()` deduplication check in `MarketDiscoveryService`
- Bug fix for `except` syntax in `market_discovery.py`
- Wiring in `main.py`
- Tests

**Out of scope:**
- Full `OrderTracker` with order status tracking, cancellation, etc. (Story 3.1)
- `PositionTracker` (Story 3.2)
- Sell order tracking (Story 3.3)
- Liquidity analysis (Story 2.4)
- Any changes to `GammaClient`, `MarketRegistry`, `GameLifecycle`, or `config.py`

### References

- [Source: epics.md#Story 2.3: BTTS-No Token Selection and Market Deduplication] — acceptance criteria
- [Source: architecture.md#State Management Architecture] — `OrderTracker` owns duplicate buy/sell prevention
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — duplicate prevention pattern
- [Source: architecture.md#Project Structure & Boundaries] — `state/order_tracker.py` location
- [Source: architecture.md#Enforcement Guidelines] — check `OrderTracker` before every order placement
- [Source: prd.md#FR7] — select "No" outcome token
- [Source: prd.md#FR8] — skip already-processed markets
- [Source: prd.md#FR15] — prevent duplicate buy orders
- [Source: 2-2-scheduled-daily-market-fetch.md#Completion Notes] — 165 tests pass, code conventions
- [Source: 2-1-market-discovery-from-json-data-file.md#Completion Notes] — `MarketDiscoveryService` constructor signature, deduplication pattern

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

### Completion Notes List

- Implemented `OrderTracker` as a pure data manager in `btts_bot/state/order_tracker.py` with `BuyOrderRecord` dataclass, `record_buy`, `has_buy_order`, `get_buy_order`, `has_sell_order`, and `record_sell` (stub) methods.
- Added `order_tracker: OrderTracker` as a required 4th parameter to `MarketDiscoveryService.__init__()` — explicit DI, no optional default.
- Added `has_buy_order()` deduplication check after `is_processed()` in `discover_markets()`, logged at INFO level with `[Home vs Away]` prefix.
- Fixed pre-existing Python 2 syntax bug: `except ValueError, TypeError:` → `except (ValueError, TypeError):` in `_parse_kickoff`.
- Wired `OrderTracker` in `main.py`: instantiated alongside `MarketRegistry`, passed to `MarketDiscoveryService`.
- Fixed pre-existing `ruff` lint issue in `tests/test_scheduling.py` (unused `CronTrigger` import).
- 147 tests pass (9 new in `test_order_tracker.py`, 4 new in `test_market_discovery.py`, 2 new in `test_main.py`; all existing tests updated to pass `order_tracker` parameter).
- `ruff check` and `ruff format` both pass with zero issues.

### File List

- `btts_bot/state/order_tracker.py` — implemented (replaced stub)
- `btts_bot/core/market_discovery.py` — modified (added `order_tracker` param, `has_buy_order` check, fixed `except` syntax)
- `btts_bot/main.py` — modified (import and instantiate `OrderTracker`, pass to `MarketDiscoveryService`)
- `tests/test_order_tracker.py` — new file
- `tests/test_market_discovery.py` — modified (updated `_make_service` helper, added buy-order deduplication tests)
- `tests/test_main.py` — modified (added `OrderTracker` mock patch, added 2 new tests)
- `tests/test_scheduling.py` — modified (removed unused `CronTrigger` import, pre-existing lint fix)
