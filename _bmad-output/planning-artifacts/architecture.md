---
stepsCompleted:
  - 1
  - 2
  - 3
  - 4
  - 5
  - 6
  - 7
  - 8
inputDocuments:
  - prd.md
  - polymarket-api-research (agent-generated)
workflowType: 'architecture'
project_name: 'btts-bot'
user_name: 'Wolny'
date: '2026-03-27'
lastStep: 8
status: 'complete'
completedAt: '2026-03-28'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

28 functional requirements across 6 domains. The architectural center of gravity is the order lifecycle (FR12-21) -- 10 of 28 requirements directly concern placing, tracking, consolidating, and recovering orders. Market discovery (FR5-8) and liquidity analysis (FR9-11) are upstream pipelines feeding into this lifecycle. State management (FR22-24) and observability (FR25-28) are cross-cutting infrastructure concerns.

**Non-Functional Requirements:**

12 NFRs, heavily weighted toward reliability and integration resilience:
- **Reliability (NFR1-4):** 14-day continuous uptime, no single API failure can crash the bot, 60-second startup reconciliation, 5-minute game-start recovery window
- **Security (NFR5-7):** Credentials from env vars only, never logged, restrictive log file permissions
- **Integration (NFR8-10):** Retry with backoff on all CLOB calls, REST polling as authoritative over websockets for safety-critical state, graceful handling of unexpected API payloads
- **Performance (NFR11-12):** 10-second per-market orderbook analysis, 5-minute full daily cycle

**Scale & Complexity:**

- Primary domain: Backend automation / Fintech CLI bot
- Complexity level: High
- Estimated architectural components: 7-9 (config loader, CLOB client wrapper, market discovery service, liquidity analyser, order manager, game lifecycle handler, state reconciler, scheduler, logger)

### Technical Constraints & Dependencies

- **Language:** Python (mandated by `py-clob-client` SDK alignment)
- **External APIs:** Polymarket CLOB API (L0/L1/L2 auth tiers), Gamma API (market discovery), Data API (positions)
- **Authentication:** Three-phase -- derive API creds from private key (L1), then construct L2 client with proxy wallet and GNOSIS_SAFE signature type
- **No database, no web framework, no UI** -- single-process, potentially single-threaded
- **Config read once at startup** -- changes require restart
- **Market data source:** JSON file (not live API query) for daily BTTS market discovery
- **Tick size constraints:** Market-dependent (0.01 to 0.0001), must be fetched per-token
- **Order constraints:** Min order size per-market, price range tick_size to 1-tick_size, batch limits (15 orders per POST, 3000 per cancel)
- **Rate limits:** 9,000 req/10s general CLOB, 1,500/10s for orderbook, 500/10s for Gamma events, 150/10s for Data API positions -- comfortable for ~40 games/week throughput
- **Websocket heartbeat caution:** If heartbeat feature is enabled and missed (~15s), ALL open orders are auto-cancelled -- this is dangerous for a bot that needs orders to persist across restarts

### Cross-Cutting Concerns Identified

1. **Error Resilience & Retry Strategy** -- Every external API call (CLOB, Gamma, Data API) needs non-fatal error handling with exponential backoff. Retryable vs non-retryable errors must be distinguished (e.g., "not enough balance" is non-retryable, 500/425/429 are retryable).

