# Implementation Readiness Assessment Report

**Date:** 2026-03-28
**Project:** btts-bot

---

## Document Inventory

**stepsCompleted:** [step-01-document-discovery, step-02-prd-analysis, step-03-epic-coverage-validation, step-04-ux-alignment, step-05-epic-quality-review, step-06-final-assessment]

### Documents Used for Assessment

| Document Type | File | Format |
|---|---|---|
| PRD | prd.md | Whole |
| Architecture | architecture.md | Whole |
| Epics & Stories | epics.md | Whole |
| UX Design | N/A | Not applicable (no UI) |

### Notes

- No duplicate documents found
- UX document not present -- confirmed not needed (application has no user interface)

---

## PRD Analysis

### Functional Requirements (28 total)

| ID | Category | Requirement |
|---|---|---|
| FR1 | Config & Init | Operator can provide a YAML configuration file path via CLI argument, defaulting to `config_btts.yaml` |
| FR2 | Config & Init | System can load league definitions, bet parameters, liquidity thresholds, timing, and logging settings from YAML at startup |
| FR3 | Config & Init | System can authenticate with the Polymarket CLOB API using private key and proxy wallet address from env vars |
| FR4 | Config & Init | System can validate configuration and credentials at startup, exiting with non-zero exit code on failure |
| FR5 | Market Discovery | System can fetch all BTTS markets for all configured leagues from a JSON data file once immediately on startup |
| FR6 | Market Discovery | System can fetch all BTTS markets from JSON data file once daily at a configured UTC hour |
| FR7 | Market Discovery | System can identify and select the "No" outcome token from each BTTS market |
| FR8 | Market Discovery | System can skip markets where a buy order has already been placed |
| FR9 | Liquidity & Pricing | System can analyse top three bid levels using three-case logic (Case A/B/C) for buy price |
| FR10 | Liquidity & Pricing | System can derive sell price as buy price + configured spread offset, capped at 0.99 |
| FR11 | Liquidity & Pricing | System can skip markets with unsuitable liquidity conditions |
| FR12 | Order Execution | System can place a limit buy order with configured share amount and expiration |
| FR13 | Order Execution | System can track incremental fill accumulation on placed buy orders |
| FR14 | Order Execution | System can place a limit sell order when accumulated fills reach min threshold (5 shares) |
| FR15 | Order Execution | System can prevent duplicate buy orders for any given market |
| FR16 | Order Execution | System can prevent duplicate sell orders where live sells already cover the position |
| FR17 | Pre-Kickoff | System can cancel unfilled sell orders before kickoff and re-create consolidated sell at buy price |
| FR18 | Pre-Kickoff | System can cancel unfilled buy orders at configurable time before kickoff |
| FR19 | Game-Start | System can detect when Polymarket cancels all open orders at game start |
| FR20 | Game-Start | System can re-place sell orders for filled buy positions at buy price after game-start cancellation |
| FR21 | Game-Start | System can verify sell order placement 1 minute after game-start and retry until confirmed |
| FR22 | State Mgmt | System can maintain in-memory state of all processed markets, orders, fills, and active sells |
| FR23 | State Mgmt | System can reconcile internal state with Polymarket API on every startup |
| FR24 | State Mgmt | System can run continuously as background process for 14+ days |
| FR25 | Observability | System can log all events with timestamp, level, logger name, and messages to file + console |
| FR26 | Observability | System can include market identifiers and event datetimes in log messages |
| FR27 | Observability | System can handle individual API failures without crashing |
| FR28 | Observability | System can exclude credentials from all log output and error messages |

### Non-Functional Requirements (12 total)

| ID | Category | Requirement |
|---|---|---|
| NFR1 | Reliability | Bot must run continuously for 14+ days without crashing |
| NFR2 | Reliability | No single API call failure may terminate the bot process |
| NFR3 | Reliability | After restart, system must reach operational state within 60 seconds |
| NFR4 | Reliability | Game-start sell re-creation must complete within 5 minutes of kickoff |
| NFR5 | Security | Private keys/wallet addresses only from env vars, never in logs/errors |
| NFR6 | Security | Configuration files must not contain credentials |
| NFR7 | Security | Log files must have restrictive file permissions (owner-only) |
| NFR8 | Integration | All API interactions must include retry logic with backoff |
| NFR9 | Integration | Must not rely on websocket events as sole source of truth for safety-critical state |
| NFR10 | Integration | Must handle API response format changes gracefully |
| NFR11 | Performance | Orderbook analysis + buy placement per market within 10 seconds |
| NFR12 | Performance | Daily market fetch + processing cycle within 5 minutes |

