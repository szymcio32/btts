# Story 1.6: Game Lifecycle State Machine and Market Registry

Status: review

## Story

As an operator,
I want the bot to have a well-defined state machine for each game's lifecycle and a registry of discovered markets,
so that all downstream modules have a consistent foundation for state tracking and market identification.

## Acceptance Criteria

1. **Given** the `btts_bot/state/` package exists from Story 1.1
   **When** the state module is implemented
   **Then** `market_registry.py` provides a `MarketRegistry` class that stores discovered markets keyed by `token_id`
   **And** each entry has fields: condition_id, token_ids (list), kickoff_time (datetime), league (str), home_team (str), away_team (str)
   **And** `MarketRegistry` exposes: `register(token_id, ...)`, `get(token_id)`, `is_processed(token_id)`, `all_markets()`
   **And** `MarketRegistry` is a pure data manager — it holds state and answers queries but never initiates API calls

2. **Given** the `btts_bot/core/` package exists from Story 1.1
   **When** the game lifecycle module is implemented
   **Then** `game_lifecycle.py` provides a `GameState` enum with states: `DISCOVERED`, `ANALYSED`, `BUY_PLACED`, `FILLING`, `SELL_PLACED`, `PRE_KICKOFF`, `GAME_STARTED`, `RECOVERY_COMPLETE`, `DONE`, `SKIPPED`, `EXPIRED`
   **And** a `GameLifecycle` class owns per-game state and enforces valid transitions via `transition(new_state)` method
   **And** `transition()` raises `InvalidTransitionError` for illegal state changes
   **And** all state transitions are logged at INFO level with from/to states
   **And** no direct mutation of game state is permitted outside `GameLifecycle.transition()`

3. **Given** `MarketRegistry` registers a new market via `register()`
   **When** the market is stored
   **Then** a `GameLifecycle` instance is created for that market in `DISCOVERED` state
   **And** the lifecycle instance is accessible via `MarketRegistry.get(token_id).lifecycle`

4. **Given** `GameLifecycle` is instantiated for a market
   **When** `transition(new_state)` is called with an illegal transition (e.g., DISCOVERED → DONE)
   **Then** `InvalidTransitionError` is raised with a message identifying the from/to states

5. **Given** tests cover all the above
   **When** `uv run pytest tests/` runs
   **Then** all tests pass
   **And** `uv run ruff check btts_bot/ tests/` reports zero issues

## Tasks / Subtasks

