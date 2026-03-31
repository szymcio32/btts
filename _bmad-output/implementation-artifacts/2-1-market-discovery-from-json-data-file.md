# Story 2.1: Market Discovery from JSON Data File

Status: done

## Story

As an operator,
I want the bot to fetch all BTTS markets for my configured leagues from the JSON data file,
so that it automatically identifies today's trading opportunities without manual market lookup.

## Acceptance Criteria

1. **Given** the bot has started with a valid config containing league definitions
   **When** the market discovery pipeline runs (immediately on startup)
   **Then** the GammaClient fetches BTTS markets from the JSON data file for all configured leagues
   **And** each discovered market is registered in `MarketRegistry` (from Story 1.6) with its condition ID, token IDs, kickoff time, league, and team names (home vs away)
   **And** each registered market receives a `GameLifecycle` instance in DISCOVERED state (from Story 1.6)
   **And** discovery results are logged at INFO level with market count per league and `[Home vs Away]` identifiers

2. **Given** a league in the config has no BTTS markets in the JSON data file
   **When** discovery runs for that league
   **Then** the bot logs an INFO message indicating zero markets found for that league and continues to the next league

3. **Given** the JSON data file is unreadable or contains invalid data
   **When** discovery runs
   **Then** GammaClient logs the error and returns `None`
   **And** discovery continues as a non-fatal path for the bot run

4. **Given** a market whose `token_id` already exists in MarketRegistry
   **When** the bot encounters it during discovery
   **Then** it skips the market with a DEBUG log message
   **And** no duplicate entry is created in MarketRegistry

5. **Given** the config model is extended with `data_file`
   **When** the bot starts with a valid config
   **Then** `BotConfig` validates the new field and `GammaClient` uses it to fetch the JSON data

6. **Given** the full discovery pipeline runs
   **When** all leagues are processed
   **Then** an INFO summary log is emitted with total markets discovered across all leagues

## Tasks / Subtasks