### Additional Requirements / Constraints

- Language: Python (aligned with py-clob-client SDK)
- Dependencies: py-clob-client, PyYAML, standard library
- Architecture: Single-process, single-threaded
- No database, no web framework, no UI
- Market data source: JSON data file
- Credentials: Environment variables only
- State: In-memory with API reconciliation on startup

### PRD Completeness Assessment

The PRD is thorough and well-structured. All 28 FRs are clearly numbered and specific. All 12 NFRs have measurable criteria. User journeys map to capabilities. Scope is tightly bounded with explicit MVP/Post-MVP separation.

---

## Epic Coverage Validation

### Coverage Matrix

| FR | PRD Requirement | Epic Coverage | Status |
|---|---|---|---|
| FR1 | YAML config path via CLI argument | Epic 1 (Story 1.2) | Covered |
| FR2 | Load config settings from YAML | Epic 1 (Story 1.2) | Covered |
| FR3 | CLOB API authentication via env vars | Epic 1 (Story 1.5) | Covered |
| FR4 | Config/credential validation at startup | Epic 1 (Stories 1.2, 1.5) | Covered |
| FR5 | Fetch BTTS markets on startup | Epic 2 (Story 2.1) | Covered |
| FR6 | Fetch BTTS markets daily at configured hour | Epic 2 (Story 2.2) | Covered |
| FR7 | Select No outcome token | Epic 2 (Story 2.3) | Covered |
| FR8 | Skip already-processed markets | Epic 2 (Story 2.3) | Covered |
| FR9 | Three-case orderbook bid-depth analysis | Epic 2 (Story 2.4) | Covered |
| FR10 | Sell price derivation (buy + spread, capped 0.99) | Epic 2 (Story 2.4) | Covered |
| FR11 | Skip unsuitable liquidity markets | Epic 2 (Story 2.4) | Covered |
| FR12 | Place limit buy orders | Epic 3 (Story 3.1) | Covered |
| FR13 | Track incremental fill accumulation | Epic 3 (Story 3.2) | Covered |
| FR14 | Place sell when fills reach threshold | Epic 3 (Story 3.3) | Covered |
| FR15 | Prevent duplicate buy orders | Epic 3 (Story 3.1) | Covered |
| FR16 | Prevent duplicate sell orders | Epic 3 (Story 3.3) | Covered |
| FR17 | Pre-kickoff sell consolidation | Epic 4 (Story 4.1) | Covered |
| FR18 | Pre-kickoff buy cancellation | Epic 4 (Story 4.1) | Covered |
| FR19 | Detect game-start order cancellation | Epic 4 (Story 4.2) | Covered |
| FR20 | Re-place sells after game-start | Epic 4 (Story 4.2) | Covered |
| FR21 | 1-min verify + retry on sell placement | Epic 4 (Story 4.3) | Covered |
| FR22 | In-memory state maintenance | Epic 3 (Story 3.4) | Covered |
| FR23 | Startup reconciliation from API | Epic 5 (Story 5.1) | Covered |
| FR24 | 14-day continuous operation | Epic 4 (Story 4.3) | Covered |
| FR25 | Structured logging (file + console) | Epic 1 (Story 1.3) + Epic 5 (Story 5.2) | Covered |
| FR26 | Market identifiers in log messages | Epic 5 (Story 5.2) | Covered |
| FR27 | Non-fatal API error handling | Epic 5 (Story 5.3) | Covered |
| FR28 | Credential exclusion from logs | Epic 1 (Story 1.3) + Epic 5 (Story 5.3) | Covered |

### Missing Requirements

None — all 28 FRs are covered.

### Coverage Statistics

- Total PRD FRs: 28
- FRs covered in epics: 28
- Coverage percentage: 100%

### Cross-Epic Observation

FR25 and FR28 span two epics: Epic 1 (Story 1.3 — logging infrastructure setup, secret filter, file permissions) and Epic 5 (Stories 5.2/5.3 — market-context logging, credential protection in error handling). This is a reasonable split — infrastructure in Epic 1, domain-specific logging in Epic 5 — but implementers should note the dependency.

