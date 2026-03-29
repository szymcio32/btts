---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation-skipped
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
inputDocuments:
  - BTTS_FUNCTIONAL_REQUIREMENTS.md
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 0
  projectDocs: 0
  functionalRequirements: 1
classification:
  projectType: cli_tool
  domain: fintech
  complexity: high
  projectContext: greenfield
workflowType: 'prd'
---

# Product Requirements Document - btts-bot

**Author:** Wolny
**Date:** 2026-03-23

## Executive Summary

BTTS Bot is a fully autonomous trading bot that captures spread profit on Polymarket's "Both Teams to Score — No" prediction markets across multiple soccer leagues. It exploits a systematic pricing inefficiency: BTTS-No tokens are consistently underpriced in early pre-game hours and converge upward toward fair value as kickoff approaches. The bot buys at liquidity-analysed prices (e.g., 0.48 at 6am), accumulates positions through partial fills, and exits at a configurable spread (e.g., 0.50 at 5pm) — repeating this across dozens of daily matches in 5+ leagues without human intervention.

The target user is an automated trader with a funded Polymarket proxy wallet and API credentials who wants a set-and-forget system. The bot handles the full order lifecycle — market discovery, orderbook analysis, buy placement, fill accumulation, sell placement, pre-kickoff consolidation, and game-start recovery — so the operator never needs to manually monitor markets or manage positions.

### What Makes This Special

The core edge is a three-case orderbook bid-depth analysis algorithm that determines optimal entry prices based on real-time liquidity conditions, combined with a multi-phase exit strategy that adapts as kickoff approaches. Unlike manual trading, the bot scales across all configured leagues simultaneously, capturing small consistent spreads (2+ cents per position) that compound across high match volume. The game-start recovery mechanism — detecting Polymarket's automatic order cancellation at kickoff and re-placing sell orders with retry logic — ensures positions are never left unmanaged, even in edge cases.

## Project Classification

- **Project Type:** CLI Tool / Backend Automation Bot — headless, config-driven, runs as a background process
- **Domain:** Fintech — prediction market trading, order lifecycle management, real-money positions
- **Complexity:** High — financial transactions, API reliability requirements, duplicate order prevention, multi-phase order lifecycle, kickoff-timing edge cases
- **Project Context:** Greenfield — new product built from scratch

## Success Criteria

### User Success

- The operator checks logs weekly and sees consistent fill activity across all configured leagues with no manual intervention required.
- Every filled buy position has a corresponding sell order placed — no positions are ever left without an exit order.
- The bot gracefully skips games with insufficient liquidity without requiring operator action or generating false alarms.
- The bot runs unattended for at least two weeks without needing a restart or manual correction.

### Business Success

- Consistent profitability across positions — the priority is reliability of the spread-capture strategy over maximizing per-trade returns.
- Approximately 40 games processed per week across 5 configured leagues at steady state.
- High fill rate on buy orders where liquidity analysis determines viable entry prices.
- Sell orders fill before or shortly after kickoff on the majority of positions.

### Technical Success

- Zero unmanaged positions after kickoff — this is the most critical failure mode to prevent. Every filled buy must have a sell order re-placed after Polymarket's automatic cancellation at game start, with retry logic until confirmed.
- No duplicate buy or sell orders placed for any market.
- Non-fatal API errors handled gracefully — individual failures must not crash the bot or leave state inconsistent.
- Structured logging captures all operational events for weekly review with sufficient detail to diagnose issues.

### Measurable Outcomes

- **Uptime:** Bot runs continuously for 14+ days without manual restart.
- **Position coverage:** 100% of filled buy positions have active sell orders at all times (pre-kickoff, at kickoff, and post-kickoff).
- **Duplicate prevention:** 0 duplicate buy or sell orders per market across all runs.
- **Error resilience:** 0 bot crashes due to individual API call failures.
- **Weekly throughput:** ~40 games analysed and traded per week across 5 leagues.

## Product Scope

### MVP - Minimum Viable Product

- YAML config-driven league and bet-parameter selection
- Daily automated market discovery from JSON file at configured UTC hour + on startup
- Three-case orderbook bid-depth analysis (Cases A/B/C) for buy price determination
- Limit buy order placement with configured share amount and expiration
- Incremental fill accumulation with automatic sell order placement (min 5 shares)
- Pre-kickoff sell consolidation (cancel unfilled sells, re-create at buy price)
- Game-start sell re-creation with 1-minute verification and retry logic
- Duplicate buy and sell order prevention
- Non-fatal API error handling
- Structured logging to file and console
- Polymarket CLOB client authentication via environment variables

