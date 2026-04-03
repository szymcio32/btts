---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - prd.md
  - architecture.md
---

# btts-bot - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for btts-bot, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Operator can provide a YAML configuration file path via CLI argument, defaulting to `config_btts.yaml` in the project root
FR2: System can load league definitions, bet parameters, liquidity thresholds, timing, and logging settings from the YAML configuration file at startup
FR3: System can authenticate with the Polymarket CLOB API using private key and proxy wallet address from environment variables
FR4: System can validate configuration and credentials at startup, exiting with a non-zero exit code and clear error message on failure
FR5: System can fetch all BTTS markets for all configured leagues from a JSON data file once immediately on startup
FR6: System can fetch all BTTS markets for all configured leagues from a JSON data file once daily at a configured UTC hour
FR7: System can identify and select the "No" outcome token from each BTTS market
FR8: System can skip markets where a buy order has already been placed in the current session or detected via API reconciliation
FR9: System can analyse the top three bid levels of a BTTS-No token's orderbook to determine the optimal buy price using three-case logic (Case A: standard, Case B: deep book, Case C: thin liquidity)
FR10: System can derive the sell price as buy price plus a configured spread offset, capped at 0.99
FR11: System can skip markets where liquidity analysis determines conditions are unsuitable for entry
FR12: System can place a limit buy order with configured share amount and expiration time on the Polymarket CLOB for each viable BTTS-No market
FR13: System can track incremental fill accumulation on placed buy orders
FR14: System can place a limit sell order when accumulated buy fills reach the minimum order size threshold (5 shares)
FR15: System can prevent duplicate buy orders for any given market
FR16: System can prevent duplicate sell orders where existing live sell orders already cover the position
FR17: System can cancel all unfilled sell orders at a configurable time before kickoff and re-create a single consolidated sell order at the buy price
FR18: System can cancel unfilled buy orders at a configurable time before kickoff
FR19: System can detect when Polymarket automatically cancels all open orders at game start
FR20: System can re-place sell orders for all filled buy positions at the buy price after game-start cancellation
FR21: System can verify sell order placement 1 minute after game-start re-creation and retry until confirmed
FR22: System can maintain in-memory state of all processed markets, placed orders, fill accumulations, and active sell orders during operation
FR23: System can reconcile internal state with the Polymarket API on every startup by querying current open orders and positions
FR24: System can run continuously as a background process for 14+ days without requiring manual intervention or restart
FR25: System can log all operational events with timestamp, log level, logger name, and human-readable messages to both a log file and console simultaneously
FR26: System can include market identifiers (home team vs. away team) and event datetimes in log messages for traceability
FR27: System can handle individual API call failures without crashing, logging the error and continuing operation
FR28: System can exclude credentials from all log output and error messages

### NonFunctional Requirements

NFR1: The bot must run continuously for 14+ days without crashing or requiring manual restart under normal operating conditions.
NFR2: No single API call failure may terminate the bot process — all API errors must be caught, logged, and retried or skipped gracefully.
NFR3: After any bot restart (intentional or crash), the system must reach a fully operational state within 60 seconds by reconciling with the Polymarket API.
NFR4: Game-start sell re-creation must complete (including retry cycles) within 5 minutes of kickoff to minimize unmanaged position exposure.
NFR5: Private keys and wallet addresses must only be read from environment variables and must never appear in log files, error messages, console output, or any persisted data.
NFR6: Configuration files must not contain any credentials or secrets.
NFR7: Log files must be written with restrictive file permissions (owner-only read/write) to prevent credential-adjacent data exposure.
NFR8: All Polymarket CLOB API interactions must include retry logic with backoff for transient failures (network errors, 5xx responses).
NFR9: The system must not rely on Polymarket websocket events as the sole source of truth for safety-critical state transitions (fill detection, order cancellation). API polling must serve as the authoritative verification method.
NFR10: The system must handle Polymarket API response format changes or unexpected payloads gracefully — logging the anomaly without crashing.
NFR11: Orderbook analysis and buy order placement for a single market must complete within 10 seconds to avoid stale pricing data.
NFR12: The daily market fetch and processing cycle for all configured leagues must complete within 5 minutes to ensure all buy orders are placed well before kickoff windows begin.

### Additional Requirements