---

## UX Alignment Assessment

### UX Document Status

Not found — confirmed not applicable.

### Alignment Issues

None. The PRD explicitly classifies this as a "CLI Tool / Backend Automation Bot — headless, config-driven, runs as a background process." The Architecture and Epics documents both confirm no UI. The operator confirmed UX is not needed.

### Warnings

None. The absence of UX documentation is correct for this project.

---

## Epic Quality Review

### Epic User Value Assessment

| Epic | Title | User Value | Notes |
|---|---|---|---|
| Epic 1 | Project Foundation & Configuration | Borderline | Framed from operator perspective, but Stories 1.1 (project init) and 1.4 (retry decorator) are infrastructure. Acceptable for greenfield. |
| Epic 2 | Market Discovery & Liquidity Analysis | Strong | Clear operator outcome — automatic market discovery and pricing. |
| Epic 3 | Order Execution & Position Management | Strong | Clear operator outcome — automated buy/sell lifecycle. |
| Epic 4 | Pre-Kickoff & Game-Start Recovery | Strong | Critical safety value — zero unmanaged positions. |
| Epic 5 | Startup Reconciliation & Operational Resilience | Strong | Clear operator outcome — crash recovery without data loss. |

### Epic Independence Assessment

All 5 epics are properly independent. Each epic builds on prior epics without requiring future epics to function. No circular dependencies detected.

### Story Acceptance Criteria Review

All 17 stories use proper Given/When/Then BDD format. Acceptance criteria are testable, specific, and include error scenarios. Coverage of edge cases is notably thorough (e.g., Story 4.1 handles FILLING state at pre-kickoff, Story 5.1 handles partial reconciliation failure).

### Quality Violations Found

#### Major Issues

**1. Story 3.4 (In-Memory State Management) is misplaced**

Story 3.4 formally defines MarketRegistry, OrderTracker, and PositionTracker interfaces, but these components are already used extensively in prior stories:
- Story 2.1 (MarketRegistry — register discovered markets)
- Story 2.3 (MarketRegistry — deduplication, OrderTracker — buy order check)
- Story 3.1 (OrderTracker — has_buy_order, record_buy)
- Story 3.2 (PositionTracker — accumulate)
- Story 3.3 (OrderTracker — has_sell_order, record_sell)

The state managers must exist before the stories that use them. Story 3.4 as written is documenting what already exists rather than creating something new.

**Recommendation:** Either (a) move state manager creation into Epic 1 as Story 1.6: Initialize State Managers, or (b) fold state manager creation into the stories that first use them (Story 2.1 creates MarketRegistry, Story 3.1 creates OrderTracker, Story 3.2 creates PositionTracker). Option (b) follows "create when first needed" best practice. Story 3.4 should be eliminated or restructured.

**Impact:** Medium — an experienced developer will naturally create state managers when first needed regardless of story ordering, but the current ordering could confuse a less experienced developer or AI agent following stories sequentially.

**2. FR24 (14-day continuous operation) awkwardly placed in Story 4.3**

FR24 is a cross-cutting reliability requirement depending on all components working together. It's assigned to Story 4.3 (sell verification), which appends a fourth AC about long-running stability and memory cleanup. This doesn't naturally belong in a sell verification story.

**Recommendation:** Either (a) create a dedicated Story 4.4 or 5.4 focused on long-running stability (memory cleanup of completed games, state manager pruning), or (b) document FR24/NFR1 as cross-cutting acceptance criteria validated during integration rather than assigning to a single story.

**Impact:** Low — the AC is clear about what's needed (cleanup of DONE state games), but its placement in a sell verification story is misleading.

#### Minor Concerns

**3. Cross-epic logging dependency (FR25/FR28)**

Logging setup (Epic 1, Story 1.3) and market-context logging (Epic 5, Stories 5.2/5.3) span two epics. Implementers should understand Story 5.2 enhances Epic 1's logging infrastructure, not creates it from scratch.

**4. APScheduler infrastructure introduced in Story 2.2 but heavily reused in Epic 4**

Story 2.2 introduces APScheduler for the daily fetch job, but the same scheduler is used for per-game date triggers in Epic 4. Scheduler initialization likely belongs in the main loop setup rather than in a single story. Implementation will naturally consolidate this.