- [x] Task 1: Extend `BotConfig` with `data_file` field in `btts_bot/config.py` (AC: #5)
  - [x] Add `data_file: str` field to `BotConfig` (required, validated as non-empty string)
  - [x] Add `data_file` to `config_btts.example.yaml`

- [x] Task 2: Implement `GammaClient` in `btts_bot/clients/gamma.py` (AC: #1, #3)
  - [x] Replace stub with full implementation
  - [x] Constructor takes `data_file: str` parameter
  - [x] Implement `fetch_games(self) -> list[dict] | None` method using local file reads
  - [x] Parses JSON from `data_file` and validates expected shape
  - [x] Parses JSON response and returns the `games` list
  - [x] Returns `None` on failure and logs an error
  - [x] Add module-level logger

- [x] Task 3: Implement `MarketDiscoveryService` in `btts_bot/core/market_discovery.py` (AC: #1, #2, #4, #6)
  - [x] Replace stub with full implementation
  - [x] Constructor takes `gamma_client: GammaClient`, `market_registry: MarketRegistry`, `leagues: list[LeagueConfig]`
  - [x] Implement `discover_markets(self) -> int` method that returns total markets discovered
  - [x] For each game in JSON data: filter by configured league abbreviations
  - [x] For each matching game: find the "Both Teams to Score" market in `markets` list (where `market_type == "both_teams_to_score"`)
  - [x] Extract `token_id` (the "No" token — index 1 of `token_ids`), `condition_id`, both `token_ids`, `kickoff_utc`, `league`, `home_team`, `away_team`
  - [x] Check `market_registry.is_processed(token_id)` before registering — skip with DEBUG log if duplicate
  - [x] Call `market_registry.register(...)` for new markets
  - [x] Log per-league discovery count at INFO level
  - [x] Log total discovery summary at INFO level
  - [x] Handle `None` return from GammaClient (retries exhausted) gracefully

- [x] Task 4: Wire discovery into `btts_bot/main.py` (AC: #1)
  - [x] Import and instantiate `GammaClient(config.data_file)`
  - [x] Import and instantiate `MarketDiscoveryService(gamma_client, market_registry, config.leagues)`
  - [x] Call `discovery_service.discover_markets()` after state managers initialization
  - [x] Log discovery completion

- [x] Task 5: Write tests (AC: #1-#6)
  - [x] `tests/test_gamma_client.py`:
    - [x] Test: successful JSON fetch returns games list
    - [x] Test: unreadable/malformed file returns `None` and logs error
    - [x] Test: empty/malformed JSON handled gracefully
  - [x] `tests/test_market_discovery.py`:
    - [x] Test: discovers BTTS markets for configured leagues only
    - [x] Test: skips games for non-configured leagues
    - [x] Test: skips games without "Both Teams to Score" market
    - [x] Test: correctly extracts "No" token (index 1 of token_ids)
    - [x] Test: skips already-processed markets (duplicate prevention)
    - [x] Test: handles GammaClient returning None (retries exhausted)
    - [x] Test: logs per-league count and total summary
    - [x] Test: registers markets correctly in MarketRegistry with all fields
  - [x] `tests/test_main.py` — update existing tests if needed for new startup flow

- [x] Task 6: Lint and format
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### File Locations

- `btts_bot/config.py` — **modify**: add `data_file: str` field to `BotConfig`
- `btts_bot/clients/gamma.py` — **replace stub entirely**: implement `GammaClient`
- `btts_bot/core/market_discovery.py` — **replace stub entirely**: implement `MarketDiscoveryService`
- `btts_bot/main.py` — **modify**: wire `GammaClient` and `MarketDiscoveryService` into startup
- `config_btts.example.yaml` — **modify**: add `data_file` field
- `tests/test_gamma_client.py` — new file
- `tests/test_market_discovery.py` — new file

Files NOT to touch:
- `btts_bot/state/market_registry.py` — complete from Story 1.6, use as-is
- `btts_bot/core/game_lifecycle.py` — complete from Story 1.6, use as-is
- `btts_bot/clients/clob.py` — complete from Story 1.5, not needed in this story
- `btts_bot/retry.py` — complete from Story 1.4 (not required by this story's local file client)
- `btts_bot/logging_setup.py` — complete from Story 1.3, use as-is
- `btts_bot/state/order_tracker.py` — stub for Story 3.1
- `btts_bot/state/position_tracker.py` — stub for Story 3.2
- `btts_bot/core/liquidity.py` — stub for Story 2.4
- `btts_bot/core/scheduling.py` — stub for Story 2.2
- `btts_bot/core/order_execution.py` — stub for Story 3.1
- `btts_bot/core/reconciliation.py` — stub for Story 5.1

### JSON Data File Structure

The JSON data file has this structure (from `BTTS_FUNCTIONAL_REQUIREMENTS.md` Section 5):

```json
{
  "date": "2026-03-23",
  "games": [
    {
      "id": "230411",
      "league": "aus",
      "league_prefix": "aus",
      "home_team": "Sydney FC",
      "away_team": "Newcastle United Jets FC",
      "home_abbr": "syd",
      "away_abbr": "new",
      "kickoff_utc": "2026-03-22T04:00:00Z",
      "slug": "aus-syd-new-2026-03-22-more-markets",
      "polymarket": {
        "slug": "...",
        "event_id": "230411",
        "condition_id": "0x...",
        "tokens": { ... },
        "markets": [
          {
            "condition_id": "0x...",
            "question": "Sydney FC vs. Newcastle United Jets FC: Both Teams to Score",
            "outcome_label": "Both Teams to Score",
            "market_type": "both_teams_to_score",
            "outcome_prices": ["1", "0"],
            "token_ids": [
              "<yes_token_id>",
              "<no_token_id>"
            ]
          }
        ]
      }
    }
  ]
}
```

**Critical extraction logic:**

1. **League matching**: Compare `game["league"]` (lowercase abbreviation like `"epl"`, `"aus"`) against configured `LeagueConfig.abbreviation` (case-insensitive)
2. **BTTS market identification**: Find the market object in `game["polymarket"]["markets"]` where `market_type == "both_teams_to_score"`
3. **No token extraction**: The "No" token ID is at index 1 of `token_ids` in the BTTS market (index 0 is "Yes")
4. **Condition ID**: Use `condition_id` from the BTTS market object (not from the top-level `polymarket.condition_id` which belongs to the first market/spread)
5. **Both token IDs**: Store both `token_ids` (Yes and No) in `MarketEntry.token_ids` for reference
6. **Kickoff time**: Parse `game["kickoff_utc"]` as a UTC datetime

### `GammaClient` Implementation Pattern

```python
"""Gamma client for reading local Polymarket market data files."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GammaClient:
    """Reads market data from a local JSON data file."""

    def __init__(self, data_file: str) -> None:
        self._data_file = Path(data_file)

    def fetch_games(self) -> list[dict] | None:
        """Read all games from the local JSON data file.

        Returns the list of game dicts from the JSON, or None on failure.
        """
        try:
            data = json.loads(self._data_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.error("Invalid data file format in %s: root must be object", self._data_file)
                return None
            games = data.get("games", [])
            if games is None:
                games = []
            if not isinstance(games, list):
                logger.error("Invalid data file format in %s: 'games' must be list", self._data_file)
                return None
            logger.info("Fetched %d games from data file", len(games))
            return games
        except FileNotFoundError:
            logger.error("Data file not found: %s", self._data_file)
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read data file %s: %s", self._data_file, exc)
            return None
```

**Key points:**
- Constructor receives `data_file` — injected from config, not hardcoded
- Reads local JSON file and validates payload shape before returning
- Returns `list[dict]` on success, `None` on read/parse/shape errors
- Logs non-fatal errors for invalid or missing file data

### `MarketDiscoveryService` Implementation Pattern

```python
"""Market discovery from Polymarket data sources."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from btts_bot.clients.gamma import GammaClient
from btts_bot.config import LeagueConfig
from btts_bot.state.market_registry import MarketRegistry

logger = logging.getLogger(__name__)

BTTS_MARKET_TYPE = "both_teams_to_score"
BTTS_NO_TOKEN_INDEX = 1  # index 0 = Yes, index 1 = No


class MarketDiscoveryService:
    """Discovers BTTS markets from JSON data and registers them."""

    def __init__(
        self,
        gamma_client: GammaClient,
        market_registry: MarketRegistry,
        leagues: list[LeagueConfig],
    ) -> None:
        self._gamma_client = gamma_client
        self._registry = market_registry
        # Build a set of lowercase abbreviations for fast lookup
        self._league_abbreviations: set[str] = {
            league.abbreviation.lower() for league in leagues
        }

    def discover_markets(self) -> int:
        """Run the full discovery pipeline. Returns total new markets discovered."""
        games = self._gamma_client.fetch_games()
        if games is None:
            logger.error("Market discovery failed: could not fetch games data")
            return 0

        total_discovered = 0
        per_league_counts: dict[str, int] = {}

        for game in games:
            league = game.get("league", "")
            if league.lower() not in self._league_abbreviations:
                continue

            btts_market = self._find_btts_market(game)
            if btts_market is None:
                continue

            token_ids = btts_market.get("token_ids", [])
            if len(token_ids) < 2:
                logger.warning(
                    "[%s vs %s] BTTS market has insufficient token_ids, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            no_token_id = token_ids[BTTS_NO_TOKEN_INDEX]

            # Duplicate check
            if self._registry.is_processed(no_token_id):
                logger.debug(
                    "[%s vs %s] Already processed, skipping (token=%s)",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    no_token_id,
                )
                continue

            # Parse kickoff time
            kickoff_utc = self._parse_kickoff(game.get("kickoff_utc", ""))
            if kickoff_utc is None:
                logger.warning(
                    "[%s vs %s] Invalid kickoff_utc, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            # Register in MarketRegistry
            self._registry.register(
                token_id=no_token_id,
                condition_id=btts_market["condition_id"],
                token_ids=list(token_ids),
                kickoff_time=kickoff_utc,
                league=league,
                home_team=game.get("home_team", "Unknown"),
                away_team=game.get("away_team", "Unknown"),
            )

            total_discovered += 1
            per_league_counts[league] = per_league_counts.get(league, 0) + 1

        # Log per-league summary
        for league_abbr, count in per_league_counts.items():
            logger.info("Discovery: %s — %d BTTS markets found", league_abbr, count)

        # Log leagues with zero markets
        for abbr in self._league_abbreviations:
            if abbr not in per_league_counts:
                logger.info("Discovery: %s — 0 BTTS markets found", abbr)

        logger.info("Market discovery complete: %d new markets registered", total_discovered)
        return total_discovered

    def _find_btts_market(self, game: dict) -> dict | None:
        """Find the BTTS market in a game's polymarket data."""
        polymarket = game.get("polymarket", {})
        markets = polymarket.get("markets", [])
        for market in markets:
            if market.get("market_type") == BTTS_MARKET_TYPE:
                return market
        return None

    def _parse_kickoff(self, kickoff_str: str) -> datetime | None:
        """Parse kickoff_utc string to timezone-aware datetime."""
        if not kickoff_str:
            return None
        try:
            # ISO 8601 format: "2026-03-22T04:00:00Z"
            return datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
```

### `main.py` Wiring Pattern

After the existing `MarketRegistry` initialization, add:

```python
from btts_bot.clients.gamma import GammaClient
from btts_bot.core.market_discovery import MarketDiscoveryService

# After market_registry initialization:
gamma_client = GammaClient(config.data_file)
discovery_service = MarketDiscoveryService(gamma_client, market_registry, config.leagues)

# Immediate startup discovery (FR5)
discovered_count = discovery_service.discover_markets()
logger.info("Startup discovery complete: %d markets", discovered_count)
```

**Critical:** Constructor dependency injection — `MarketDiscoveryService` receives `GammaClient` and `MarketRegistry` instances, it does NOT import them or create them. This follows the architecture's DI pattern.

### `BotConfig` Extension

Add `data_file` to the `BotConfig` model:

```python
class BotConfig(BaseModel):
    leagues: list[LeagueConfig] = Field(min_length=1)
    btts: BttsConfig
    liquidity: LiquidityConfig
    timing: TimingConfig
    logging: LoggingConfig
    data_file: str  # Path to local JSON data file with games/markets
```

And update `config_btts.example.yaml`:

```yaml
data_file: "games-data.json"
```

### `MarketRegistry.register()` — Existing Behavior Note

The current `MarketRegistry.register()` raises `ValueError` if the `token_id` is already registered. The `MarketDiscoveryService` **must** call `is_processed(token_id)` before `register()` to avoid this exception. This is the correct pattern — deduplication happens at the business logic layer (in `core/`), not in the data manager (in `state/`).

### Import Paths to Use

```python
# In gamma.py
import json
import logging
from pathlib import Path

# In market_discovery.py
from __future__ import annotations
import logging
from datetime import datetime, timezone
from btts_bot.clients.gamma import GammaClient
from btts_bot.config import LeagueConfig
from btts_bot.state.market_registry import MarketRegistry

# In main.py (additions)
from btts_bot.clients.gamma import GammaClient
from btts_bot.core.market_discovery import MarketDiscoveryService
```

### Architecture Constraints to Enforce

From project enforcement guidelines:
- All I/O access for market source data confined to `clients/` package — `GammaClient` in `clients/gamma.py`, business logic in `core/market_discovery.py`
- `core/` modules receive client instances via constructor injection
- `state/` modules are pure data managers — `MarketRegistry` never initiates API calls
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- Return `None` on source read failures, caller handles gracefully
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Market-specific log messages include `[Home vs Away]` prefix

From architecture anti-patterns to avoid:
- Do NOT place market discovery logic in `clients/gamma.py` — it belongs in `core/`
- Do NOT hardcode the JSON data file path — read from config
- Do NOT catch exceptions without logging them
- Do NOT create a market entry without checking `is_processed()` first

### Testing Pattern

```python
# test_gamma_client.py
from btts_bot.clients.gamma import GammaClient

def test_fetch_games_success():
    """GammaClient returns games list from local JSON file."""
    client = GammaClient("games-data.json")
    result = client.fetch_games()
    assert isinstance(result, list) or result is None


# test_market_discovery.py
from datetime import datetime, timezone
from unittest.mock import MagicMock
from btts_bot.core.market_discovery import MarketDiscoveryService
from btts_bot.config import LeagueConfig
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.core.game_lifecycle import GameState

def _make_game(league="epl", home="Arsenal", away="Chelsea",
               kickoff="2026-04-01T15:00:00Z"):
    """Helper to create a game dict matching JSON structure."""
    return {
        "id": "123",
        "league": league,
        "home_team": home,
        "away_team": away,
        "kickoff_utc": kickoff,
        "polymarket": {
            "markets": [
                {
                    "condition_id": "0xabc",
                    "question": f"{home} vs. {away}: Both Teams to Score",
                    "outcome_label": "Both Teams to Score",
                    "market_type": "both_teams_to_score",
                    "token_ids": ["yes-token-id", "no-token-id"],
                }
            ]
        },
    }

def test_discovers_btts_markets_for_configured_leagues():
    gamma = MagicMock()
    gamma.fetch_games.return_value = [_make_game(league="epl"), _make_game(league="liga")]
    registry = MarketRegistry()
    leagues = [LeagueConfig(name="Premier League", abbreviation="epl")]
    service = MarketDiscoveryService(gamma, registry, leagues)
    count = service.discover_markets()
    assert count == 1  # Only EPL, not LIGA
    assert registry.is_processed("no-token-id")

def test_skips_already_processed_markets():
    gamma = MagicMock()
    gamma.fetch_games.return_value = [_make_game(), _make_game()]  # Same game twice
    registry = MarketRegistry()
    leagues = [LeagueConfig(name="Premier League", abbreviation="epl")]
    service = MarketDiscoveryService(gamma, registry, leagues)
    count = service.discover_markets()
    assert count == 1  # Second is duplicate, skipped
```

### Previous Story Context (1.6)

From Story 1.6 completion notes:
- `MarketRegistry.register()` raises `ValueError` on duplicate `token_id` — always check `is_processed()` first
- `MarketRegistry` stores `MarketEntry` with `GameLifecycle` in DISCOVERED state
- Pattern: `logger = logging.getLogger(__name__)` at module level
- Tests use `pytest` with `MagicMock` and `caplog`; use `unittest.mock.patch` for external deps
- 80 total tests at end of Story 1.6; this story should add ~15-20 new tests
- `ruff check` and `ruff format` must pass

### Project Structure Notes

This story is the first in Epic 2 — it transitions the bot from "project foundation" to "business logic." The two new files (`gamma.py`, `market_discovery.py`) establish the data flow pattern that all subsequent Epic 2 stories build on:

```
JSON file → GammaClient → MarketDiscoveryService → MarketRegistry
```

Story 2.2 (Scheduled Daily Market Fetch) will call `MarketDiscoveryService.discover_markets()` on a schedule via APScheduler. Story 2.3 (BTTS-No Token Selection) is largely handled here — the "No" token extraction logic is built into this story's `MarketDiscoveryService`. Story 2.4 (Liquidity Analysis) will consume markets from `MarketRegistry` and add orderbook analysis.

### References

- [Source: epics.md#Story 2.1: Market Discovery from JSON Data File] — all acceptance criteria
- [Source: architecture.md#Project Structure & Boundaries] — `clients/gamma.py` for source I/O, `core/market_discovery.py` for logic
- [Source: architecture.md#Project Structure & Boundaries] — `clients/gamma.py` for I/O, `core/market_discovery.py` for logic
- [Source: architecture.md#State Management Architecture] — `MarketRegistry` for market state, `token_id` as canonical key
- [Source: architecture.md#Enforcement Guidelines] — DI pattern, source I/O in `clients/`, no direct file reads in `core/`
- [Source: architecture.md#Data Flow] — `JSON file → GammaClient → MarketRegistry`
- [Source: architecture.md#Communication Patterns] — logging levels (INFO for discovery, DEBUG for skips)
- [Source: BTTS_FUNCTIONAL_REQUIREMENTS.md#Section 5] — JSON data file structure with game/market/token schema
- [Source: prd.md#FR5] — Fetch BTTS markets on startup
- [Source: prd.md#FR7] — Select "No" outcome token
- [Source: prd.md#FR8] — Skip already-processed markets

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

No blocking issues encountered. Ruff auto-fixed 11 unused import warnings in test files.

### Completion Notes List

- Implemented `GammaClient` in `btts_bot/clients/gamma.py` — reads local JSON file, validates payload shape, returns `list[dict]` or `None` on failure.
- Implemented `MarketDiscoveryService` in `btts_bot/core/market_discovery.py` — filters by configured league abbreviations (case-insensitive), extracts No token (index 1), deduplicates via `is_processed()` before `register()`, logs per-league and total counts.
- Extended `BotConfig` with required `data_file: str` field; updated `config_btts.example.yaml`.
- Wired `GammaClient` and `MarketDiscoveryService` into `btts_bot/main.py` startup sequence via DI.
- 33 new tests added (6 in `test_gamma_client.py`, 18 in `test_market_discovery.py`, 9 updated/added in `test_main.py`). All 111 tests pass.
- `ruff check` zero issues; `ruff format` clean.

### File List

- `btts_bot/config.py` — added `data_file: str` field to `BotConfig`
- `btts_bot/clients/gamma.py` — replaced stub with full `GammaClient` implementation
- `btts_bot/core/market_discovery.py` — replaced stub with full `MarketDiscoveryService` implementation
- `btts_bot/main.py` — wired `GammaClient` + `MarketDiscoveryService` into startup
- `config_btts.example.yaml` — added `data_file` field
- `tests/test_gamma_client.py` — new test file (6 tests)
- `tests/test_market_discovery.py` — new test file (18 tests)
- `tests/test_main.py` — updated existing tests + added 3 new discovery-wiring tests
- `tests/test_config.py` — updated `VALID_CONFIG` and inline dicts to include `data_file`