- Architecture specifies `uv init btts-bot --python 3.14` as the starter template with fallback to Python 3.13 — this must be Epic 1 Story 1
- Dependencies to install: `py-clob-client`, `pyyaml`, `requests`, `pydantic`, `pydantic-settings`, `apscheduler`; dev dependency: `ruff`
- Project structure follows flat application layout: `btts_bot/` package with `clients/`, `state/`, `core/` sub-packages
- All external API access confined to `clients/` package — business logic modules never import `requests` or `py-clob-client` directly
- Constructor dependency injection: `core/` modules receive client instances, not import them
- `@with_retry` decorator required on all API calls — exponential backoff with jitter, base=1s, max=30s, max_retries=5
- Retryable errors: 425, 429, 500, 503. Non-retryable: 400 validation, "not enough balance", "minimum tick size"
- After max retries exhausted: return `None`, caller handles gracefully (skip and continue)
- `token_id` (BTTS-No token ID) is the canonical identifier for all state lookups
- All state transitions routed through `GameLifecycle.transition()` — no direct state mutation
- GameState enum: DISCOVERED → ANALYSED → BUY_PLACED → FILLING → SELL_PLACED → PRE_KICKOFF → GAME_STARTED → RECOVERY_COMPLETE → DONE; terminal states: SKIPPED, EXPIRED
- Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- LoggerAdapter used for binding market context ([Home vs Away] + token_id) to all log messages
- RotatingFileHandler for log file management during long-running operation
- Secret filter in logging to redact credentials from any log output
- Log file permissions: owner-only read/write
- Buy orders use Polymarket GTD (Good Til Date) order type with Unix timestamp expiration
- Tick-size cache per token ID in ClobClientWrapper (per-session, no invalidation needed)
- Three-phase CLOB authentication: derive API creds from private key (L1), construct L2 client with proxy wallet and GNOSIS_SAFE signature type
- `__main__.py` entry point for `python -m btts_bot` invocation
- APScheduler BackgroundScheduler with date triggers for per-game timing (pre-kickoff, game-start)
- Websocket heartbeats explicitly avoided — risk of auto-cancelling all open orders on missed heartbeat
- Startup reconciliation pattern: query CLOB for open orders → OrderTracker, query Data API for positions → PositionTracker, cross-reference for orphaned positions → place sell

### UX Design Requirements

Not applicable — btts-bot is a headless CLI bot with no user interface.

### FR Coverage Map

FR1: Epic 1 — YAML config path via CLI argument
FR2: Epic 1 — Load config settings from YAML
FR3: Epic 1 — CLOB API authentication via env vars
FR4: Epic 1 — Config/credential validation at startup
FR5: Epic 2 — Fetch BTTS markets on startup
FR6: Epic 2 — Fetch BTTS markets daily at configured hour
FR7: Epic 2 — Select No outcome token
FR8: Epic 2 — Skip already-processed markets
FR9: Epic 2 — Three-case orderbook bid-depth analysis
FR10: Epic 2 — Sell price derivation (buy + spread, capped 0.99)
FR11: Epic 2 — Skip unsuitable liquidity markets
FR12: Epic 3 — Place limit buy orders
FR13: Epic 3 — Track incremental fill accumulation
FR14: Epic 3 — Place sell when fills reach threshold
FR15: Epic 3 — Prevent duplicate buy orders
FR16: Epic 3 — Prevent duplicate sell orders
FR17: Epic 4 — Pre-kickoff sell consolidation
FR18: Epic 4 — Pre-kickoff buy cancellation
FR19: Epic 4 — Detect game-start order cancellation
FR20: Epic 4 — Re-place sells after game-start
FR21: Epic 4 — 1-minute verify + retry on sell placement
FR22: Epic 1 (Story 1.6: MarketRegistry + GameLifecycle) + Epic 3 (Story 3.1: OrderTracker, Story 3.2: PositionTracker) — In-memory state maintenance
FR23: Epic 5 — Startup reconciliation from API
FR24: Epic 5 (Story 5.4) — 14-day continuous operation and state pruning
FR25: Epic 5 — Structured logging (file + console)
FR26: Epic 5 — Market identifiers in log messages
FR27: Epic 5 — Non-fatal API error handling
FR28: Epic 5 — Credential exclusion from logs

## Epic List

### Epic 1: Project Foundation & Configuration
The operator can initialise the bot project, configure leagues and trading parameters via YAML, authenticate with Polymarket, and get clear error feedback on misconfiguration.
**FRs covered:** FR1, FR2, FR3, FR4, FR22 (partial — MarketRegistry and GameLifecycle foundations)

### Epic 2: Market Discovery & Liquidity Analysis
The operator's bot can automatically discover BTTS markets across all configured leagues and determine optimal entry prices using orderbook analysis.
**FRs covered:** FR5, FR6, FR7, FR8, FR9, FR10, FR11

### Epic 3: Order Execution & Position Management
The operator's bot can place buy orders, track fills, and automatically place sell orders — managing the full entry-to-exit lifecycle for each market.
**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR22 (OrderTracker and PositionTracker complete the in-memory state)

### Epic 4: Pre-Kickoff & Game-Start Recovery
The operator's bot handles the critical kickoff window — consolidating sells before kickoff, surviving Polymarket's automatic order cancellation at game start, and ensuring zero unmanaged positions.
**FRs covered:** FR17, FR18, FR19, FR20, FR21

### Epic 5: Startup Reconciliation & Operational Resilience
The operator can restart the bot at any time (or recover from a crash) and it automatically rebuilds its state from Polymarket's API, resuming operation without losing track of any positions. The bot also maintains long-running stability through state pruning.
**FRs covered:** FR23, FR24, FR25, FR26, FR27, FR28