### Growth Features (Post-MVP)

- Multi-strategy support (e.g., Over/Under markets in addition to BTTS)
- Profit/loss tracking and daily summary reports
- Configurable alerting (e.g., Telegram/Discord notifications on errors or daily P&L)
- Historical performance analytics
- Dynamic position sizing based on bankroll or confidence

### Vision (Future)

- Support for additional prediction market platforms beyond Polymarket
- Machine learning-enhanced liquidity analysis and entry timing
- Portfolio-level risk management across concurrent positions
- Web dashboard for monitoring (optional, operator preference)

## User Journeys

### Journey 1: First-Time Setup — "Getting the Bot Running"

**Persona:** Wolny, an automated trader with a funded Polymarket proxy wallet who wants to capture BTTS-No spreads across European soccer leagues without manual effort.

**Opening Scene:** Wolny has identified the BTTS-No pricing inefficiency on Polymarket and has been trading it manually, but can't keep up with 40+ games per week across 5 leagues. He decides to automate the strategy.

**Rising Action:**
1. Wolny clones the bot repository and reviews the example configuration.
2. He creates `config_btts.yaml`, configuring his 5 target leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1), setting order size to 30 shares, price_diff to 0.02, and liquidity thresholds based on his manual trading experience.
3. He sets environment variables for his Polymarket private key and proxy wallet address.
4. He starts the bot. It immediately fetches today's markets from the JSON file, logs discovered BTTS markets for each configured league, and begins placing buy orders.

**Climax:** Within hours, Wolny checks the logs and sees the bot has analysed orderbooks, placed buy orders at optimal prices across multiple games, and is already accumulating fills. He closes his laptop and walks away.

**Resolution:** A week later, Wolny reviews the logs — consistent fills across all 5 leagues, sell orders placed for every filled position, and the bot handled game-start cancellations and re-placed sells without intervention. The set-and-forget promise is real.

### Journey 2: Normal Daily Operation — "The Happy Path"

**Opening Scene:** The bot has been running for 3 days. It's 11pm UTC and the daily market fetch triggers.

**Rising Action:**
1. The bot fetches tomorrow's BTTS markets from the JSON file for all 5 configured leagues. It discovers 8 new games.
2. For each game, it checks if a buy order was already placed (none have — these are new markets). It fetches the orderbook for each BTTS-No token.
3. Liquidity analysis runs: 5 games fall into Case A (standard — order at L3 price), 2 into Case B (deep book — order at L2 price), 1 into Case C (thin liquidity — order at L3 - tick_offset).
4. Buy orders are placed for all 8 games with appropriate prices and configured expiration.
5. Over the next hours, fills trickle in. Each time accumulated fills reach 5 shares, a sell order is placed at buy_price + 0.02.

**Climax:** 10 minutes before kickoff on the first game, the bot cancels all unfilled sell orders and re-creates a single consolidated sell at the buy price to maximize fill probability. The sell fills just before kickoff.

**Resolution:** By end of day, 7 of 8 positions have fully exited with profit. One game had the buy order expire unfilled due to thin liquidity — the bot logged it and moved on. No intervention needed.

### Journey 3: Game-Start Recovery — "The Critical Edge Case"

**Opening Scene:** It's 3pm UTC. A Premier League match kicks off. Polymarket automatically cancels all open orders on the market.

**Rising Action:**
1. The bot detects that its live sell orders for this game have been cancelled (order status changes).
2. It identifies the filled buy position — 30 shares bought at 0.48 — that now has no active sell order.
3. The bot immediately places a new sell order at 0.48 (the buy price, breakeven) to preserve the position.
4. After 1 minute, the bot checks whether the sell order was placed successfully on Polymarket.

**Climax:** The first sell placement attempt failed due to a transient API error. The bot detects this in its 1-minute verification check and retries. The retry succeeds — the sell order is now live.

**Resolution:** The position is managed. The sell order fills during the match as the BTTS-No price holds. Wolny never knew there was an issue — the logs show the retry, but the bot handled it autonomously.

### Journey 4: Troubleshooting — "Something Looks Off"

**Opening Scene:** After 10 days of unattended operation, Wolny does his weekly log check and notices fewer fills than expected on La Liga games.

**Rising Action:**
1. Wolny opens the log file and filters by league. He sees entries with friendly datetime stamps, market identifiers (home team vs away team), and clear status messages.
2. He finds that for 3 La Liga games, the buy orders were placed but never filled — the log shows the buy price was set via Case C (low liquidity) and the orderbook was very thin.
3. He cross-references on Polymarket and confirms the orders expired unfilled — no position was opened, so no risk.
4. He considers adjusting the liquidity thresholds in config to be slightly more aggressive on La Liga markets.

