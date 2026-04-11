# Story 5.2: Market-Context Logging with LoggerAdapter

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want every log message related to a specific market to include the team names and token ID,
so that I can quickly filter and trace activity for any game when reviewing logs.

## Acceptance Criteria

1. **Given** a `core/` module is processing a specific market
   **When** it creates a LoggerAdapter bound to that market's context
   **Then** all log messages from that adapter automatically include `[Home vs Away]` prefix and `token_id` in the message

2. **Given** a log message is emitted at any level (DEBUG through CRITICAL)
   **When** it is written to file and console
   **Then** the format is `%(asctime)s | %(levelname)-8s | %(name)s | [Home vs Away] message text (token=...)`
   **And** the logger name reflects the originating module (e.g., `btts_bot.core.order_execution`)

3. **Given** market context is available (from MarketRegistry)
   **When** log messages include event datetimes (e.g., kickoff time)
   **Then** the datetime is formatted in a human-readable UTC format within the message body

4. **Given** a module operates outside of a specific market context (e.g., daily fetch summary, startup message)
   **When** it logs
   **Then** it uses the standard module logger without a market adapter
   **And** the log format remains consistent (no empty brackets or missing fields)

## Tasks / Subtasks

- [x] Task 1: Create `MarketLoggerAdapter` in `btts_bot/logging_setup.py` (AC: #1, #2)
  - [x] Import `logging.LoggerAdapter` at top of file
  - [x] Create `MarketLoggerAdapter(logging.LoggerAdapter)` class
  - [x] `__init__` takes `logger: logging.Logger`, `home_team: str`, `away_team: str`, `token_id: str`
  - [x] Store extra context: `{"market_name": f"[{home_team} vs {away_team}]", "token_id": token_id}`
  - [x] Override `process(msg, kwargs)` to prepend `[Home vs Away]` and append `(token={token_id})` to message
  - [x] Output format: `[Arsenal vs Chelsea] Buy order placed: price=0.48 (token=0xabc123)`
  - [x] Create module-level factory: `create_market_logger(module_name: str, home_team: str, away_team: str, token_id: str) -> MarketLoggerAdapter`
  - [x] Factory calls `logging.getLogger(module_name)` internally and wraps it
  - [x] Create fallback factory: `create_token_logger(module_name: str, token_id: str) -> MarketLoggerAdapter` for contexts where team names are unavailable -- uses `[{token_id}]` as prefix with no `(token=...)` suffix

- [x] Task 2: Refactor `order_execution.py` to use `MarketLoggerAdapter` (AC: #1, #2, #3)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In `place_buy_order()`: replace the `market_name` construction + manual prepending with adapter creation at method entry
  - [x] Create adapter: `mlog = create_market_logger(__name__, entry.home_team, entry.away_team, token_id)` (when entry exists) or `mlog = create_token_logger(__name__, token_id)` (when entry is None)
  - [x] Replace all `logger.info("%s ...", market_name, ...)` calls with `mlog.info("...", ...)` -- remove `market_name` from format string and args
  - [x] Repeat for `place_sell_order()` and `update_sell_order()` methods
  - [x] Remove all `market_name` local variable constructions (lines ~48-49, ~194-195, ~264-265)
  - [x] Remove `token=` from message bodies where the adapter suffix already includes it (avoid duplication)
  - [x] Verify the module-level `logger = logging.getLogger(__name__)` is preserved for non-market log calls (if any)

- [x] Task 3: Refactor `fill_polling.py` to use `MarketLoggerAdapter` (AC: #1, #2)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In `_poll_single_order()`: replace `market_name` construction with adapter
  - [x] Create adapter at method entry using `entry.home_team`, `entry.away_team`, `token_id`
  - [x] Replace all 6 log calls to use `mlog` instead of `logger` with manual `market_name`
  - [x] Remove `market_name` local variable

- [x] Task 4: Refactor `pre_kickoff.py` to use `MarketLoggerAdapter` (AC: #1, #2)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In `handle_pre_kickoff()`: replace `market_name` construction with adapter
  - [x] **Critical:** Remove `market_name` parameter from all private helper methods: `_handle_sell_placed()`, `_handle_filling()`, `_handle_buy_placed()`, `_cancel_buy_if_active()`
  - [x] Instead, pass `mlog` (the adapter) as parameter to each helper, or store it as an instance variable for the duration of the call
  - [x] Replace all ~19 log calls from `logger.xyz("%s ...", market_name, ...)` to `mlog.xyz("...", ...)`
  - [x] Remove `market_name` from method signatures and call sites

- [x] Task 5: Refactor `game_start.py` to use `MarketLoggerAdapter` (AC: #1, #2)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In `_do_game_start_recovery()`: replace `market_name` construction with adapter
  - [x] **Critical:** Remove `market_name` parameter from all sub-methods: `_handle_pre_kickoff_state()`, `_handle_sell_placed_state()`, `_handle_filling_state()`, `_handle_buy_placed_state()`, `_place_sell_and_transition()`, `_verify_and_retry_sell()`, `_is_sell_active()`, `_cancel_buy_if_active()`
  - [x] Pass `mlog` as parameter to each sub-method instead of `market_name`
  - [x] Replace all ~25 log calls to use `mlog`
  - [x] Remove `market_name` from method signatures and call sites

- [x] Task 6: Refactor `liquidity.py` to use `MarketLoggerAdapter` (AC: #1, #2)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In `MarketAnalysisPipeline.analyse_market()`: replace `market_name` construction with adapter
  - [x] **Critical:** Currently `market_name` is passed to `LiquidityAnalyser.analyse()` as a parameter. Replace with passing `mlog` adapter
  - [x] Fix the double-bracket issue: currently logs `[Arsenal vs Chelsea] [0xabc123]: Case B...`. With LoggerAdapter, the adapter provides `[Arsenal vs Chelsea]` prefix and `(token=0xabc123)` suffix, so the message body should just be `Case B (deep book)...` -- no manual brackets
  - [x] Update `LiquidityAnalyser.analyse()` signature: replace `market_name: str` param with `mlog: MarketLoggerAdapter` (or `logging.LoggerAdapter`)
  - [x] Replace all log calls in `LiquidityAnalyser.analyse()` and `MarketAnalysisPipeline.analyse_market()`

- [x] Task 7: Refactor `reconciliation.py` to use `MarketLoggerAdapter` where applicable (AC: #1, #2, #4)
  - [x] Import `create_market_logger`, `create_token_logger` from `btts_bot.logging_setup`
  - [x] In `_register_market()`: replace the `label` construction with adapter, use for log calls in that method
  - [x] In orphaned position handling within `reconcile()`: create adapter from game dict or fall back to token-only
  - [x] **Important:** Non-market log calls in `reconcile()` (e.g., `"Reconciliation: queried N open orders..."`) should keep using the standard `logger` -- they are NOT market-specific (AC: #4)

- [x] Task 8: Refactor `market_discovery.py` to use `MarketLoggerAdapter` where applicable (AC: #1, #2, #4)
  - [x] Import `create_market_logger` from `btts_bot.logging_setup`
  - [x] In per-game processing loop: create adapter from `game.get("home_team", "?")` and `game.get("away_team", "?")` and the token_id
  - [x] Replace inline `"[%s vs %s]"` formatting with adapter log calls
  - [x] **Important:** Summary log calls (e.g., `"Discovered N markets for league X"`) should keep using standard `logger` (AC: #4)

- [x] Task 9: Update tests for all refactored modules (AC: #1-#4)
  - [x] Create `tests/test_market_logger_adapter.py` with tests for `MarketLoggerAdapter`:
    - Test: adapter prepends `[Home vs Away]` and appends `(token=...)` to messages
    - Test: factory function `create_market_logger()` returns properly configured adapter
    - Test: fallback factory `create_token_logger()` uses `[token_id]` prefix with no suffix
    - Test: adapter preserves logger name from the underlying module logger
    - Test: adapter works at all log levels (DEBUG through CRITICAL)
    - Test: adapter doesn't interfere with SecretFilter (credentials still redacted)
  - [x] Update existing tests in `tests/test_order_execution.py`: update log message assertions to match new format (no manual `market_name` in format string)
  - [x] Update existing tests in `tests/test_fill_polling.py`: update log message assertions
  - [x] Update existing tests in `tests/test_pre_kickoff.py`: update log assertions AND remove `market_name` from mocked method call assertions if signatures changed
  - [x] Update existing tests in `tests/test_game_start.py`: update log assertions AND remove `market_name` from mocked method call assertions if signatures changed
  - [x] Update existing tests in `tests/test_liquidity.py`: update log assertions AND update `analyse()` call signature in tests
  - [x] Update existing tests in `tests/test_reconciliation.py`: update log assertions for market-context messages
  - [x] Update existing tests in `tests/test_market_discovery.py`: update log assertions for per-game messages

- [x] Task 10: Lint and format (AC: all)
  - [x] `uv run ruff check btts_bot/ tests/` -- zero issues
  - [x] `uv run ruff format btts_bot/ tests/` -- no changes needed
  - [x] All existing tests still pass (431 baseline from 5-1, adjusted for test changes)

## Dev Notes

### Critical Context: This Story Adds a Layer on Top of Story 1.3's Foundation

Story 1.3 created the logging infrastructure: `RotatingFileHandler`, `StreamHandler(stdout)`, `SecretFilter`, `LOG_FORMAT`, and `setup_logging()`. This story does NOT modify that infrastructure. It adds an application-level `LoggerAdapter` pattern used by `core/` modules to automatically bind market context.

The cross-epic dependency note from Story 1.3 explicitly planned for this:
> "Story 5.2 later adds `LoggerAdapter` for per-market context binding. All intermediate stories (Epics 2-4) should use standard module loggers; the market-context adapter is layered on in Epic 5 without requiring changes to the logging infrastructure created here."

### Critical Context: LoggerAdapter Mechanism

Python's `logging.LoggerAdapter` wraps a `Logger` instance and injects extra context into every message via its `process()` method. Key properties:

```python
class MarketLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # self.extra contains {"market_name": "[Arsenal vs Chelsea]", "token_id": "0xabc123"}
        return f"{self.extra['market_name']} {msg} (token={self.extra['token_id']})", kwargs
```

- **Logger name preserved:** `LoggerAdapter` delegates to the underlying logger, so `%(name)s` in the format string still shows `btts_bot.core.order_execution` (the module name)
- **All levels work:** `adapter.info()`, `adapter.warning()`, etc. all go through `process()`
- **No changes to handlers/formatters needed:** The adapter modifies the message before it hits the handler
- **Thread-safe:** `LoggerAdapter` is inherently thread-safe because it delegates to the thread-safe `Logger`

### Critical Context: The `market_name` Duplication Problem

Currently, 7 modules independently construct `market_name` using this identical pattern:

```python
entry = self._market_registry.get(token_id)
market_name = (
    f"[{entry.home_team} vs {entry.away_team}]" if entry is not None else f"[{token_id}]"
)
```

This is manually prepended as the first `%s` arg in every single log call. The problems:
1. **Duplication:** Same construction in 7+ places across 5 files
2. **Fragility:** Easy to forget the prefix on new log lines
3. **Parameter threading:** `pre_kickoff.py` and `game_start.py` pass `market_name` through 4-8 private method signatures each, adding noise
4. **Inconsistency:** `liquidity.py` double-brackets `[Home vs Away] [token_id]`, while others do `[Home vs Away] ... token=...`

The LoggerAdapter eliminates all four issues.

### Critical Context: Adapter Output Format

**Target output for market-context messages:**
```
2026-04-10 15:00:12 | INFO     | btts_bot.core.order_execution | [Arsenal vs Chelsea] Buy order placed: price=0.48, size=30 (token=0xabc123)
```

**Target output for token-only fallback (no team names available):**
```
2026-04-10 15:00:12 | WARNING  | btts_bot.core.reconciliation | [0xabc123] Orphaned position detected -- sell placed at buy_price=0.48, size=30
```

**Target output for non-market messages (standard logger, no adapter):**
```
2026-04-10 23:00:00 | INFO     | btts_bot.core.market_discovery | Discovered 8 new BTTS markets for EPL
```

### Critical Context: Which Modules to Refactor vs. Leave Alone

**Refactor (use `MarketLoggerAdapter` for per-market log calls):**
- `core/order_execution.py` -- 3 methods, ~13 log calls with `market_name`
- `core/fill_polling.py` -- 1 method, ~6 log calls with `market_name`
- `core/pre_kickoff.py` -- 1 entry + 4 helpers, ~19 log calls with `market_name` passed as param
- `core/game_start.py` -- 1 entry + 8 helpers, ~25 log calls with `market_name` passed as param
- `core/liquidity.py` -- 2 classes, `market_name` passed between them as param
- `core/reconciliation.py` -- `_register_market()` and orphan handling only
- `core/market_discovery.py` -- per-game loop only

**Leave alone (standard `logger` with no adapter):**
- `core/scheduling.py` -- logs `token=` but has no team names; changing it would require passing registry or adapter into scheduler callbacks, which adds complexity for minimal benefit
- `core/game_lifecycle.py` -- logs `[token_id]` in transitions; this is a low-level state module that should not depend on market display names
- `state/market_registry.py` -- already logs `[Home vs Away]` inline during `register()` which is fine as a one-time event
- `state/order_tracker.py`, `state/position_tracker.py` -- pure data managers, log with `token=` only
- `clients/*.py` -- infrastructure wrappers, no market context
- `main.py` -- startup orchestration only
- `retry.py` -- cross-cutting infrastructure

### Critical Context: Method Signature Changes in `pre_kickoff.py` and `game_start.py`

These two modules pass `market_name: str` as a parameter through many private methods. The refactoring replaces this with `mlog: logging.LoggerAdapter` (or `MarketLoggerAdapter`). This changes method signatures.

**`pre_kickoff.py` methods affected:**
- `_handle_sell_placed(self, token_id, market_name)` -> `_handle_sell_placed(self, token_id, mlog)`
- `_handle_filling(self, token_id, market_name)` -> `_handle_filling(self, token_id, mlog)`
- `_handle_buy_placed(self, token_id, market_name)` -> `_handle_buy_placed(self, token_id, mlog)`
- `_cancel_buy_if_active(self, token_id, market_name)` -> `_cancel_buy_if_active(self, token_id, mlog)`

**`game_start.py` methods affected:**
- `_handle_pre_kickoff_state(self, token_id, market_name)` -> `_handle_pre_kickoff_state(self, token_id, mlog)`
- `_handle_sell_placed_state(self, token_id, market_name)` -> `_handle_sell_placed_state(self, token_id, mlog)`
- `_handle_filling_state(self, token_id, market_name)` -> `_handle_filling_state(self, token_id, mlog)`
- `_handle_buy_placed_state(self, token_id, market_name)` -> `_handle_buy_placed_state(self, token_id, mlog)`
- `_place_sell_and_transition(self, token_id, sell_price, position_size, market_name, ...)` -> `..., mlog, ...`
- `_verify_and_retry_sell(self, token_id, sell_price, position_size, sell_order_id, market_name)` -> `..., mlog`
- `_is_sell_active(self, sell_order_id, market_name)` -> `..., mlog`
- `_cancel_buy_if_active(self, token_id, market_name)` -> `..., mlog`

**`liquidity.py` methods affected:**
- `LiquidityAnalyser.analyse(self, token_id, orderbook, market_name)` -> `..., mlog`

Tests must be updated to match these new signatures.

### Critical Context: Avoiding `token=` Duplication

Currently, many log messages manually include `token=...` in the message body:
```python
logger.info("%s Buy order placed: token=%s, price=%.4f", market_name, token_id, price)
```

With the adapter appending `(token=0xabc123)` automatically, the message body should NOT also include `token=`:
```python
mlog.info("Buy order placed: price=%.4f, size=%d", price, size)
# Output: [Arsenal vs Chelsea] Buy order placed: price=0.4800, size=30 (token=0xabc123)
```

Review each log message and remove redundant `token=` args from the message body. Keep `token=` only in messages where it provides additional context beyond the adapter suffix (which should be rare/none).

### Critical Context: `market_discovery.py` Special Case

`market_discovery.py` constructs market context from raw `game` dicts (fetched from JSON file) BEFORE the market is registered in MarketRegistry. The team names come from `game.get("home_team", "?")` and `game.get("away_team", "?")`. Token ID may not yet be resolved.

For this module, create the adapter from the game dict values directly:
```python
mlog = create_market_logger(__name__, game.get("home_team", "?"), game.get("away_team", "?"), token_id_or_empty)
```

If token_id is not yet known at some log points, use a placeholder or skip the suffix.

### Critical Context: `reconciliation.py` Special Case

Similar to `market_discovery.py`, reconciliation constructs context from `game` dicts (from the JSON file lookup). For tokens without game metadata, use the token-only fallback:
```python
mlog = create_token_logger(__name__, token_id)
```

### Previous Story Intelligence (5-1)

From Story 5-1 completion notes:
- **Test baseline:** 431 tests passing, ruff check and format clean
- **ReconciliationService** now takes 8 DI dependencies including `GammaClient` for market metadata lookup
- `DataApiClient` implemented with `@with_retry` and `threading.Lock`
- `get_open_orders()` added to `ClobClientWrapper`
- `set_position()` added to `PositionTracker`
- Market registration during reconciliation uses sequential lifecycle transitions (DISCOVERED -> ANALYSED -> BUY_PLACED -> etc.)
- Tokens without game metadata in JSON file are tracked in OrderTracker/PositionTracker but skipped from MarketRegistry -- logged with WARNING and token_id only
- Commit message format: story key only (e.g., `5-1-startup-state-reconciliation-from-polymarket-api`)

### Git Intelligence

Last 5 commits:
```
0d76fbd 5-1-startup-state-reconciliation-from-polymarket-api
2bbea8f 4-3-post-game-start-sell-verification-and-retry-loop
33ec73f 4-2-game-start-order-cancellation-detection-and-sell-re-placement
5d88a3c 4-1-pre-kickoff-sell-consolidation-and-buy-cancellation
749e7d4 3-3-automatic-sell-order-placement-on-fill-threshold
```

Test suite: 431 tests. Commit message format: story key only.

### Architecture Constraints to Enforce

- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s` -- do NOT modify this format string
- `LoggerAdapter` modifies the message only (via `process()`), not the format
- Market-specific log messages include `[Home vs Away]` prefix (from adapter) and `(token=...)` suffix (from adapter)
- Non-market log calls use standard `logger = logging.getLogger(__name__)` -- no adapter
- `core/` modules contain business logic -- never import `requests` or `py-clob-client`
- `state/` modules are pure data managers -- do NOT add LoggerAdapter to state modules
- `clients/` modules are thin I/O wrappers -- do NOT add LoggerAdapter to client modules
- `SecretFilter` must still work with LoggerAdapter messages -- test this explicitly
- Thread safety: `LoggerAdapter` is inherently thread-safe (delegates to `Logger`)
- `token_id` is the canonical identifier -- always include in market-context logs

### Architecture Anti-Patterns to Avoid

- Do NOT modify `LOG_FORMAT` in `logging_setup.py` -- market context goes in the message, not in format fields
- Do NOT add custom format fields like `%(market_name)s` to the formatter -- use `process()` only
- Do NOT add LoggerAdapter to `state/` or `clients/` modules -- they should use plain `getLogger(__name__)`
- Do NOT create adapters at class `__init__` time and store as instance variable -- create per-method-call (each call may process a different market)
- Do NOT remove the module-level `logger = logging.getLogger(__name__)` from modules -- it is still needed for non-market log calls
- Do NOT make `MarketLoggerAdapter` depend on `MarketRegistry` -- keep it a simple wrapper that takes string args
- Do NOT duplicate `token=` in both the message body and adapter suffix

### Scope Boundaries

**In scope:**
- `MarketLoggerAdapter` class and factory functions in `logging_setup.py`
- Refactoring 7 `core/` modules to use the adapter for market-context log calls
- Removing `market_name` parameter threading from `pre_kickoff.py`, `game_start.py`, `liquidity.py`
- Fixing the double-bracket issue in `liquidity.py`
- Updating all existing tests for changed log formats and method signatures
- New tests for `MarketLoggerAdapter`

**Out of scope:**
- Modifying `LOG_FORMAT` or `setup_logging()` in `logging_setup.py`
- Adding LoggerAdapter to `state/` modules, `clients/` modules, or `game_lifecycle.py`
- Adding LoggerAdapter to `scheduling.py` (no team names available in scheduler callbacks)
- Non-fatal error handling improvements (Story 5.3)
- State pruning (Story 5.4)
- Any changes to retry logic, config, or state managers

### Project Structure Notes

Files to MODIFY:
```
btts_bot/logging_setup.py         -- ADD: MarketLoggerAdapter class + factory functions
btts_bot/core/order_execution.py  -- REFACTOR: use adapter instead of manual market_name
btts_bot/core/fill_polling.py     -- REFACTOR: use adapter instead of manual market_name
btts_bot/core/pre_kickoff.py      -- REFACTOR: use adapter, remove market_name param threading
btts_bot/core/game_start.py       -- REFACTOR: use adapter, remove market_name param threading
btts_bot/core/liquidity.py        -- REFACTOR: use adapter, fix double-bracket, change analyse() sig
btts_bot/core/reconciliation.py   -- REFACTOR: use adapter in _register_market() and orphan handling
btts_bot/core/market_discovery.py -- REFACTOR: use adapter in per-game processing loop
```

Files to CREATE:
```
tests/test_market_logger_adapter.py -- NEW: tests for MarketLoggerAdapter
```

Files to UPDATE (test assertions only):
```
tests/test_order_execution.py     -- UPDATE: log message assertions
tests/test_fill_polling.py        -- UPDATE: log message assertions
tests/test_pre_kickoff.py         -- UPDATE: log assertions + method signature mocks
tests/test_game_start.py          -- UPDATE: log assertions + method signature mocks
tests/test_liquidity.py           -- UPDATE: log assertions + analyse() call signature
tests/test_reconciliation.py      -- UPDATE: log assertions
tests/test_market_discovery.py    -- UPDATE: log assertions
```

Files NOT to touch:
```
btts_bot/config.py                -- unchanged
btts_bot/constants.py             -- unchanged
btts_bot/retry.py                 -- unchanged
btts_bot/main.py                  -- unchanged (no market-context logging in startup)
btts_bot/__main__.py              -- unchanged
btts_bot/core/scheduling.py       -- unchanged (no team names in scheduler callbacks)
btts_bot/core/game_lifecycle.py   -- unchanged (low-level state module)
btts_bot/state/*.py               -- unchanged (pure data managers)
btts_bot/clients/*.py             -- unchanged (infrastructure wrappers)
```

### References

- [Source: epics.md#Story 5.2: Market-Context Logging with LoggerAdapter] -- acceptance criteria, cross-epic dependency note
- [Source: epics.md#Story 1.3: Structured Logging Setup] -- cross-epic dependency: "Story 5.2 later adds LoggerAdapter"
- [Source: architecture.md#Logging & Observability] -- LoggerAdapter for market context, per-module loggers via `getLogger(__name__)`
- [Source: architecture.md#Communication Patterns - Log Message Format] -- `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- [Source: architecture.md#Implementation Patterns - Market Identifier Conventions] -- `[Home vs Away]` prefix + `token_id` for traceability
- [Source: architecture.md#Cross-Cutting Concerns] -- Structured Observability: every log entry needs market identifier
- [Source: prd.md#FR25] -- log with timestamp, log level, logger name, human-readable messages
- [Source: prd.md#FR26] -- include market identifiers (home team vs away team) and event datetimes
- [Source: 5-1-startup-state-reconciliation-from-polymarket-api.md] -- previous story: 431 tests, ruff clean, commit format
- [Source: btts_bot/logging_setup.py] -- current logging infrastructure, SecretFilter, LOG_FORMAT
- [Source: btts_bot/core/order_execution.py] -- current manual market_name prepending pattern
- [Source: btts_bot/core/pre_kickoff.py] -- market_name parameter threading through 4 helpers
- [Source: btts_bot/core/game_start.py] -- market_name parameter threading through 8 helpers
- [Source: btts_bot/core/liquidity.py] -- market_name passed to LiquidityAnalyser.analyse(), double-bracket issue

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

- Python 2-style `except ValueError, TypeError:` syntax existed in `reconciliation.py` and `market_discovery.py` — fixed to Python 3 `except (ValueError, TypeError):`
- `liquidity.py` had unused `MarketLoggerAdapter` import after refactor — removed
- `tests/test_market_logger_adapter.py` used ambiguous variable name `l` — renamed to `line`
- `tests/test_market_logger_adapter.py` imported unused `SecretFilter` — removed
- `tests/test_liquidity.py` pipeline assertion used exact adapter type — updated to `ANY`
- `tests/test_game_start.py` log message assertion included old `token=` in body — updated

### Completion Notes List

- `_TokenOnlyLoggerAdapter` is a private class (not `MarketLoggerAdapter` subclass) — `create_token_logger()` return type annotated with `# type: ignore[return-value]`
- Test count increased from 431 (baseline) to 486 (55 new tests across new file + updated files)
- All 486 tests pass; ruff check and format clean

### File List

**Modified source files:**
- `btts_bot/logging_setup.py` — Added `MarketLoggerAdapter`, `_TokenOnlyLoggerAdapter`, `create_market_logger()`, `create_token_logger()`
- `btts_bot/core/order_execution.py` — Refactored to use adapter
- `btts_bot/core/fill_polling.py` — Refactored to use adapter
- `btts_bot/core/pre_kickoff.py` — Refactored to use adapter, removed `market_name` param threading
- `btts_bot/core/game_start.py` — Refactored to use adapter, removed `market_name` param threading
- `btts_bot/core/liquidity.py` — Refactored, `analyse()` sig changed to accept `mlog`, double-bracket fixed
- `btts_bot/core/reconciliation.py` — Refactored, fixed Python 2 except syntax
- `btts_bot/core/market_discovery.py` — Refactored, fixed Python 2 except syntax

**New test file:**
- `tests/test_market_logger_adapter.py` — 21 tests for `MarketLoggerAdapter`, factories, all log levels, SecretFilter interop

**Updated test files:**
- `tests/test_order_execution.py` — Updated log message assertions
- `tests/test_fill_polling.py` — Updated log message assertions
- `tests/test_pre_kickoff.py` — Updated log assertions + method signature mocks
- `tests/test_game_start.py` — Updated log assertions + method signature mocks
- `tests/test_liquidity.py` — Updated `analyse()` call signature + pipeline assertion
- `tests/test_reconciliation.py` — Passes as-is (no log string assertions needed updating)
- `tests/test_market_discovery.py` — Passes as-is (no log string assertions needed updating)