## Epic 1: Project Foundation & Configuration

The operator can initialise the bot project, configure leagues and trading parameters via YAML, authenticate with Polymarket, establish the game lifecycle state machine and market registry, and get clear error feedback on misconfiguration.

### Story 1.1: Initialize Project with uv and Package Structure

As an operator,
I want the bot project initialized with proper Python packaging and dependencies,
So that I have a working development environment to build upon.

**Acceptance Criteria:**

**Given** a fresh project directory
**When** `uv init btts-bot --python 3.14` is run and dependencies are added
**Then** `pyproject.toml` exists with all runtime dependencies (`py-clob-client`, `pyyaml`, `requests`, `pydantic`, `pydantic-settings`, `apscheduler`) and dev dependencies (`ruff`)
**And** the `btts_bot/` package exists with `__init__.py`, `__main__.py`, `main.py`, and sub-packages `clients/`, `state/`, `core/` each with `__init__.py`
**And** `uv run python -m btts_bot` executes without import errors (can print a startup message and exit)
**And** `config_btts.example.yaml` exists with the canonical config structure from Architecture
**And** `.python-version` is set to 3.14 (or 3.13 fallback)

### Story 1.2: Configuration Loading and Validation with Pydantic

As an operator,
I want the bot to load and validate my YAML configuration file at startup,
So that I get clear error messages if my config is malformed or missing required fields.

**Acceptance Criteria:**

**Given** a valid `config_btts.yaml` with leagues, btts, liquidity, timing, and logging sections
**When** the bot starts with `--config config_btts.yaml` or no argument (uses default path)
**Then** all configuration values are loaded into typed Pydantic models (`BotConfig`, `LeagueConfig`, `BttsConfig`, `LiquidityConfig`, `TimingConfig`, `LoggingConfig`)
**And** the `--config` CLI argument overrides the default config path

**Given** a YAML file with missing required fields or invalid types
**When** the bot starts
**Then** it exits with a non-zero exit code and a clear error message identifying which field is invalid
**And** no partial startup occurs

**Given** no config file exists at the specified path
**When** the bot starts
**Then** it exits with a non-zero exit code and a message indicating the file was not found

### Story 1.3: Structured Logging Setup

As an operator,
I want the bot to log all events with timestamps, levels, and context to both file and console,
So that I can monitor operations in real-time and review logs later for troubleshooting.

**Acceptance Criteria:**