**Climax:** Wolny edits `config_btts.yaml`, adjusts `low_liquidity_total` from 500 to 400 for a slightly wider net, and restarts the bot.

**Resolution:** The bot picks up the new config on restart, fetches markets immediately, and resumes operations with the updated parameters. No data loss, no state corruption.

### Journey Requirements Summary

| Journey | Key Capabilities Revealed |
|---|---|
| First-Time Setup | YAML config loading, env var authentication, immediate market fetch on startup, log output for verification |
| Normal Daily Operation | Scheduled market fetch, orderbook analysis (3 cases), buy/sell order lifecycle, fill accumulation, pre-kickoff consolidation, liquidity skip logic |
| Game-Start Recovery | Order cancellation detection, sell re-placement at buy price, 1-minute verification, retry logic, zero unmanaged positions |
| Troubleshooting | Structured logging with datetime + market identifier + issue description, log file persistence, config edit + restart workflow |

## Domain-Specific Requirements

### Financial Risk & Position Safety

- The bot operates with real money on Polymarket prediction markets. The primary risk mitigation is ensuring **zero unmanaged positions** — every filled buy must always have a corresponding sell order.
- No additional financial caps (daily spend limits, max concurrent positions) are required beyond the configured order size. The operator manages bankroll externally.
- Duplicate order prevention (both buy and sell) is a hard safety requirement, not a nice-to-have.

### Credential Security

- Polymarket private key and proxy wallet address are stored as environment variables. This is sufficient for a single-operator bot running on trusted infrastructure.
- Credentials must never be logged, written to state files, or exposed in error messages.

### State Management Strategy

- **Primary:** In-memory state during normal operation — tracks processed markets, placed orders, fill accumulation, and active sell orders.
- **Reconciliation on startup:** On every bot start (including restarts), query the Polymarket API for current open orders and positions to rebuild internal state. This ensures no positions are orphaned after a crash or restart.
- **No persistent state file required.** The Polymarket API is the source of truth; in-memory state is a performance optimization to avoid polling on every loop iteration.

### Platform Dependency Constraints

- The bot depends on Polymarket's CLOB API for orderbook data, order placement, order status, and position queries.
- **Websocket unreliability:** The Polymarket websocket channel may not deliver all events. The bot must not rely solely on websocket events for critical state transitions (e.g., fill detection, order cancellation). Periodic API polling or verification checks are required for safety-critical operations.
- No known API rate limits, but the bot should handle transient API failures gracefully (retries with backoff) since it operates continuously for 14+ days.

### Risk Mitigations

See the comprehensive risk mitigation tables in the Project Scoping & Phased Development section, covering technical, market, and resource risks.

## CLI Bot Specific Requirements

### Project-Type Overview

BTTS Bot is a long-running background process (daemon-style), not an interactive CLI tool. It is started once and runs continuously for weeks, processing markets autonomously. The operator interacts with the bot only at startup (providing config path) and during troubleshooting (reading log files). There are no interactive commands, shell completions, or real-time user prompts.

### Command Structure

- **Entry point:** Single command to start the bot, e.g., `python btts_bot.py` or `python btts_bot.py --config path/to/config.yaml`
- **CLI arguments:**
  - `--config` (optional): Path to YAML configuration file. Defaults to `config_btts.yaml` in the project root.
- **No subcommands, no interactive mode, no shell completion required.**
- The bot runs as a foreground process in the terminal (or can be backgrounded with standard OS tools like `nohup`, `screen`, or `systemd`).

### Configuration Schema

- **Primary config:** YAML file (`config_btts.yaml`) with sections for:
  - `leagues` — list of league names and abbreviations
  - `btts` — order sizing, spread, minimum order size, cancellation timing
  - `liquidity` — three-case bid-depth analysis thresholds
  - `timing` — daily market fetch hour (UTC)
  - `logging` — log file path
- **Credentials:** Environment variables for Polymarket private key and proxy wallet address.
- **Config is read once at startup.** Changes require a bot restart.

### Output Formats

- **Primary output:** Structured log file with timestamp, log level, logger name, and human-readable messages including market identifiers (home vs away team) and event datetimes.
- **Console output:** Same structured log output mirrored to stdout for real-time monitoring if desired.
- **Daily trade summary (Phase 2):** A log-based summary of the day's trading activity — markets discovered, buy orders placed, fills accumulated, sell orders placed, positions exited. Format: structured log entries at INFO level that can be filtered by date.

