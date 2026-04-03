# Sprint Change Proposal — GTD Expiration Anchored to Kickoff Time

**Date:** 2026-04-03
**Author:** Wolny
**Change Scope:** Minor
**Triggered By:** Story 3.1 (Buy Order Placement with Duplicate Prevention) — design review

---

## Section 1: Issue Summary

### Problem Statement

The GTD buy order expiration is currently calculated as `now + buy_expiration_hours` — a fixed duration offset from the moment the order is placed. This produces inconsistent expiration times relative to each game's kickoff:

- An order placed 18 hours before kickoff with `buy_expiration_hours=12` expires 6 hours before the game — potentially missing late fill opportunities.
- An order placed 2 hours before kickoff expires 10 hours after the game — well past when the order matters.
- Different placement times yield different effective trading windows for the same game.

The correct anchor point is the game's kickoff time, since the entire trading opportunity is tied to when the game starts. The expiration should be `kickoff_time - expiration_hour_offset`, so orders expire a consistent amount of time **before** kickoff regardless of when they were placed.

### Discovery Context

Identified during design review after Story 3.1 implementation was completed. The `MarketEntry.kickoff_time` is already stored for every discovered market and is the natural anchor for all game-relative timing.

---

## Section 2: Impact Analysis

### Epic Impact

| Epic | Status | Impact |
|------|--------|--------|
| Epic 1: Project Foundation & Configuration | done | Config field rename: `buy_expiration_hours` -> `expiration_hour_offset` |
| Epic 2: Market Discovery & Liquidity Analysis | done | None |
| Epic 3: Order Execution & Position Management | in-progress | Expiration calculation change in `order_execution.py` (Story 3.1 code) |
| Epic 4: Pre-Kickoff & Game-Start Recovery | backlog | None — already uses kickoff-anchored timing |
| Epic 5: Startup Reconciliation & Operational Resilience | backlog | None |

**No epics added, removed, or resequenced.**

### Story Impact

- **Story 3.1 (done):** Code change to expiration calculation + config field rename. Tests updated.
- **Stories 3.2, 3.3 (backlog):** No impact — deal with fill tracking and sell placement, not buy expiration.
- **All Epic 4 & 5 stories (backlog):** No impact.

### Artifact Conflicts

| Artifact | Conflict | Resolution |
|----------|----------|------------|
| `architecture.md` | Config YAML structure shows `buy_expiration_hours: 12`; Gap Analysis references `now + buy_expiration_hours` | Update both to `expiration_hour_offset: 1` and `kickoff_time - expiration_hour_offset` |
| `epics.md` | Story 3.1 AC #2 references `now + btts.buy_expiration_hours` | Update to `kickoff_time - btts.expiration_hour_offset` |
| `prd.md` | FR12 says "configured share amount and expiration time" | No change needed — wording is generic |
| Story 3.1 spec | Dev Notes reference the old calculation | No retroactive change — tracked in this proposal |

### Technical Impact

| Component | File | Change |
|-----------|------|--------|
| Config model | `btts_bot/config.py` | Rename field `buy_expiration_hours` -> `expiration_hour_offset`, default 12 -> 1 |
| Order execution | `btts_bot/core/order_execution.py` | Change expiration calc from `now + hours` to `kickoff_ts - offset * 3600` |
| Example config | `config_btts.example.yaml` | Rename field, update value |
| Tests | `tests/test_order_execution.py`, `tests/test_config.py`, `tests/test_liquidity.py`, `tests/test_main.py` | Update field references and expiration assertions |

---

## Section 3: Recommended Approach

**Selected Path:** Direct Adjustment — modify code, config, and docs within the existing plan.

**Rationale:**
- The change is surgically small — one config rename, one line of calculation logic, doc text updates, and test updates.
- No new components, no architectural restructuring, no epic changes.
- The `MarketEntry.kickoff_time` is already available at the point where expiration is calculated.
- Risk is minimal — the only behavioral change is that orders expire at a consistent time before kickoff instead of a variable time after placement.

**Effort Estimate:** Low (< 1 hour of implementation)
**Risk Assessment:** Low — isolated change with clear test coverage
**Timeline Impact:** None

---

## Section 4: Detailed Change Proposals

### 4.1 Config Model

**File:** `btts_bot/config.py`

OLD:
```python
buy_expiration_hours: int = Field(default=12, gt=0)
```

NEW:
```python
expiration_hour_offset: int = Field(default=1, gt=0)
```

### 4.2 Order Execution — Expiration Calculation

**File:** `btts_bot/core/order_execution.py`

OLD:
```python
# Calculate GTD expiration
expiration_ts = int(time.time()) + self._btts.buy_expiration_hours * 3600
```

NEW:
```python
# Calculate GTD expiration: order expires before kickoff
kickoff_ts = int(entry.kickoff_time.timestamp())
expiration_ts = kickoff_ts - self._btts.expiration_hour_offset * 3600
```

### 4.3 Example YAML Config

**File:** `config_btts.example.yaml`

OLD:
```yaml
buy_expiration_hours: 12
```

NEW:
```yaml
expiration_hour_offset: 1
```

### 4.4 Architecture Doc — Config Structure

**File:** `_bmad-output/planning-artifacts/architecture.md` (config YAML block)

OLD:
```yaml
buy_expiration_hours: 12
```

NEW:
```yaml
expiration_hour_offset: 1
```

### 4.5 Architecture Doc — Gap Analysis

**File:** `_bmad-output/planning-artifacts/architecture.md` (Gap Analysis section)

OLD:
> Buy order expiration strategy clarified — Buy orders use the Polymarket GTD (Good Til Date) order type with a Unix timestamp calculated as `now + buy_expiration_hours`. Polymarket handles cancellation server-side — no APScheduler job needed for buy expiration.

NEW:
> Buy order expiration strategy clarified — Buy orders use the Polymarket GTD (Good Til Date) order type with a Unix timestamp calculated as `kickoff_time - expiration_hour_offset`. The expiration is anchored to each market's kickoff time so orders expire before the game starts. Polymarket handles cancellation server-side — no APScheduler job needed for buy expiration.

### 4.6 Epics Doc — Story 3.1 AC

**File:** `_bmad-output/planning-artifacts/epics.md` (Story 3.1 AC #2)

OLD:
```
And the order uses GTD (Good Til Date) type with expiration timestamp calculated as `now + btts.buy_expiration_hours`
```

NEW:
```
And the order uses GTD (Good Til Date) type with expiration timestamp calculated as `kickoff_time - btts.expiration_hour_offset`
```

### 4.7 Tests

All test files referencing `buy_expiration_hours` must be updated to `expiration_hour_offset` and expiration assertions changed from `now + hours * 3600` to `kickoff_ts - offset * 3600`.

---

## Section 5: Implementation Handoff

**Change Scope Classification:** Minor — direct implementation by dev team.

**Handoff:** Development team for direct implementation.

**Implementation Checklist:**
1. Rename config field in `btts_bot/config.py`
2. Update expiration calculation in `btts_bot/core/order_execution.py`
3. Update `config_btts.example.yaml`
4. Update all test files for field rename and new assertion logic
5. Run full test suite — ensure all pass
6. Run `ruff check` and `ruff format` — zero issues
7. Update `architecture.md` (2 locations)
8. Update `epics.md` (1 location)

**Success Criteria:**
- All 213+ tests pass with updated expiration logic
- `ruff check` and `ruff format` pass with zero issues
- Expiration timestamp for any order = `kickoff_time - expiration_hour_offset * 3600` (verifiable in test assertions)
- No references to `buy_expiration_hours` remain in codebase or docs