**Given** a valid logging configuration (level, file_path, max_bytes, backup_count)
**When** the bot starts
**Then** a `RotatingFileHandler` is configured with the specified file path, max bytes, and backup count
**And** a console handler outputs to stdout simultaneously
**And** log format matches `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
**And** the log file is created with owner-only read/write permissions (0o600)

**Given** a log message is emitted from any module
**When** the message contains patterns matching private keys or API secrets
**Then** the secret filter redacts them before writing to file or console
**And** credentials never appear in any log output

> **Cross-Epic Dependency Note:** This story establishes the logging foundation (handlers, format, secret filter). Story 5.2 later adds `LoggerAdapter` for per-market context binding. All intermediate stories (Epics 2-4) should use standard module loggers; the market-context adapter is layered on in Epic 5 without requiring changes to the logging infrastructure created here.

### Story 1.4: Retry Decorator for API Resilience

> **Rationale:** This is an infrastructure story with indirect user value. The `@with_retry` decorator is a prerequisite for every API-calling story in Epics 2-5 (NFR2, NFR8). It is placed here to establish the pattern early, allowing all subsequent stories to focus on business logic rather than error handling boilerplate.

As an operator,
I want all API calls to automatically retry on transient failures with exponential backoff,
So that temporary network issues or server errors don't crash the bot or lose operations.

**Acceptance Criteria:**

**Given** an API call decorated with `@with_retry`
**When** the call fails with a retryable error (status 425, 429, 500, 503, or network error)
**Then** the decorator retries with exponential backoff (base=1s, max=30s) plus jitter, up to 5 retries
**And** each retry is logged at WARNING level

**Given** an API call fails with a non-retryable error (400, "not enough balance", "minimum tick size")
**When** the error is detected
**Then** the error is re-raised immediately without retry

**Given** an API call exhausts all 5 retries
**When** the final retry fails
**Then** the decorator returns `None` (does not raise)
**And** an ERROR level log message is emitted
**And** the caller handles `None` by skipping the operation for that market

### Story 1.5: Polymarket CLOB Client Authentication

As an operator,
I want the bot to authenticate with Polymarket using my environment variables,
So that it can place and manage orders on my behalf.

**Acceptance Criteria:**

**Given** environment variables are set for Polymarket private key and proxy wallet address
**When** the bot starts
**Then** `ClobClientWrapper` derives L1 API credentials from the private key
**And** constructs an L2 CLOB client with the proxy wallet address and GNOSIS_SAFE signature type
**And** the client is ready for order operations
**And** tick-size cache is initialized (empty, populated on first per-token query)

**Given** environment variables are missing or invalid
**When** the bot starts
**Then** it exits with a non-zero exit code and a clear error message (without exposing the credential values)

**Given** a successful authentication
**When** any module inspects log output
**Then** no private key, API key, API secret, or passphrase values appear in logs

### Story 1.6: Game Lifecycle State Machine and Market Registry

As an operator,
I want the bot to have a well-defined state machine for each game's lifecycle and a registry of discovered markets,
So that all downstream modules have a consistent foundation for state tracking and market identification.

**Acceptance Criteria:**

**Given** the `btts_bot/state/` package exists from Story 1.1
**When** the state module is implemented
**Then** `market_registry.py` provides a `MarketRegistry` class that stores discovered markets keyed by `token_id` with fields: condition ID, token IDs, kickoff time, league, and team names (home vs away)
**And** `MarketRegistry` provides query methods: `register(token_id, ...)`, `get(token_id)`, `is_processed(token_id)`, `all_markets()`
**And** `MarketRegistry` is a pure data manager — it holds state and answers queries but never initiates API calls

**Given** the `btts_bot/core/` package exists from Story 1.1
**When** the game lifecycle module is implemented
**Then** `game_lifecycle.py` provides a `GameState` enum with states: DISCOVERED, ANALYSED, BUY_PLACED, FILLING, SELL_PLACED, PRE_KICKOFF, GAME_STARTED, RECOVERY_COMPLETE, DONE, SKIPPED, EXPIRED
**And** `GameLifecycle` class owns the per-game state and enforces valid transitions via `transition(new_state)` method
**And** `transition()` raises `InvalidTransitionError` for illegal state changes
**And** all state transitions are logged at INFO level with the from/to states
**And** no direct mutation of game state is permitted outside `GameLifecycle.transition()`

**Given** `MarketRegistry` registers a new market
**When** the market is stored
**Then** a `GameLifecycle` instance is created for that market in DISCOVERED state
**And** the lifecycle instance is accessible via `MarketRegistry.get(token_id).lifecycle`

> **Cross-Epic Dependency Note:** `MarketRegistry` and `GameLifecycle` are created here because they are first consumed in Epic 2 (Story 2.1 for market registration, Story 2.4 for state transitions). `OrderTracker` and `PositionTracker` are introduced later in Epic 3 where they are first needed.

## Epic 2: Market Discovery & Liquidity Analysis

The operator's bot can automatically discover BTTS markets across all configured leagues and determine optimal entry prices using orderbook analysis.

### Story 2.1: Market Discovery from JSON Data File

As an operator,
I want the bot to fetch all BTTS markets for my configured leagues from the JSON data file,
So that it automatically identifies today's trading opportunities without manual market lookup.

**Acceptance Criteria:**

**Given** the bot has started with a valid config containing league definitions
**When** the market discovery pipeline runs (immediately on startup)
**Then** the GammaClient fetches BTTS markets from the JSON data file for all configured leagues
**And** each discovered market is registered in `MarketRegistry` (from Story 1.6) with its condition ID, token IDs, kickoff time, league, and team names (home vs away)
**And** each registered market receives a `GameLifecycle` instance in DISCOVERED state (from Story 1.6)
**And** discovery results are logged at INFO level with market count per league and `[Home vs Away]` identifiers

**Given** a league in the config has no BTTS markets in the JSON data file
**When** discovery runs for that league
**Then** the bot logs an INFO message indicating zero markets found for that league and continues to the next league

**Given** the JSON data file is unreachable or returns an error
**When** discovery runs
**Then** the `@with_retry` decorator handles the transient failure
**And** if retries are exhausted, the error is logged and discovery continues for remaining leagues (non-fatal)

### Story 2.2: Scheduled Daily Market Fetch

> **Cross-Epic Dependency Note:** This story introduces the APScheduler `BackgroundScheduler` instance. Epic 4 (Stories 4.1 and 4.2) reuses this same scheduler for per-game date triggers (pre-kickoff and game-start). The scheduler should be created as a shared infrastructure component injected into modules that need it.

As an operator,
I want the bot to automatically fetch new markets once daily at my configured UTC hour,
So that tomorrow's games are discovered and queued for trading without manual intervention.

**Acceptance Criteria:**

**Given** a valid `timing.daily_fetch_hour_utc` in the config (e.g., 23)
**When** the bot starts
**Then** an APScheduler cron-like job is registered to trigger market discovery daily at the configured UTC hour
**And** the scheduler runs in the background without blocking the main loop

**Given** the daily fetch triggers
**When** new markets are discovered
**Then** only markets not already in MarketRegistry are added (skip duplicates)
**And** newly discovered markets are logged at INFO level
**And** the entire daily fetch cycle completes within 5 minutes (NFR12)

### Story 2.3: BTTS-No Token Selection and Market Deduplication

As an operator,
I want the bot to correctly identify the "No" outcome token from each BTTS market and skip markets already being processed,
So that it targets the right token and never double-processes a market.

**Acceptance Criteria:**

**Given** a discovered BTTS market with multiple outcome tokens
**When** the bot processes the market
**Then** it identifies and selects the "No" outcome token using the token metadata
**And** records the `token_id` as the canonical identifier in MarketRegistry

**Given** a market whose `token_id` already exists in MarketRegistry (from current session or API reconciliation)
**When** the bot encounters it during discovery
**Then** it skips the market with a DEBUG log message
**And** no duplicate entry is created in MarketRegistry

**Given** a market whose `token_id` has an existing buy order in OrderTracker
**When** the bot encounters it during discovery
**Then** it skips the market with an INFO log message indicating a buy order already exists

### Story 2.4: Three-Case Orderbook Liquidity Analysis

As an operator,
I want the bot to analyse each market's orderbook and determine the optimal buy price using the three-case algorithm,
So that it enters at prices informed by real liquidity conditions rather than arbitrary levels.

**Acceptance Criteria:**

**Given** a viable BTTS-No token with `token_id`
**When** the bot fetches the orderbook via ClobClientWrapper
**Then** it retrieves the top three bid levels (L1, L2, L3) with their prices and sizes

**Given** an orderbook where total bid depth across top 3 levels >= `liquidity.standard_depth` and < `liquidity.deep_book_threshold` (Case A: standard)
**When** liquidity analysis runs
**Then** the buy price is set to the L3 bid price
**And** the game transitions to ANALYSED state via GameLifecycle

**Given** an orderbook where total bid depth >= `liquidity.deep_book_threshold` (Case B: deep book)
**When** liquidity analysis runs
**Then** the buy price is set to the L2 bid price

**Given** an orderbook where total bid depth >= `liquidity.low_liquidity_total` but < `liquidity.standard_depth` (Case C: thin liquidity)
**When** liquidity analysis runs
**Then** the buy price is set to L3 price minus `liquidity.tick_offset`

**Given** an orderbook where total bid depth < `liquidity.low_liquidity_total`
**When** liquidity analysis runs
**Then** the market is skipped with an INFO log message including the market name and depth values
**And** the game transitions to SKIPPED state

**Given** a determined buy price
**When** sell price derivation runs
**Then** the sell price is calculated as `buy_price + config.btts.price_diff`, capped at 0.99

**Given** the full per-market analysis pipeline (fetch orderbook + analyse + derive prices)
**When** timed
**Then** it completes within 10 seconds (NFR11)

## Epic 3: Order Execution & Position Management

The operator's bot can place buy orders, track fills, and automatically place sell orders — managing the full entry-to-exit lifecycle for each market.

### Story 3.1: Buy Order Placement with Duplicate Prevention

As an operator,
I want the bot to place limit buy orders at the analysed price for each viable market,
So that it enters positions automatically at optimal prices without risking duplicate orders.

> **Implementation Reality Note:** Story 2.3 already introduced a partial `OrderTracker` with buy-order recording/query methods and basic sell-order placeholders. Story 3.1 should extend that implementation to complete order tracking behavior rather than recreate `order_tracker.py` from scratch. Story 2.4 also already produces analysed markets via `MarketAnalysisPipeline`, so Story 3.1 should consume that existing `ANALYSED` state as its upstream handoff.

**Acceptance Criteria:**

**Given** the `btts_bot/state/` package from Story 1.1
**When** the order tracking module is implemented
**Then** `order_tracker.py` provides an `OrderTracker` class that stores buy and sell orders keyed by `token_id`
**And** `OrderTracker` provides methods: `record_buy(token_id, order_id, buy_price)`, `record_sell(token_id, order_id)`, `has_buy_order(token_id)`, `has_sell_order(token_id)`, `get_order(token_id)`
**And** `OrderTracker` is a pure data manager — it holds state and answers queries but never initiates API calls

**Given** a market that has been analysed with a valid buy price (GameState: ANALYSED)
**When** the order execution module processes the market
**Then** it checks `OrderTracker.has_buy_order(token_id)` first
**And** if no existing buy order, it fetches the tick size for the token via ClobClientWrapper (cached per-session)
**And** places a limit buy order on the Polymarket CLOB with the configured share amount (`btts.order_size`)
**And** the order uses GTD (Good Til Date) type with expiration timestamp calculated as `kickoff_time - btts.expiration_hour_offset`
**And** the order ID is recorded in OrderTracker via `record_buy(token_id, order_id, buy_price)`
**And** the game transitions to BUY_PLACED via GameLifecycle
**And** an INFO log is emitted: `[Home vs Away] Buy order placed: token=..., price=..., size=...`

**Given** `OrderTracker.has_buy_order(token_id)` returns `True`
**When** order placement is attempted
**Then** the buy is skipped with a WARNING log: `[Home vs Away] Duplicate buy prevented`
**And** no API call is made

**Given** the ClobClientWrapper returns `None` for the buy order (retries exhausted)
**When** the placement fails
**Then** the error is logged at ERROR level
**And** the game transitions to SKIPPED state
**And** the bot continues to the next market

### Story 3.2: Fill Accumulation Tracking via Polling

As an operator,
I want the bot to periodically check my buy orders for fills and track accumulated shares,
So that it knows when enough shares are filled to place a sell order.

**Acceptance Criteria:**

**Given** the `btts_bot/state/` package from Story 1.1
**When** the position tracking module is implemented
**Then** `position_tracker.py` provides a `PositionTracker` class that stores fill accumulations keyed by `token_id`
**And** `PositionTracker` provides methods: `accumulate(token_id, fill_size)`, `get_accumulated_fills(token_id)`, `has_reached_threshold(token_id, min_size)`
**And** `PositionTracker` is a pure data manager — it holds state and answers queries but never initiates API calls

**Given** one or more buy orders in BUY_PLACED or FILLING state
**When** the fill polling loop runs (at `timing.fill_poll_interval_seconds` intervals via APScheduler)
**Then** for each active buy order, it queries the CLOB API for current fill status via ClobClientWrapper
**And** new fills are accumulated in PositionTracker via `accumulate(token_id, fill_size)`
**And** the game transitions from BUY_PLACED to FILLING on first fill detection

**Given** a buy order has no new fills since the last poll
**When** the polling loop checks it
**Then** no state change occurs and no log is emitted (avoid log noise)

**Given** a buy order is fully filled or expired
**When** the polling loop detects this
**Then** the order status is updated in OrderTracker
**And** if expired with zero fills, the game transitions to EXPIRED state with an INFO log

**Given** the CLOB API returns an error during fill polling
**When** `@with_retry` exhausts retries
**Then** the error is logged and the bot continues polling other orders (non-fatal)

### Story 3.3: Automatic Sell Order Placement on Fill Threshold

As an operator,
I want the bot to automatically place sell orders when enough buy fills accumulate,
So that my exit orders are live as early as possible to capture the spread.

**Acceptance Criteria:**

**Given** accumulated fills for a token reach or exceed `btts.min_order_size` (5 shares)
**When** the fill tracking detects the threshold is crossed
**Then** it checks `OrderTracker.has_sell_order(token_id)` for duplicate prevention
**And** if no existing live sell order, it places a limit sell order at `buy_price + btts.price_diff` (capped at 0.99)
**And** the sell order size equals the total accumulated fill amount
**And** the order ID is recorded in OrderTracker via `record_sell(token_id, order_id)`
**And** the game transitions to SELL_PLACED via GameLifecycle
**And** an INFO log is emitted: `[Home vs Away] Sell order placed: token=..., price=..., size=...`

**Given** `OrderTracker.has_sell_order(token_id)` returns `True` (a live sell already covers the position)
**When** a new sell placement is attempted
**Then** the sell is skipped with a DEBUG log: `[Home vs Away] Duplicate sell prevented — live sell exists`
**And** no API call is made

**Given** additional fills arrive after the initial sell order was placed
**When** the new accumulated total exceeds the existing sell order size
**Then** the existing sell is cancelled and a new sell is placed for the updated total amount
**And** OrderTracker is updated with the new sell order ID

## Epic 4: Pre-Kickoff & Game-Start Recovery

The operator's bot handles the critical kickoff window — consolidating sells before kickoff, surviving Polymarket's automatic order cancellation at game start, and ensuring zero unmanaged positions.

### Story 4.1: Pre-Kickoff Sell Consolidation and Buy Cancellation

> **Dependency Note:** This story uses the APScheduler `BackgroundScheduler` introduced in Story 2.2 for per-game date triggers.

As an operator,
I want the bot to consolidate my sell orders and cancel unfilled buys before kickoff,
So that I have one maximum-size sell at the buy price for the best fill probability in the final minutes.

**Acceptance Criteria:**

**Given** a game with an active sell order and a known kickoff time
**When** the current time reaches `kickoff_time - timing.pre_kickoff_minutes`
**Then** an APScheduler date trigger fires for that specific game

**Given** the pre-kickoff trigger fires for a game in SELL_PLACED state
**When** the pre-kickoff handler runs
**Then** it cancels all unfilled sell orders for that token via ClobClientWrapper
**And** re-creates a single consolidated sell order at the buy price (not buy_price + spread) for the full accumulated position size
**And** updates OrderTracker with the new sell order ID
**And** the game transitions to PRE_KICKOFF via GameLifecycle
**And** an INFO log is emitted: `[Home vs Away] Pre-kickoff consolidation: sell at buy_price=..., size=...`

**Given** the game has an unfilled buy order at pre-kickoff time
**When** the pre-kickoff handler runs
**Then** the unfilled buy order is cancelled via ClobClientWrapper
**And** OrderTracker is updated to reflect the cancellation
**And** an INFO log is emitted: `[Home vs Away] Pre-kickoff buy cancelled`

**Given** the game is in FILLING state (has fills but no sell yet — fills below min threshold)
**When** the pre-kickoff trigger fires
**Then** a sell order is placed at the buy price for whatever accumulated fills exist (even if below min_order_size)
**And** the unfilled buy is cancelled
**And** the game transitions to PRE_KICKOFF

**Given** ClobClientWrapper returns `None` for a cancel or sell placement (retries exhausted)
**When** the pre-kickoff handler encounters the failure
**Then** the error is logged at ERROR level
**And** the game is flagged for priority handling during game-start recovery

### Story 4.2: Game-Start Order Cancellation Detection and Sell Re-Placement

As an operator,
I want the bot to detect when Polymarket cancels all orders at game start and immediately re-place my sell orders,
So that I never have an unmanaged position — the most critical safety requirement.

**Acceptance Criteria:**

**Given** a game with a known kickoff time and a filled position
**When** the current time reaches the kickoff time
**Then** an APScheduler date trigger fires and launches a dedicated thread for game-start recovery

**Given** the game-start recovery thread starts
**When** it queries the CLOB API for the sell order status
**Then** it detects that Polymarket has automatically cancelled the sell order
**And** immediately places a new sell order at the buy price for the full position size
**And** updates OrderTracker with the new sell order ID
**And** the game transitions to GAME_STARTED via GameLifecycle
**And** an INFO log is emitted: `[Home vs Away] Game-start recovery: sell re-placed at buy_price=..., size=...`

**Given** the game has no filled position (buy expired or was fully cancelled pre-kickoff)
**When** game-start recovery runs
**Then** it detects no position to protect
**And** the game transitions to DONE state
**And** an INFO log is emitted: `[Home vs Away] No position at game start — nothing to recover`

**Given** multiple games kick off simultaneously
**When** game-start triggers fire for each
**Then** each game gets its own dedicated thread for recovery
**And** recoveries proceed concurrently without blocking each other or the main loop

### Story 4.3: Post-Game-Start Sell Verification and Retry Loop

As an operator,
I want the bot to verify that sell orders are actually live after game-start re-placement and retry until confirmed,
So that transient API failures at the critical moment don't leave me with an unmanaged position.

**Acceptance Criteria:**

**Given** a sell order was re-placed during game-start recovery
**When** 1 minute has elapsed since the re-placement
**Then** the bot queries the CLOB API to verify the sell order exists and is active

**Given** the verification confirms the sell order is live
**When** the check completes
**Then** the game transitions to RECOVERY_COMPLETE via GameLifecycle
**And** an INFO log is emitted: `[Home vs Away] Game-start recovery verified — sell confirmed active`
**And** the recovery thread exits

**Given** the verification finds the sell order is missing or was cancelled
**When** the check detects the failure
**Then** the bot immediately re-places the sell order at the buy price
**And** waits 1 minute and verifies again
**And** this retry cycle continues until the sell is confirmed active
**And** each retry is logged at WARNING level: `[Home vs Away] Sell verification failed — retry #N`