### Scripting & Automation Support

- The bot is designed to run unattended as a background process. It can be managed via standard process management:
  - `nohup` / `screen` / `tmux` for simple deployment
  - `systemd` service unit for production deployment with auto-restart
- **Graceful shutdown (Phase 2):** The bot should handle SIGTERM/SIGINT cleanly — cancel pending operations where safe and exit without corrupting state.
- **Exit codes:** 0 for clean shutdown, non-zero for fatal startup errors (e.g., missing config, invalid credentials).

### Implementation Considerations

- **Language:** Python (aligned with Polymarket's `py-clob-client` SDK)
- **Dependencies:** `py-clob-client` for Polymarket CLOB API interaction, `PyYAML` for config parsing, standard library for logging and scheduling.
- **No web framework, no database, no UI framework required.**
- **Single-process, single-threaded architecture** is sufficient given the throughput requirements (~40 games/week). Async I/O may be used for API calls but is not a hard requirement.

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-solving MVP — the minimum feature set that eliminates the need for manual BTTS-No trading across multiple leagues. The bot must reliably execute the full buy-sell lifecycle and handle the game-start edge case without leaving positions unmanaged.

**Resource Requirements:** Single Python developer with experience in the Polymarket CLOB API (`py-clob-client`). No frontend, database, or infrastructure engineering needed.

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
- Journey 1 (First-Time Setup) — full support
- Journey 2 (Normal Daily Operation) — full support
- Journey 3 (Game-Start Recovery) — full support
- Journey 4 (Troubleshooting) — partial support (log-based only, no daily summary)

**Must-Have Capabilities:**

| Capability | Rationale |
|---|---|
| YAML config loading with CLI path override | Operator must configure leagues and parameters |
| Polymarket CLOB client auth via env vars | Required for all API interactions |
| Daily market discovery from JSON file (on startup + scheduled) | Core market selection pipeline |
| BTTS-No token selection and duplicate market skip | Correct token targeting and idempotency |
| Three-case orderbook bid-depth analysis (A/B/C) | Core pricing strategy |
| Limit buy order placement with expiration | Entry execution |
| Incremental fill accumulation + sell order placement (min 5 shares) | Position exit pipeline |
| Sell price derivation (buy_price + price_diff, capped at 0.99) | Spread capture logic |
| Pre-kickoff sell consolidation at buy price | Last-chance exit optimization |
| Game-start sell re-creation with 1-min verification + retry | Critical safety mechanism — zero unmanaged positions |
| Startup reconciliation via Polymarket API | Crash recovery — rebuild state from API on restart |
| Duplicate buy and sell order prevention | Financial safety guard |
| Non-fatal API error handling | 14-day unattended uptime requirement |
| Structured logging to file and console (with datetime, market ID, issue) | Troubleshooting capability |

**Explicitly Excluded from MVP:**
- Daily trade summary report
- Graceful shutdown / SIGTERM handling
- Alerting (Telegram/Discord)
- Multi-strategy support
- Performance analytics

### Post-MVP Features

**Phase 2 (Growth):**
- Daily trade summary log output (consolidated end-of-day report)
- Graceful shutdown with SIGTERM/SIGINT handling
- Profit/loss tracking per position and per league
- Configurable alerting (Telegram/Discord notifications on errors or daily P&L)
- Historical performance analytics

**Phase 3 (Expansion):**
- Multi-strategy support (Over/Under markets)
- Dynamic position sizing based on bankroll or confidence
- Support for additional prediction market platforms
- Machine learning-enhanced liquidity analysis and entry timing
- Portfolio-level risk management across concurrent positions
- Optional web dashboard for monitoring

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Mitigation |
|---|---|
| Polymarket API changes or downtime | Non-fatal error handling with retries; bot survives transient outages |
| Websocket misses critical events | API polling for safety-critical operations (fills, order cancellations) — never rely solely on websocket |
| Bot crash mid-day loses position state | Startup reconciliation rebuilds all state from Polymarket API |
| Liquidity analysis produces bad entry prices | Three-case algorithm adapts to market conditions; Case C handles thin books conservatively |

**Market Risks:**

| Risk | Mitigation |
|---|---|
| BTTS-No pricing inefficiency disappears | Configurable spread parameter allows operator to adjust strategy |
| Polymarket changes market structure | Config-driven market selection allows rapid adaptation |
| Low liquidity across all leagues | Bot gracefully skips thin markets — no forced entries |

**Resource Risks:**

| Risk | Mitigation |
|---|---|
| Single developer — bus factor of 1 | Narrow, well-documented scope; config-driven design reduces code complexity |
| Fewer hours available than planned | MVP scope is tight — no nice-to-haves included; can be built incrementally |

## Functional Requirements

### Configuration & Initialization

- FR1: Operator can provide a YAML configuration file path via CLI argument, defaulting to `config_btts.yaml` in the project root
- FR2: System can load league definitions, bet parameters, liquidity thresholds, timing, and logging settings from the YAML configuration file at startup
- FR3: System can authenticate with the Polymarket CLOB API using private key and proxy wallet address from environment variables
- FR4: System can validate configuration and credentials at startup, exiting with a non-zero exit code and clear error message on failure

### Market Discovery & Selection

- FR5: System can fetch all BTTS markets for all configured leagues from a JSON data file once immediately on startup
- FR6: System can fetch all BTTS markets for all configured leagues from a JSON data file once daily at a configured UTC hour
- FR7: System can identify and select the "No" outcome token from each BTTS market
- FR8: System can skip markets where a buy order has already been placed in the current session or detected via API reconciliation

### Liquidity Analysis & Pricing

- FR9: System can analyse the top three bid levels of a BTTS-No token's orderbook to determine the optimal buy price using three-case logic (Case A: standard, Case B: deep book, Case C: thin liquidity)
- FR10: System can derive the sell price as buy price plus a configured spread offset, capped at 0.99
- FR11: System can skip markets where liquidity analysis determines conditions are unsuitable for entry

### Order Execution & Position Management

- FR12: System can place a limit buy order with configured share amount and expiration time on the Polymarket CLOB for each viable BTTS-No market
- FR13: System can track incremental fill accumulation on placed buy orders
- FR14: System can place a limit sell order when accumulated buy fills reach the minimum order size threshold (5 shares)
- FR15: System can prevent duplicate buy orders for any given market
- FR16: System can prevent duplicate sell orders where existing live sell orders already cover the position

### Pre-Kickoff & Game-Start Handling

- FR17: System can cancel all unfilled sell orders at a configurable time before kickoff and re-create a single consolidated sell order at the buy price
- FR18: System can cancel unfilled buy orders at a configurable time before kickoff
- FR19: System can detect when Polymarket automatically cancels all open orders at game start
- FR20: System can re-place sell orders for all filled buy positions at the buy price after game-start cancellation
- FR21: System can verify sell order placement 1 minute after game-start re-creation and retry until confirmed

### State Management & Recovery

- FR22: System can maintain in-memory state of all processed markets, placed orders, fill accumulations, and active sell orders during operation
- FR23: System can reconcile internal state with the Polymarket API on every startup by querying current open orders and positions
- FR24: System can run continuously as a background process for 14+ days without requiring manual intervention or restart

### Operational Observability

- FR25: System can log all operational events with timestamp, log level, logger name, and human-readable messages to both a log file and console simultaneously
- FR26: System can include market identifiers (home team vs. away team) and event datetimes in log messages for traceability
- FR27: System can handle individual API call failures without crashing, logging the error and continuing operation
- FR28: System can exclude credentials from all log output and error messages

## Non-Functional Requirements

### Reliability

- NFR1: The bot must run continuously for 14+ days without crashing or requiring manual restart under normal operating conditions.
- NFR2: No single API call failure may terminate the bot process — all API errors must be caught, logged, and retried or skipped gracefully.
- NFR3: After any bot restart (intentional or crash), the system must reach a fully operational state within 60 seconds by reconciling with the Polymarket API.
- NFR4: Game-start sell re-creation must complete (including retry cycles) within 5 minutes of kickoff to minimize unmanaged position exposure.

### Security

- NFR5: Private keys and wallet addresses must only be read from environment variables and must never appear in log files, error messages, console output, or any persisted data.
- NFR6: Configuration files must not contain any credentials or secrets.
- NFR7: Log files must be written with restrictive file permissions (owner-only read/write) to prevent credential-adjacent data exposure.

### Integration

- NFR8: All Polymarket CLOB API interactions must include retry logic with backoff for transient failures (network errors, 5xx responses).
- NFR9: The system must not rely on Polymarket websocket events as the sole source of truth for safety-critical state transitions (fill detection, order cancellation). API polling must serve as the authoritative verification method.
- NFR10: The system must handle Polymarket API response format changes or unexpected payloads gracefully — logging the anomaly without crashing.

### Performance

- NFR11: Orderbook analysis and buy order placement for a single market must complete within 10 seconds to avoid stale pricing data.
- NFR12: The daily market fetch and processing cycle for all configured leagues must complete within 5 minutes to ensure all buy orders are placed well before kickoff windows begin.