- [x] Task 1: Implement `GameState` enum and `InvalidTransitionError` in `btts_bot/core/game_lifecycle.py` (AC: #2, #4)
  - [x] Define `GameState(enum.Enum)` with all 11 states exactly as specified
  - [x] Define `InvalidTransitionError(Exception)` with message format: `"Invalid transition: {from_state} → {new_state}"`
  - [x] Define `VALID_TRANSITIONS: dict[GameState, frozenset[GameState]]` mapping each state to its allowed next states
  - [x] Implement `GameLifecycle` class with `__init__(self, token_id: str)` that sets `self.state = GameState.DISCOVERED` and stores `token_id`
  - [x] Implement `transition(self, new_state: GameState) -> None` — validates transition, logs at INFO, updates `self.state`
  - [x] Add module-level logger: `logger = logging.getLogger(__name__)`

- [x] Task 2: Implement `MarketEntry` dataclass and `MarketRegistry` class in `btts_bot/state/market_registry.py` (AC: #1, #3)
  - [x] Define `MarketEntry` dataclass with fields: `token_id: str`, `condition_id: str`, `token_ids: list[str]`, `kickoff_time: datetime`, `league: str`, `home_team: str`, `away_team: str`, `lifecycle: GameLifecycle`
  - [x] Implement `MarketRegistry` class with `_markets: dict[str, MarketEntry]` internal store
  - [x] Implement `register(self, token_id, condition_id, token_ids, kickoff_time, league, home_team, away_team) -> MarketEntry` — creates `GameLifecycle(token_id)` in DISCOVERED state, creates `MarketEntry`, stores it, logs at INFO, returns entry
  - [x] Implement `get(self, token_id: str) -> MarketEntry | None` — returns entry or None
  - [x] Implement `is_processed(self, token_id: str) -> bool` — returns True if token_id exists in registry
  - [x] Implement `all_markets(self) -> list[MarketEntry]` — returns list of all registered entries
  - [x] Add module-level logger: `logger = logging.getLogger(__name__)`

- [x] Task 3: Wire `MarketRegistry` into `main.py` (AC: #3)
  - [x] Import and instantiate `MarketRegistry()` after `ClobClientWrapper()`
  - [x] Log at INFO: `"State managers initialized"` after instantiation

- [x] Task 4: Write tests in `tests/test_game_lifecycle.py` and `tests/test_market_registry.py` (AC: #1-#5)
  - [x] `test_game_lifecycle.py`:
    - [x] Test: all valid transitions succeed and state is updated correctly
    - [x] Test: illegal transitions raise `InvalidTransitionError` (e.g., DISCOVERED→DONE, DONE→BUY_PLACED)
    - [x] Test: `transition()` logs at INFO with from/to state names
    - [x] Test: terminal states (DONE, SKIPPED, EXPIRED) reject all further transitions
  - [x] `test_market_registry.py`:
    - [x] Test: `register()` creates a `MarketEntry` with a `GameLifecycle` in `DISCOVERED` state
    - [x] Test: `get()` returns registered entry; returns None for unknown token_id
    - [x] Test: `is_processed()` returns True for registered, False for unknown
    - [x] Test: `all_markets()` returns all registered entries
    - [x] Test: `register()` logs at INFO with market info

- [x] Task 5: Lint and format (all stories convention)
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### File Locations

- `btts_bot/core/game_lifecycle.py` — **replace stub entirely** (currently 5-line TODO)
- `btts_bot/state/market_registry.py` — **replace stub entirely** (currently 5-line TODO)
- `btts_bot/main.py` — add `MarketRegistry()` instantiation after `ClobClientWrapper()`
- `tests/test_game_lifecycle.py` — new file (does not exist yet)
- `tests/test_market_registry.py` — new file (does not exist yet)

Files NOT to touch:
- `btts_bot/state/order_tracker.py` — stub for Story 3.1
- `btts_bot/state/position_tracker.py` — stub for Story 3.2
- `btts_bot/clients/clob.py` — complete from Story 1.5
- `btts_bot/retry.py`, `btts_bot/logging_setup.py`, `btts_bot/config.py` — complete, do not modify

### Valid State Transitions Map

Architecture mandates: "All state transitions routed through `GameLifecycle.transition()` — no direct state mutation."

```python
VALID_TRANSITIONS: dict[GameState, frozenset[GameState]] = {
    GameState.DISCOVERED:         frozenset({GameState.ANALYSED, GameState.SKIPPED}),
    GameState.ANALYSED:           frozenset({GameState.BUY_PLACED, GameState.SKIPPED}),
    GameState.BUY_PLACED:         frozenset({GameState.FILLING, GameState.SKIPPED, GameState.EXPIRED}),
    GameState.FILLING:            frozenset({GameState.SELL_PLACED, GameState.PRE_KICKOFF, GameState.EXPIRED}),
    GameState.SELL_PLACED:        frozenset({GameState.PRE_KICKOFF, GameState.DONE}),
    GameState.PRE_KICKOFF:        frozenset({GameState.GAME_STARTED, GameState.DONE}),
    GameState.GAME_STARTED:       frozenset({GameState.RECOVERY_COMPLETE, GameState.DONE}),
    GameState.RECOVERY_COMPLETE:  frozenset({GameState.DONE}),
    GameState.DONE:               frozenset(),   # terminal
    GameState.SKIPPED:            frozenset(),   # terminal
    GameState.EXPIRED:            frozenset(),   # terminal
}
```

### `GameLifecycle` Implementation Pattern

```python
import enum
import logging

logger = logging.getLogger(__name__)


class GameState(enum.Enum):
    DISCOVERED = "DISCOVERED"
    ANALYSED = "ANALYSED"
    BUY_PLACED = "BUY_PLACED"
    FILLING = "FILLING"
    SELL_PLACED = "SELL_PLACED"
    PRE_KICKOFF = "PRE_KICKOFF"
    GAME_STARTED = "GAME_STARTED"
    RECOVERY_COMPLETE = "RECOVERY_COMPLETE"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"


class InvalidTransitionError(Exception):
    pass


class GameLifecycle:
    def __init__(self, token_id: str) -> None:
        self.token_id = token_id
        self.state = GameState.DISCOVERED

    def transition(self, new_state: GameState) -> None:
        allowed = VALID_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Invalid transition: {self.state.value} → {new_state.value}"
            )
        logger.info(
            "GameLifecycle [%s]: %s → %s",
            self.token_id,
            self.state.value,
            new_state.value,
        )
        self.state = new_state
```

### `MarketEntry` and `MarketRegistry` Pattern

```python
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime

from btts_bot.core.game_lifecycle import GameLifecycle, GameState

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MarketEntry:
    token_id: str
    condition_id: str
    token_ids: list[str]
    kickoff_time: datetime
    league: str
    home_team: str
    away_team: str
    lifecycle: GameLifecycle


class MarketRegistry:
    def __init__(self) -> None:
        self._markets: dict[str, MarketEntry] = {}

    def register(
        self,
        token_id: str,
        condition_id: str,
        token_ids: list[str],
        kickoff_time: datetime,
        league: str,
        home_team: str,
        away_team: str,
    ) -> MarketEntry:
        lifecycle = GameLifecycle(token_id)
        entry = MarketEntry(
            token_id=token_id,
            condition_id=condition_id,
            token_ids=token_ids,
            kickoff_time=kickoff_time,
            league=league,
            home_team=home_team,
            away_team=away_team,
            lifecycle=lifecycle,
        )
        self._markets[token_id] = entry
        logger.info(
            "Market registered: [%s vs %s] token=%s league=%s kickoff=%s",
            home_team,
            away_team,
            token_id,
            league,
            kickoff_time.isoformat(),
        )
        return entry

    def get(self, token_id: str) -> MarketEntry | None:
        return self._markets.get(token_id)

    def is_processed(self, token_id: str) -> bool:
        return token_id in self._markets

    def all_markets(self) -> list[MarketEntry]:
        return list(self._markets.values())
```

### `main.py` Wiring Pattern

The `MarketRegistry` is a pure state manager — instantiated in `main.py` as the composition root. It requires no constructor arguments (no clients, no config). Inject it into `core/` modules that need it (market_discovery, reconciliation) in later stories via constructor injection, not by importing the instance.

```python
from btts_bot.state.market_registry import MarketRegistry

# After ClobClientWrapper() and logger.info("Authentication successful"):
market_registry = MarketRegistry()
logger.info("State managers initialized")
```

`MarketRegistry` does NOT need to be passed into `ClobClientWrapper` — they are independent.

### Import Paths to Use

```python
# In game_lifecycle.py — no external imports beyond stdlib
import enum
import logging

# In market_registry.py
from __future__ import annotations
import dataclasses
import logging
from datetime import datetime
from btts_bot.core.game_lifecycle import GameLifecycle  # cross-package import is fine here
```

**Critical:** `market_registry.py` is in `btts_bot/state/` and imports from `btts_bot/core/game_lifecycle.py`. This is the only cross-package import at this layer. `state/` modules import from `core/` for the `GameLifecycle` type; `core/` modules in later stories import from `state/` for `MarketRegistry`. This **one-directional dependency** (state→core for lifecycle type only) is acceptable because `GameLifecycle` is a data/state class with no I/O, not a business logic orchestrator.

### `GameState` Enum: String Values

Use string values (e.g., `DISCOVERED = "DISCOVERED"`) so that `state.value` in log messages produces readable output like `"DISCOVERED"` rather than the integer enum member. This is consistent with the architecture's log examples showing state names in log messages.

### Architecture Constraints to Enforce

From `architecture.md#Enforcement Guidelines`:
- `token_id` is the canonical state key for all per-market lookups — `MarketRegistry` uses it as the dict key
- All state transitions go through `GameLifecycle.transition()` — no `game.state = ...` anywhere
- `state/` modules are pure data managers — `MarketRegistry` never imports `requests` or `py-clob-client`
- Constructor dependency injection: downstream `core/` modules receive `MarketRegistry` instance, don't import it

From `architecture.md#Naming Patterns`:
- Class: `MarketRegistry`, `GameLifecycle`, `MarketEntry`, `GameState`, `InvalidTransitionError`
- Module: `market_registry.py`, `game_lifecycle.py`
- Enum members: `UPPER_SNAKE_CASE` (e.g., `GameState.BUY_PLACED`)
- Log message convention: include `token_id` and `[Home vs Away]` format for market-specific messages

### Testing Pattern

```python
# test_game_lifecycle.py
import pytest
from btts_bot.core.game_lifecycle import GameLifecycle, GameState, InvalidTransitionError

def test_initial_state():
    gl = GameLifecycle("token-123")
    assert gl.state == GameState.DISCOVERED

def test_valid_transition():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.ANALYSED)
    assert gl.state == GameState.ANALYSED

def test_invalid_transition_raises():
    gl = GameLifecycle("token-123")
    with pytest.raises(InvalidTransitionError, match="DISCOVERED.*DONE"):
        gl.transition(GameState.DONE)

def test_terminal_state_rejects_all(caplog):
    gl = GameLifecycle("token-123")
    gl.transition(GameState.SKIPPED)
    with pytest.raises(InvalidTransitionError):
        gl.transition(GameState.DISCOVERED)

def test_transition_logs_info(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="btts_bot.core.game_lifecycle"):
        gl = GameLifecycle("token-abc")
        gl.transition(GameState.ANALYSED)
    assert "DISCOVERED" in caplog.text
    assert "ANALYSED" in caplog.text


# test_market_registry.py
from datetime import datetime, timezone
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.core.game_lifecycle import GameState

KICKOFF = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)

def _registry():
    return MarketRegistry()

def test_register_creates_entry():
    reg = _registry()
    entry = reg.register("tok-1", "cond-1", ["tok-1", "tok-2"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    assert entry.token_id == "tok-1"
    assert entry.lifecycle.state == GameState.DISCOVERED

def test_get_returns_entry():
    reg = _registry()
    reg.register("tok-1", "cond-1", ["tok-1"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    assert reg.get("tok-1") is not None
    assert reg.get("unknown") is None

def test_is_processed():
    reg = _registry()
    reg.register("tok-1", "cond-1", ["tok-1"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    assert reg.is_processed("tok-1") is True
    assert reg.is_processed("unknown") is False

def test_all_markets():
    reg = _registry()
    reg.register("tok-1", "cond-1", ["tok-1"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    reg.register("tok-2", "cond-2", ["tok-2"], KICKOFF, "LIGA", "Real Madrid", "Atletico")
    assert len(reg.all_markets()) == 2
```

### Previous Story Context (1.5)

From Story 1.5 completion notes and file list:
- `btts_bot/constants.py` — complete, contains `CLOB_HOST`, `CHAIN_ID`, `POLY_GNOSIS_SAFE`, `BUY_SIDE`, `SELL_SIDE`
- `btts_bot/clients/clob.py` — complete `ClobClientWrapper` with full L1/L2 auth
- `btts_bot/main.py` — has `setup_logging()`, `load_config()`, `ClobClientWrapper()`, and auth-success log; **add `MarketRegistry()` instantiation after the auth line**
- Test count at end of Story 1.5: 50 tests passing; this story should add ~12-15 new tests
- Pattern: `logger = logging.getLogger(__name__)` at module level — continue this in both new files
- Pattern: tests use `unittest.mock` (`MagicMock`, `patch`); use `pytest` with `caplog` for logging assertions

### Project Structure Notes

This story creates two new real implementations replacing stubs:

| File | Action |
|---|---|
| `btts_bot/core/game_lifecycle.py` | Replace stub — implement `GameState`, `InvalidTransitionError`, `GameLifecycle` |
| `btts_bot/state/market_registry.py` | Replace stub — implement `MarketEntry`, `MarketRegistry` |
| `btts_bot/main.py` | Add `MarketRegistry` import and instantiation |
| `tests/test_game_lifecycle.py` | New file |
| `tests/test_market_registry.py` | New file |

Files touched in `btts_bot/state/order_tracker.py` and `btts_bot/state/position_tracker.py`: **do not touch** — they remain stubs for Stories 3.1 and 3.2.

### References

- [Source: epics.md#Story 1.6: Game Lifecycle State Machine and Market Registry] — all acceptance criteria
- [Source: architecture.md#Game Lifecycle Management] — 11-state machine, `VALID_TRANSITIONS`, `InvalidTransitionError`
- [Source: architecture.md#State Management Architecture] — `MarketRegistry` boundaries, pure data manager rule
- [Source: architecture.md#Complete Project Directory Structure] — file locations: `state/market_registry.py`, `core/game_lifecycle.py`
- [Source: architecture.md#Enforcement Guidelines] — `token_id` as canonical key, no direct state mutation, `state/` modules never call APIs
- [Source: architecture.md#Naming Patterns] — PEP 8, `UPPER_SNAKE_CASE` enums, `[Home vs Away]` log format
- [Source: architecture.md#Communication Patterns] — INFO level for state transitions, duplicate prevention pattern
- [Source: epics.md#FR22] — `MarketRegistry` and `GameLifecycle` are the in-memory state foundation for all downstream epics

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Implemented `GameState` enum (11 states with string values), `InvalidTransitionError`, `VALID_TRANSITIONS` map, and `GameLifecycle` class in `btts_bot/core/game_lifecycle.py`
- Implemented `MarketEntry` dataclass and `MarketRegistry` class in `btts_bot/state/market_registry.py`; `MarketRegistry` creates a `GameLifecycle(token_id)` in DISCOVERED state on every `register()` call
- Wired `MarketRegistry` instantiation into `main.py` after `ClobClientWrapper()` with `"State managers initialized"` log; assigned with `# noqa: F841` since it will be injected into downstream modules in later stories
- 30 new tests added (16 in `test_game_lifecycle.py`, 14 in `test_market_registry.py`); total suite 80 tests, all passing
- `ruff check` zero issues; `ruff format` no changes needed

### File List

- `btts_bot/core/game_lifecycle.py` — replaced stub; implements GameState, InvalidTransitionError, VALID_TRANSITIONS, GameLifecycle
- `btts_bot/state/market_registry.py` — replaced stub; implements MarketEntry, MarketRegistry
- `btts_bot/main.py` — added MarketRegistry import and instantiation
- `tests/test_game_lifecycle.py` — new file, 16 tests
- `tests/test_market_registry.py` — new file, 14 tests