**Given** the entire recovery process (detection + re-placement + verification + retries)
**When** timed from kickoff
**Then** it completes within 5 minutes under normal conditions (NFR4)

## Epic 5: Startup Reconciliation & Operational Resilience

The operator can restart the bot at any time (or recover from a crash) and it automatically rebuilds its state from Polymarket's API, resuming operation without losing track of any positions. The bot also maintains long-running stability through state pruning of completed games.

### Story 5.1: Startup State Reconciliation from Polymarket API

As an operator,
I want the bot to rebuild its internal state from the Polymarket API on every startup,
So that after a crash or intentional restart, no positions are orphaned and the bot resumes correctly.

**Acceptance Criteria:**

**Given** the bot starts (fresh start or restart after crash)
**When** the reconciliation module runs during startup
**Then** it queries the CLOB API for all open orders associated with the proxy wallet and populates OrderTracker with buy and sell orders (order IDs, token IDs, prices, sizes, statuses)
**And** it queries the Data API for all current positions and populates PositionTracker with fill amounts per token

**Given** reconciliation discovers a position (filled shares) with no matching active sell order
**When** the cross-reference check identifies the orphan
**Then** it immediately places a sell order at the buy price for that position via ClobClientWrapper
**And** records the sell in OrderTracker
**And** logs at WARNING level: `[Home vs Away] Orphaned position detected — sell placed at buy_price=..., size=...`