2. **Duplicate Prevention** -- Must be enforced at multiple levels: before placing buy orders (check in-memory state + API reconciliation), before placing sell orders (check existing live sells for that market), and during game-start recovery (don't double-place sells).

3. **Timing & Scheduling** -- Three timing domains: daily market fetch (configurable UTC hour + on startup), pre-kickoff window (configurable minutes before game start), and game-start detection/recovery (immediate + 1-minute verification + retry). Each game has its own lifecycle clock.

4. **Credential Hygiene** -- Private key, API key/secret/passphrase must never appear in logs, error messages, or state. Environment variables only. Log file permissions owner-only.

5. **Structured Observability** -- Every log entry needs: timestamp, log level, logger name, market identifier (home vs away), event datetime. Must support both file and console output simultaneously.

6. **API Source of Truth Hierarchy** -- REST API polling is authoritative for safety-critical operations (fills, cancellations). Websockets (if used) are supplementary for latency optimization only. The Data API is authoritative for position balances.

## Starter Template Evaluation

### Primary Technology Domain

Python backend automation / CLI bot, based on project requirements analysis. No web framework, no database, no UI -- pure Python with external API integrations.

### Starter Options Considered

| Option | Description | Verdict |
|---|---|---|
| `uv init` (application mode) | Creates `pyproject.toml`, `.python-version`, `main.py`, `.gitignore`. Minimal, modern, fast. | **Selected** |
| `cookiecutter` templates | Over-engineered for a single-purpose bot. Generates docs, CI, tests scaffolding we don't need for MVP. | Rejected -- too much boilerplate |
| `poetry new` | Similar to uv but slower resolver, heavier tooling. uv is the operator's preference. | Rejected -- user prefers uv |
| Manual `pyproject.toml` | No scaffolding benefit. | Rejected |

### Selected Starter: `uv init` (application mode)

**Rationale for Selection:**

- Operator explicitly chose `uv` as package manager
- Application mode (not library) -- no `src/` layout needed, generates `main.py` entry point
- Fastest dependency resolution available
- Native `pyproject.toml` management with `uv add`/`uv remove`
- Lockfile (`uv.lock`) for reproducible deployments on the Ubuntu target machine
- Handles Python version pinning via `.python-version`

**Initialization Command:**

```bash
uv init btts-bot --python 3.14
cd btts-bot
uv add py-clob-client pyyaml requests pydantic pydantic-settings apscheduler
uv add --dev ruff
```

> Note: If `py-clob-client` fails to install on Python 3.14 due to dependency compilation issues, fall back to `--python 3.13`.

**Architectural Decisions Provided by Starter:**

**Language & Runtime:**
- Python 3.14 (latest stable, bugfix status) with fallback to 3.13
- Version pinned in `.python-version` for consistency across environments

**Package Management:**
- `uv` for dependency resolution, virtual environment management, and lockfile
- `pyproject.toml` as the single source of truth for project metadata and dependencies
- `uv.lock` checked into version control for reproducible installs

**Linting & Formatting:**
- `ruff` for both linting and formatting (replaces black + flake8 + isort)
- Configuration in `pyproject.toml` under `[tool.ruff]`

**Build Tooling:**
- No build step needed -- pure Python application, run directly with `uv run main.py` or `python main.py` after `uv sync`

**Testing Framework:**
- Deferred to post-MVP. When added: `pytest` via `uv add --dev pytest`

**Code Organization:**
- Flat application structure (not `src/` layout) -- appropriate for a single-purpose bot
- Entry point: `main.py` (to be renamed/restructured during architecture decisions)

**Development Experience:**
- `uv run` for running the bot with automatic dependency sync
- `uv sync` + virtualenv activation for direct `python` execution
- `ruff check` and `ruff format` for code quality

**Note:** Project initialization using this command should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. Process model: Synchronous main loop + threading for time-critical paths
2. Game lifecycle: Per-game state machine with explicit states and transitions
3. State management: Domain-separated state managers
4. API client architecture: Thin wrappers per API + shared retry decorator
5. Config validation: Pydantic models with pydantic-settings for env vars

**Important Decisions (Shape Architecture):**
6. Scheduling: APScheduler with BackgroundScheduler for dynamic per-game timing
7. Logging: Python stdlib `logging` with LoggerAdapter for market context

**Deferred Decisions (Post-MVP):**
- Testing framework (pytest when ready)
- Type checking / mypy
- CI/CD pipeline
- Graceful shutdown / signal handling
- Alerting integrations (Telegram/Discord)

### Application Architecture & Process Model

- **Decision:** Synchronous main loop + dedicated threads for time-critical paths
- **Rationale:** The main trading loop (discover -> analyse -> buy -> track fills -> sell) is inherently sequential and simple to reason about. However, multiple games can kick off simultaneously and game-start recovery is time-critical (5-minute window per NFR4). Dedicated threads for game-start recovery ensure concurrent handling without blocking the main loop.
- **Affects:** All components -- defines the concurrency model for the entire bot

### Scheduling & Timing Strategy

- **Decision:** APScheduler (BackgroundScheduler)
- **Rationale:** The bot has dynamic per-game timing -- each game has its own kickoff time requiring individually scheduled pre-kickoff consolidation and game-start recovery. APScheduler handles this natively with date triggers. Its BackgroundScheduler runs in a separate thread, integrating cleanly with the synchronous + threading model. Also supports interval triggers for periodic fill polling and cron-like triggers for daily market fetch.
- **Affects:** Daily market fetch scheduling, per-game lifecycle transitions, periodic polling loops

### API Client Architecture & Retry Strategy

- **Decision:** Thin wrapper per API + shared retry decorator
- **Rationale:** Three external APIs (CLOB, Gamma, Data API) each have different auth requirements, response formats, and error semantics. Thin wrappers keep API-specific concerns isolated. A shared `@with_retry` decorator ensures consistent exponential backoff with jitter across all APIs, distinguishing retryable errors (425, 429, 500, 503) from non-retryable ones ("not enough balance", "minimum tick size").
- **Components:**
  - `ClobClientWrapper` -- wraps `py-clob-client`, manages L0/L1/L2 auth, tick-size caching
  - `GammaClient` -- uses `requests` directly for market discovery, sport/league filtering
  - `DataApiClient` -- uses `requests` directly for position queries via proxy wallet address
  - `@with_retry` decorator -- shared retry logic with configurable backoff, max retries, retryable status codes
- **Affects:** All external API interactions, error resilience (NFR2, NFR8)

### State Management Architecture

- **Decision:** Domain-separated state managers
- **Rationale:** Maps naturally to domain boundaries. Each manager owns its slice of state and deduplication logic. On startup, each manager reconciles independently from the relevant API.
- **Components:**
  - `MarketRegistry` -- discovered markets, token IDs, kickoff times, league associations. Owns "has this market been processed?" deduplication.
  - `OrderTracker` -- buy orders, sell orders, order IDs, order statuses. Owns duplicate buy/sell prevention (`has_buy_order(market_id)`, `has_sell_order(market_id)`).
  - `PositionTracker` -- fill accumulations per market, current position sizes. Owns "has fills reached min threshold for sell?" logic.
- **Affects:** Duplicate prevention (FR15, FR16), startup reconciliation (FR23), all order lifecycle operations

### Game Lifecycle Management

- **Decision:** Per-game state machine with explicit states and transitions
- **States:** `DISCOVERED` -> `ANALYSED` -> `BUY_PLACED` -> `FILLING` -> `SELL_PLACED` -> `PRE_KICKOFF` -> `GAME_STARTED` -> `RECOVERY_COMPLETE` -> `DONE`
- **Additional terminal states:** `SKIPPED` (insufficient liquidity), `EXPIRED` (buy order expired unfilled)
- **Rationale:** The "zero unmanaged positions" safety invariant (NFR: 100% position coverage) is a state machine property -- every game in `FILLING` or `SELL_PLACED` must reach `RECOVERY_COMPLETE` or `DONE`. Explicit states make this auditable. APScheduler date triggers drive time-based transitions (pre-kickoff, game-start) per-game at their specific kickoff times.
- **Affects:** Core order lifecycle (FR12-21), game-start recovery (FR19-21), pre-kickoff consolidation (FR17-18)

### Logging & Observability

- **Decision:** Python stdlib `logging` with `LoggerAdapter` for market context
- **Rationale:** PRD specifies human-readable logs for weekly manual review, not machine-parseable JSON. Stdlib logging is zero-dependency, well-understood, and supports dual output (file + console) natively. `LoggerAdapter` allows binding market identifiers (home vs away) and event datetimes to a logger instance so all messages from that context include them automatically. `RotatingFileHandler` manages long-running file growth.
- **Configuration:** Per-module loggers via `logging.getLogger(__name__)`, configured programmatically at startup from YAML config (log level, file path, rotation settings)
- **Affects:** All components (FR25-28), credential hygiene (NFR5 -- custom filter to redact secrets)

### Configuration & Environment

- **Decision:** Pydantic models with `pydantic-settings` for unified config + env var validation
- **Rationale:** Config validation is critical at startup (FR4: exit with clear error on failure). Pydantic provides typed config objects with automatic validation, type coercion, default values, and clear error messages. `pydantic-settings` unifies YAML config loading and environment variable reading into a single validated model, eliminating `python-dotenv` as a separate dependency.
- **Components:**
  - `BotConfig` -- top-level settings model
  - `LeagueConfig` -- per-league settings (name, abbreviation)
  - `BttsConfig` -- order sizing, spread, min order size, cancellation timing
  - `LiquidityConfig` -- three-case bid-depth analysis thresholds
  - `TimingConfig` -- daily fetch hour, polling intervals
  - `LoggingConfig` -- log file path, log level, rotation settings
- **Affects:** All components at startup (FR1-4), operator workflow (config edit + restart)

### Decision Impact Analysis

**Implementation Sequence:**
1. Project initialization (uv init, dependencies)
2. Configuration & validation (Pydantic models, YAML loading, env var reading)
3. API client wrappers (CLOB, Gamma, Data API) + retry decorator
4. State managers (MarketRegistry, OrderTracker, PositionTracker)
5. Game lifecycle state machine
6. Market discovery pipeline
7. Liquidity analysis engine
8. Order execution (buy placement, fill tracking, sell placement)
9. Scheduling (APScheduler: daily fetch, per-game timers, polling)
10. Pre-kickoff consolidation + game-start recovery
11. Startup reconciliation
12. Logging configuration + main entry point

**Cross-Component Dependencies:**
- Game lifecycle state machine depends on: OrderTracker, PositionTracker, ClobClientWrapper
- Order execution depends on: MarketRegistry (token IDs), LiquidityConfig (thresholds), ClobClientWrapper
- Scheduling depends on: MarketRegistry (kickoff times), game lifecycle (transition triggers)
- Startup reconciliation depends on: all three state managers + all three API clients

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified:** 12 areas where AI agents could make different choices, across naming, structure, format, communication, and process patterns.

### Naming Patterns

**Code Naming Conventions (PEP 8 strict):**

- Modules/files: `snake_case.py` (e.g., `clob_client.py`, `market_registry.py`, `game_lifecycle.py`)
- Classes: `PascalCase` (e.g., `OrderTracker`, `GameLifecycle`, `BotConfig`)
- Functions/methods: `snake_case` (e.g., `place_buy_order`, `get_top_bid_levels`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`, `CLOB_API_URL`)
- Private methods/attrs: single leading underscore `_internal_method`
- Enum members: `UPPER_SNAKE_CASE` (e.g., `GameState.BUY_PLACED`)

**Market Identifier Conventions:**

- Internal state keys: Use `token_id` (the BTTS-No token ID) as the canonical identifier for all state lookups
- Log messages: Always include `"[Home vs Away]"` as the human-readable identifier plus `token_id` for traceability
- Variable naming: `token_id` for the No outcome token, `condition_id` for the market condition, never abbreviate to `tid` or `cid`

### Structure Patterns

**Module Organization:**

```
btts_bot/
  __init__.py
  main.py              # Entry point, main loop
  config.py            # Pydantic config models
  constants.py         # Shared constants (API URLs, enums)
  retry.py             # @with_retry decorator
  logging_setup.py     # Logging configuration
  clients/
    __init__.py
    clob.py            # ClobClientWrapper
    gamma.py           # GammaClient
    data_api.py        # DataApiClient
  state/
    __init__.py
    market_registry.py # MarketRegistry
    order_tracker.py   # OrderTracker
    position_tracker.py # PositionTracker
  core/
    __init__.py
    game_lifecycle.py  # GameLifecycle state machine
    market_discovery.py # Market discovery pipeline
    liquidity.py       # Three-case liquidity analysis
    order_execution.py # Buy/sell order placement logic
    reconciliation.py  # Startup state reconciliation
    scheduling.py      # APScheduler setup and job definitions
```

**Rule:** One class per file for major components. Utility functions can share a module. No nested packages beyond one level.

### Format Patterns

**Config YAML Canonical Structure:**

```yaml
leagues:
  - name: "Premier League"
    abbreviation: "EPL"
  - name: "La Liga"
    abbreviation: "LIGA"

btts:
  order_size: 30
  price_diff: 0.02
  min_order_size: 5
  buy_expiration_hours: 12

liquidity:
  standard_depth: 1000
  deep_book_threshold: 2000
  low_liquidity_total: 500
  tick_offset: 0.01

timing:
  daily_fetch_hour_utc: 23
  fill_poll_interval_seconds: 30
  pre_kickoff_minutes: 10

logging:
  level: "INFO"
  file_path: "btts_bot.log"
  max_bytes: 10485760
  backup_count: 5
```

### Communication Patterns

**State Machine Transitions:**

- All state transitions go through `GameLifecycle.transition(new_state)` which validates the transition is legal, logs it, and raises `InvalidTransitionError` if not
- No direct mutation of game state from outside the `GameLifecycle` class
- Transition methods return `bool` (success/failure), never raise on expected failures (e.g., order already cancelled)

**Logging Levels:**

- `DEBUG`: API request/response details, state machine transition details, orderbook raw data
- `INFO`: Market discovered, buy order placed, fill accumulated, sell order placed, game-start recovery triggered, state transition completed
- `WARNING`: Retryable API error occurred, low liquidity skip, order expired unfilled, unexpected API response format
- `ERROR`: Non-retryable API error, game-start recovery failed after retries, duplicate order detected and blocked
- `CRITICAL`: Bot startup failure (bad config, auth failure), unrecoverable state (should never happen in normal operation)

**Log Message Format:**

```
%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
```

Example: `2026-03-28 15:00:12 | INFO     | btts_bot.core.order_execution | [Arsenal vs Chelsea] Buy order placed: token=7132..., price=0.48, size=30`

### Process Patterns

**Error Handling:**

1. All API calls must be wrapped with `@with_retry`. No bare `client.method()` calls in business logic.
2. Retry decorator catches `requests.RequestException` and `Exception`, checks for retryable status codes (425, 429, 500, 503), applies exponential backoff with jitter (base=1s, max=30s, max_retries=5).
3. Non-retryable errors (400 validation, "not enough balance", "minimum tick size") are re-raised immediately.
4. After max retries exhausted: Log at ERROR level and return `None` (not raise). The caller must handle `None` gracefully -- skip the operation for this market and continue to the next.
5. Never catch and silently swallow exceptions. Every `except` block must log.

**Duplicate Prevention Pattern:**

```python
# Before any order placement:
if order_tracker.has_buy_order(token_id):
    logger.warning(f"[{market_name}] Duplicate buy prevented")
    return
```

This check happens at the business logic layer, not in the API wrapper.

**Startup Reconciliation Pattern:**

1. Query CLOB API for all open orders -> populate `OrderTracker`
2. Query Data API for all positions -> populate `PositionTracker`
3. Cross-reference: any position with no matching sell order -> immediately place sell
4. Mark reconciled games in `MarketRegistry` with appropriate lifecycle state

### Enforcement Guidelines

**All AI Agents MUST:**

- Follow PEP 8 naming conventions exactly as specified above
- Use `token_id` as the canonical state key for all per-market lookups
- Route all state transitions through `GameLifecycle.transition()`
- Wrap all API calls with `@with_retry` -- no exceptions
- Include `[Home vs Away]` prefix in all market-specific log messages
- Return `None` on exhausted retries, never crash the bot
- Check `OrderTracker` before every order placement for duplicates

**Anti-Patterns to Avoid:**

- Direct state mutation on `GameLifecycle` (e.g., `game.state = GameState.DONE`)
- Bare API calls without retry wrapper
- Logging credentials or API keys at any level
- Using `condition_id` as state key (use `token_id`)
- Catching exceptions without logging them
- Placing orders without checking for duplicates first

## Project Structure & Boundaries

### Complete Project Directory Structure

```
btts-bot/
├── .python-version               # Python 3.14 (fallback 3.13)
├── .gitignore                    # Generated by uv init
├── pyproject.toml                # Project metadata, dependencies, ruff config
├── uv.lock                       # Lockfile for reproducible installs
├── config_btts.yaml              # Default operator config (not committed with secrets)
├── config_btts.example.yaml      # Example config for documentation
├── btts_bot/
│   ├── __init__.py               # Package marker
│   ├── __main__.py               # python -m btts_bot entry: imports and calls main()
│   ├── main.py                   # Entry point: arg parsing, startup, main loop
│   ├── config.py                 # Pydantic config models (BotConfig, LeagueConfig, etc.)
│   ├── constants.py              # Shared constants: API URLs, GameState enum, tick defaults
│   ├── retry.py                  # @with_retry decorator (exponential backoff + jitter)
│   ├── logging_setup.py          # Configure stdlib logging, RotatingFileHandler, secret filter
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── clob.py               # ClobClientWrapper — py-clob-client L0/L1/L2, tick cache
│   │   ├── gamma.py              # GammaClient — requests-based market discovery
│   │   └── data_api.py           # DataApiClient — requests-based position queries
│   ├── state/
│   │   ├── __init__.py
│   │   ├── market_registry.py    # MarketRegistry — discovered markets, token IDs, kickoffs
│   │   ├── order_tracker.py      # OrderTracker — buy/sell orders, duplicate prevention
│   │   └── position_tracker.py   # PositionTracker — fill accumulation, min-threshold logic
│   └── core/
│       ├── __init__.py
│       ├── game_lifecycle.py     # GameLifecycle — per-game state machine, transitions
│       ├── market_discovery.py   # Market discovery pipeline — JSON fetch, league filter
│       ├── liquidity.py          # Three-case bid-depth analysis (A/B/C)
│       ├── order_execution.py    # Buy/sell order placement, price derivation
│       ├── reconciliation.py     # Startup state reconciliation from API
│       └── scheduling.py         # APScheduler setup: daily fetch, per-game timers, polling
└── tests/                        # Deferred to post-MVP
    └── __init__.py
```

### Architectural Boundaries

**API Boundaries:**

| Boundary | Module | External System | Auth Required |
|---|---|---|---|
| Order management | `clients/clob.py` | Polymarket CLOB API | L2 (GNOSIS_SAFE) |
| Market discovery | `clients/gamma.py` | Polymarket Gamma API | None |
| Position queries | `clients/data_api.py` | Polymarket Data API | None |

All external API access is confined to the `clients/` package. Business logic modules in `core/` and `state/` never import `requests` or `py-clob-client` directly — they receive client instances via constructor injection.

**Component Boundaries:**

- `state/` modules are pure data managers — they hold state and answer queries but never initiate API calls or schedule jobs
- `core/` modules contain business logic — they orchestrate state changes by calling `state/` managers and `clients/` wrappers
- `clients/` modules are thin I/O wrappers — they translate between Polymarket API formats and internal domain types
- `main.py` is the composition root — it instantiates all components, wires dependencies, and starts the main loop

**Data Boundaries:**

- In-memory only — no database, no state files
- Polymarket API is the source of truth; in-memory state is a performance cache
- Config is immutable after startup — loaded once from YAML + env vars into frozen Pydantic models

### Requirements to Structure Mapping

**FR Category → Module Mapping:**

| FR Category | FRs | Primary Module(s) |
|---|---|---|
| Configuration & Initialization | FR1-4 | `config.py`, `main.py`, `clients/clob.py` |
| Market Discovery & Selection | FR5-8 | `core/market_discovery.py`, `clients/gamma.py`, `state/market_registry.py` |
| Liquidity Analysis & Pricing | FR9-11 | `core/liquidity.py` |
| Order Execution & Position Mgmt | FR12-16 | `core/order_execution.py`, `clients/clob.py`, `state/order_tracker.py`, `state/position_tracker.py` |
| Pre-Kickoff & Game-Start | FR17-21 | `core/game_lifecycle.py`, `core/order_execution.py`, `core/scheduling.py` |
| State Management & Recovery | FR22-24 | `state/*`, `core/reconciliation.py`, `main.py` |
| Operational Observability | FR25-28 | `logging_setup.py`, `retry.py` (all modules emit logs) |

**Cross-Cutting Concerns → Location:**

| Concern | Primary Location | Enforcement |
|---|---|---|
| Retry & error resilience | `retry.py` (`@with_retry`) | All `clients/` methods decorated |
| Duplicate prevention | `state/order_tracker.py` | Checked in `core/order_execution.py` before every placement |
| Credential hygiene | `logging_setup.py` (secret filter) | Filter strips patterns matching keys/secrets |
| Market context in logs | `logging_setup.py` (LoggerAdapter) | All `core/` modules use adapted loggers |
| Game timing/scheduling | `core/scheduling.py` | APScheduler date triggers per game |
| State machine integrity | `core/game_lifecycle.py` | All transitions through `transition()` method |

### Data Flow

```
                    ┌──────────────────────────────────────────────────────┐
                    │                  STARTUP                             │
                    │                                                      │
                    │  config.yaml + env vars → BotConfig (Pydantic)       │
                    │  CLOB API (open orders) → OrderTracker              │
                    │  Data API (positions)   → PositionTracker           │
                    │  Cross-reference: position without sell → place sell │
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │              DAILY MARKET FETCH                       │
                    │                                                       │
                    │  JSON file → GammaClient → MarketRegistry            │
                    │  For each new market:                                 │
                    │    MarketRegistry.is_processed(token_id)?  → skip    │
                    │    OrderTracker.has_buy_order(token_id)?   → skip    │
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │            PER-MARKET ANALYSIS & BUY                  │
                    │                                                       │
                    │  ClobClientWrapper.get_orderbook(token_id)           │
                    │  → liquidity.analyse(orderbook) → buy_price          │
                    │  → order_execution.place_buy(token_id, buy_price)    │
                    │  → OrderTracker.record_buy(token_id, order_id)       │
                    │  → GameLifecycle: DISCOVERED → ANALYSED → BUY_PLACED │
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │              FILL POLLING LOOP                        │
                    │                                                       │
                    │  ClobClientWrapper.get_order(order_id) → fills       │
                    │  → PositionTracker.accumulate(token_id, fill_size)   │
                    │  → if accumulated >= min_order_size:                  │
                    │      order_execution.place_sell(token_id, sell_price)│
                    │      OrderTracker.record_sell(token_id, order_id)    │
                    │  → GameLifecycle: BUY_PLACED → FILLING → SELL_PLACED│
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │           PRE-KICKOFF CONSOLIDATION                   │
                    │  (APScheduler: kickoff_time - pre_kickoff_minutes)    │
                    │                                                       │
                    │  Cancel unfilled sells → re-create single sell at    │
                    │  buy_price → cancel unfilled buy                      │
                    │  → GameLifecycle: SELL_PLACED → PRE_KICKOFF          │
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │            GAME-START RECOVERY                        │
                    │  (APScheduler: kickoff_time)                          │
                    │                                                       │
                    │  Detect order cancellation → re-place sell at        │
                    │  buy_price → wait 1 min → verify → retry if needed  │
                    │  → GameLifecycle: GAME_STARTED → RECOVERY_COMPLETE   │
                    └──────────────────────────────────────────────────────┘
```

### Development Workflow

**Running the bot:**
```bash
uv run python -m btts_bot                              # Default config
uv run python -m btts_bot --config /path/to/config.yaml  # Custom config
```

**Code quality:**
```bash
uv run ruff check btts_bot/     # Lint
uv run ruff format btts_bot/    # Format
```

**Adding dependencies:**
```bash
uv add <package>        # Runtime dependency
uv add --dev <package>  # Dev dependency
```

**Deployment (Ubuntu target):**
```bash
uv sync                 # Install from lockfile
python -m btts_bot      # Run directly after sync
```

## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:**
All technology choices are compatible. Python 3.14 + uv + py-clob-client + pydantic + apscheduler have no version conflicts. The synchronous main loop + APScheduler BackgroundScheduler + dedicated threads for game-start recovery form a consistent threading model. Pydantic-settings unifies config + env vars cleanly, with no overlap after dropping python-dotenv.

**Pattern Consistency:**
PEP 8 naming is applied uniformly across all modules (snake_case files, PascalCase classes, UPPER_SNAKE_CASE enums/constants). `token_id` as canonical state key is enforced in state managers, log messages, and order execution. `@with_retry` on all client methods and `LoggerAdapter` for market context are mandated with no exceptions.

**Structure Alignment:**
The `clients/` → `state/` → `core/` boundary is clean with no circular dependencies. `main.py` as composition root matches the dependency injection pattern. One class per file for major components is consistent with the module listing.

### Requirements Coverage Validation

**Functional Requirements — 28/28 Covered:**

| FR Category | FRs | Primary Module(s) |
|---|---|---|
| Configuration & Initialization | FR1-4 | `config.py`, `main.py`, `clients/clob.py` |
| Market Discovery & Selection | FR5-8 | `core/market_discovery.py`, `clients/gamma.py`, `state/market_registry.py` |
| Liquidity Analysis & Pricing | FR9-11 | `core/liquidity.py` |
| Order Execution & Position Mgmt | FR12-16 | `core/order_execution.py`, `state/order_tracker.py`, `state/position_tracker.py` |
| Pre-Kickoff & Game-Start | FR17-21 | `core/game_lifecycle.py`, `core/scheduling.py` |
| State Management & Recovery | FR22-24 | `state/*`, `core/reconciliation.py` |
| Operational Observability | FR25-28 | `logging_setup.py`, all modules |

**Non-Functional Requirements — 12/12 Covered:**

| NFR | Architectural Support |
|---|---|
| NFR1 (14-day uptime) | Non-fatal error handling, `@with_retry`, no-crash-on-failure rule |
| NFR2 (No single API crash) | `@with_retry` returns `None` on exhaustion, caller skips gracefully |
| NFR3 (60s startup reconciliation) | `core/reconciliation.py` — query CLOB + Data API, rebuild state |
| NFR4 (5-min game-start recovery) | Dedicated thread for game-start recovery, 1-min verify + retry |
| NFR5 (Credentials from env only) | `pydantic-settings` env var reading, secret filter in logging |
| NFR6 (No secrets in config) | YAML contains only operational params, creds via env vars |
| NFR7 (Restrictive log permissions) | `logging_setup.py` — file handler with owner-only permissions |
| NFR8 (Retry with backoff) | `@with_retry` decorator on all CLOB calls |
| NFR9 (REST > websocket for safety) | Websocket heartbeats skipped, REST polling authoritative |
| NFR10 (Handle unexpected payloads) | Non-retryable error catch + log, no crash |
| NFR11 (10s per-market analysis) | Synchronous per-market loop, single API call + analysis |
| NFR12 (5-min daily cycle) | Sequential processing of ~8-10 markets per day |

### Implementation Readiness Validation

**Decision Completeness:**
7/7 core architectural decisions documented with rationale, component names, and cross-component impact analysis. Implementation sequence defined (12 steps). Deferred decisions explicitly listed.

**Structure Completeness:**
Full directory tree with every file named and purpose-annotated. `__main__.py` included for `python -m` invocation. Architectural boundaries defined with API/component/data separation.

**Pattern Completeness:**
12 conflict points resolved. Code examples provided for critical patterns (duplicate prevention, startup reconciliation, log format). Anti-patterns explicitly listed. Enforcement guidelines for AI agents documented.

### Gap Analysis Results

**Critical Gaps:** None.

**Important Gaps Addressed:**

1. **`__main__.py` added to directory tree** — Required for `python -m btts_bot` invocation. Contents: import and call `main()` from `main.py`.

2. **Buy order expiration strategy clarified** — Buy orders use the Polymarket GTD (Good Til Date) order type with a Unix timestamp calculated as `now + buy_expiration_hours`. Polymarket handles cancellation server-side — no APScheduler job needed for buy expiration.

**Nice-to-Have Gaps Noted:**

3. **Tick-size cache is per-session** — The `ClobClientWrapper` caches tick sizes per token ID in memory. Since tick sizes do not change during a market's lifetime, no invalidation is needed. Cache is naturally cleared on bot restart.

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context thoroughly analysed (28 FRs, 12 NFRs, 6 cross-cutting concerns)
- [x] Scale and complexity assessed (High complexity, 7-9 components)
- [x] Technical constraints identified (3 APIs, auth tiers, rate limits, websocket risks)
- [x] Cross-cutting concerns mapped (6 concerns with enforcement locations)

**Architectural Decisions**

- [x] Critical decisions documented with rationale (7 decisions)
- [x] Technology stack fully specified (Python 3.14, uv, py-clob-client, pydantic, apscheduler, ruff)
- [x] Integration patterns defined (thin wrappers, constructor injection, retry decorator)
- [x] Performance considerations addressed (10s per-market, 5-min daily cycle)

**Implementation Patterns**

- [x] Naming conventions established (PEP 8, token_id canonical key, log format)
- [x] Structure patterns defined (one class per file, max one nesting level)
- [x] Communication patterns specified (state machine transitions, logging levels)
- [x] Process patterns documented (error handling, duplicate prevention, reconciliation)

**Project Structure**

- [x] Complete directory structure defined (all files annotated)
- [x] Component boundaries established (clients / state / core separation)
- [x] Integration points mapped (data flow diagram)
- [x] Requirements to structure mapping complete (FR → module table)

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High — all 28 FRs and 12 NFRs have explicit architectural support with named modules and defined patterns.

**Key Strengths:**

- Clean separation of concerns: I/O (clients) / data (state) / logic (core)
- "Zero unmanaged positions" invariant enforced through explicit state machine with auditable transitions
- Comprehensive retry and error resilience strategy prevents bot crashes
- Domain-separated state managers with clear ownership boundaries prevent duplicate orders
- GTD order type for buy expiration offloads timing to Polymarket server

**Areas for Future Enhancement:**

- Testing framework (pytest) — deferred to post-MVP
- Graceful shutdown / signal handling — Phase 2
- Alerting integrations (Telegram/Discord) — Phase 2
- Type checking with mypy — post-MVP
- CI/CD pipeline — when deployment matures beyond manual `uv sync`

### Implementation Handoff

**AI Agent Guidelines:**

- Follow all architectural decisions exactly as documented in this file
- Use implementation patterns consistently across all components
- Respect project structure and boundaries — no direct API imports in `core/` or `state/`
- Route all state transitions through `GameLifecycle.transition()`
- Wrap all API calls with `@with_retry` — no exceptions
- Refer to this document for all architectural questions

**First Implementation Priority:**

```bash
uv init btts-bot --python 3.14
cd btts-bot
uv add py-clob-client pyyaml requests pydantic pydantic-settings apscheduler
uv add --dev ruff
```

Then: create `btts_bot/` package structure, `config.py` with Pydantic models, and `__main__.py` entry point.