**5. Story 1.4 (Retry Decorator) has indirect operator value**

The retry decorator is pure infrastructure. The user story framing works ("bot doesn't crash on transient errors") but is a stretch. Acceptable given the decorator is a critical cross-cutting pattern.

### Best Practices Compliance Summary

| Check | Epic 1 | Epic 2 | Epic 3 | Epic 4 | Epic 5 |
|---|---|---|---|---|---|
| Delivers user value | Borderline | Yes | Yes | Yes | Yes |
| Functions independently | Yes | Yes | Yes | Yes | Yes |
| Stories appropriately sized | Yes | Yes | Yes | Yes | Yes |
| No forward dependencies | Yes | Yes | Issue (3.4) | Yes | Yes |
| State created when needed | N/A | Issue | Issue | N/A | N/A |
| Clear acceptance criteria | Yes | Yes | Yes | Yes | Yes |
| FR traceability maintained | Yes | Yes | Yes | Yes | Yes |

---

## Summary and Recommendations

### Overall Readiness Status

**READY** — with minor structural improvements recommended.

The btts-bot project has strong planning artifacts. The PRD is thorough with 28 clearly specified FRs and 12 measurable NFRs. The Architecture document is comprehensive with full FR/NFR coverage, explicit module structure, and detailed implementation patterns. The Epics document achieves 100% FR coverage across 5 epics and 17 stories with well-structured Given/When/Then acceptance criteria.

### Critical Issues Requiring Immediate Action

None. There are no blockers to beginning implementation.

### Issues Summary

| # | Severity | Issue | Impact |
|---|---|---|---|
| 1 | Major | Story 3.4 (State Management) is misplaced — defines interfaces already used by prior stories | Medium — may confuse sequential implementers |
| 2 | Major | FR24 (14-day operation) awkwardly assigned to Story 4.3 (sell verification) | Low — AC is clear, but placement is misleading |
| 3 | Minor | Cross-epic logging dependency between Epic 1 and Epic 5 | Low — natural layering, just needs awareness |
| 4 | Minor | APScheduler infrastructure introduced in Story 2.2, reused in Epic 4 | Low — implementation will consolidate naturally |
| 5 | Minor | Story 1.4 (Retry Decorator) has indirect user value | Low — acceptable for infrastructure pattern |

### Recommended Next Steps

1. **Restructure Story 3.4:** Either move state manager creation to Epic 1 (Story 1.6) or eliminate Story 3.4 and fold state manager creation into the stories that first use them (Story 2.1 for MarketRegistry, Story 3.1 for OrderTracker, Story 3.2 for PositionTracker). This follows the "create when first needed" best practice.

2. **Relocate FR24/NFR1 long-running stability concern:** Create a dedicated story for memory cleanup of completed games (state manager pruning of DONE/EXPIRED/SKIPPED games) rather than appending it to Story 4.3. Alternatively, document it as a cross-cutting acceptance criterion.

3. **Proceed to implementation.** The issues identified are structural improvements to story ordering, not gaps in requirements or architecture. An experienced developer can implement the stories as-is by naturally creating state managers when first referenced. The acceptance criteria are clear and complete.

### Strengths

- **100% FR coverage** — all 28 functional requirements have traceable paths through epics to specific stories with testable ACs
- **Architecture-epic alignment** — the epics faithfully follow the Architecture's module structure, naming conventions, and implementation patterns
- **Edge case handling** — acceptance criteria cover error scenarios thoroughly (API failures, thin liquidity, concurrent kickoffs, partial reconciliation)
- **Safety-critical path well-defined** — the "zero unmanaged positions" invariant is reinforced through Stories 4.1, 4.2, 4.3, and 5.1 with multiple layers of detection, re-placement, and verification
- **Clean epic independence** — each epic builds on prior epics without backward dependencies

### Final Note

This assessment identified 5 issues across 2 severity categories (2 major, 3 minor). None are blockers. The major issues concern story ordering — specifically, Story 3.4 defines state manager interfaces that are already used by earlier stories, and FR24 is awkwardly placed. These are structural refinements that improve clarity but do not prevent correct implementation. The planning artifacts are well-prepared for Phase 4 implementation.