**Given** reconciliation discovers open buy orders
**When** the orders are loaded into OrderTracker
**Then** the corresponding markets are registered in MarketRegistry with appropriate GameLifecycle state (BUY_PLACED or FILLING based on fill status)
**And** per-game APScheduler triggers are created for their kickoff times (pre-kickoff consolidation and game-start recovery)

**Given** the entire reconciliation process
**When** timed from startup
**Then** it completes within 60 seconds (NFR3)

**Given** the CLOB or Data API returns an error during reconciliation
**When** `@with_retry` handles the failure
**Then** if retries succeed, reconciliation continues normally
**And** if retries are exhausted for a specific query, the error is logged at ERROR level and the bot starts with partial state (best effort), logging a CRITICAL warning that manual review may be needed

### Story 5.2: Market-Context Logging with LoggerAdapter

> **Cross-Epic Dependency Note:** This story builds on the logging infrastructure from Story 1.3 (handlers, format, secret filter). No changes to that foundation are required — this story adds an application-level `LoggerAdapter` pattern for market context binding.

As an operator,
I want every log message related to a specific market to include the team names and token ID,
So that I can quickly filter and trace activity for any game when reviewing logs.

**Acceptance Criteria:**

**Given** a `core/` module is processing a specific market
**When** it creates a LoggerAdapter bound to that market's context
**Then** all log messages from that adapter automatically include `[Home vs Away]` prefix and `token_id` in the message

**Given** a log message is emitted at any level (DEBUG through CRITICAL)
**When** it is written to file and console
**Then** the format is `%(asctime)s | %(levelname)-8s | %(name)s | [Home vs Away] message text (token=...)`
**And** the logger name reflects the originating module (e.g., `btts_bot.core.order_execution`)

**Given** market context is available (from MarketRegistry)
**When** log messages include event datetimes (e.g., kickoff time)
**Then** the datetime is formatted in a human-readable UTC format within the message body

**Given** a module operates outside of a specific market context (e.g., daily fetch summary, startup message)
**When** it logs
**Then** it uses the standard module logger without a market adapter
**And** the log format remains consistent (no empty brackets or missing fields)

### Story 5.3: Non-Fatal Error Handling and Credential Protection

As an operator,
I want the bot to survive any individual API failure without crashing and ensure my credentials never appear in any output,
So that the bot runs unattended for weeks and my private keys remain secure.

**Acceptance Criteria:**

**Given** any API call (CLOB, Gamma, Data API) fails with an unexpected error
**When** the `@with_retry` decorator catches the exception
**Then** the error is logged with full context (endpoint, token_id if applicable, error message)
**And** the bot continues processing the next market or operation
**And** no single API failure terminates the bot process (NFR2)

**Given** the Polymarket API returns an unexpected response format or payload
**When** the client wrapper attempts to parse it
**Then** a descriptive WARNING is logged including the unexpected structure
**And** the operation returns `None` to the caller
**And** the bot continues without crashing (NFR10)

**Given** any log message is about to be written (file or console)
**When** the secret filter inspects the message content
**Then** any string matching the private key, API key, API secret, or API passphrase patterns is replaced with `[REDACTED]`
**And** the redaction applies to all log levels including DEBUG and ERROR stack traces

**Given** an exception traceback includes credential values (e.g., from a failed auth call)
**When** the traceback is logged
**Then** the secret filter redacts credentials from the traceback text before output
**And** the operator never sees raw credential values in any log file or console output (NFR5)

**Given** the log file on disk
**When** its file permissions are inspected
**Then** they are set to `0o600` (owner-only read/write) (NFR7)

### Story 5.4: Long-Running Stability and State Pruning

As an operator,
I want the bot to run continuously for 14+ days without memory leaks, state corruption, or crashes,
So that I can deploy it and leave it running unattended across multiple daily market cycles.

**Acceptance Criteria:**

**Given** the bot has been running for multiple days with dozens of completed games
**When** a game transitions to a terminal state (DONE, EXPIRED, or SKIPPED)
**Then** after a configurable cooldown period (e.g., 24 hours past kickoff), the game's state is pruned from MarketRegistry, OrderTracker, and PositionTracker
**And** an INFO log is emitted: `[Home vs Away] Completed game pruned from state managers`
**And** memory used by the pruned game data is reclaimed

**Given** the state pruning mechanism runs periodically (e.g., daily alongside the market fetch)
**When** it scans all games in terminal states
**Then** only games past the cooldown period are pruned
**And** games still in active states (BUY_PLACED, FILLING, SELL_PLACED, PRE_KICKOFF, GAME_STARTED, RECOVERY_COMPLETE) are never touched
**And** the pruning operation is logged with a summary: `State pruning complete: N games removed, M active games retained`

**Given** the bot has been running for 14+ days
**When** daily market fetch, order placement, fill tracking, pre-kickoff consolidation, and game-start recovery all execute repeatedly
**Then** the bot remains stable without memory leaks, state corruption, or process crashes (FR24, NFR1)
**And** total memory usage remains bounded regardless of how many games have been processed over the bot's lifetime

**Given** the APScheduler is managing triggers for multiple concurrent games
**When** a game reaches a terminal state and its triggers have all fired
**Then** completed scheduler jobs are cleaned up to prevent scheduler resource leaks
