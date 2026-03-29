# Story 1.1: Initialize Project with uv and Package Structure

Status: review

## Story

As an operator,
I want the bot project initialized with proper Python packaging and dependencies,
So that I have a working development environment to build upon.

## Acceptance Criteria

1. **Given** a fresh project directory  
   **When** `uv init btts-bot --python 3.14` is run and dependencies are added  
   **Then** `pyproject.toml` exists with all runtime dependencies (`py-clob-client`, `pyyaml`, `requests`, `pydantic`, `pydantic-settings`, `apscheduler`) and dev dependencies (`ruff`)

2. **Given** the project is initialized  
   **When** the package structure is created  
   **Then** the `btts_bot/` package exists with `__init__.py`, `__main__.py`, `main.py`, and sub-packages `clients/`, `state/`, `core/` each with their own `__init__.py`

3. **Given** the package structure is in place  
   **When** `uv run python -m btts_bot` is executed  
   **Then** it runs without import errors (prints a startup message and exits cleanly)

4. **Given** the project is initialized  
   **When** the config example is created  
   **Then** `config_btts.example.yaml` exists with the full canonical config structure (leagues, btts, liquidity, timing, logging sections)

5. **Given** the project is initialized  
   **When** the Python version file is inspected  
   **Then** `.python-version` is set to `3.14` (or `3.13` if py-clob-client fails to install on 3.14)

## Tasks / Subtasks

- [x] Task 1: Run uv project initialization (AC: #1, #5)
  - [x] Run `uv init btts-bot --python 3.14` in the working directory (NOT inside a new subfolder — init into the existing project root)
  - [x] If py-clob-client fails to resolve on 3.14, retry with `--python 3.13`
  - [x] Run `uv add py-clob-client pyyaml requests pydantic pydantic-settings apscheduler`
  - [x] Run `uv add --dev ruff`
  - [x] Verify `pyproject.toml` and `uv.lock` were created
  - [x] Verify `.python-version` contains `3.14` (or `3.13`)

- [x] Task 2: Create btts_bot package with all required modules (AC: #2)
  - [x] Create `btts_bot/__init__.py` (empty package marker)
  - [x] Create `btts_bot/__main__.py` — imports and calls `main()` from `main.py`
  - [x] Create `btts_bot/main.py` — entry point stub (prints startup message, exits)
  - [x] Create `btts_bot/config.py` — empty stub with a TODO comment for Pydantic models (Story 1.2)
  - [x] Create `btts_bot/constants.py` — empty stub with a TODO comment (API URLs, enums added in later stories)
  - [x] Create `btts_bot/retry.py` — empty stub with a TODO comment (decorator added in Story 1.4)
  - [x] Create `btts_bot/logging_setup.py` — empty stub with a TODO comment (logging configured in Story 1.3)
  - [x] Create `btts_bot/clients/__init__.py` (empty)
  - [x] Create `btts_bot/clients/clob.py` — empty stub
  - [x] Create `btts_bot/clients/gamma.py` — empty stub
  - [x] Create `btts_bot/clients/data_api.py` — empty stub
  - [x] Create `btts_bot/state/__init__.py` (empty)
  - [x] Create `btts_bot/state/market_registry.py` — empty stub
  - [x] Create `btts_bot/state/order_tracker.py` — empty stub
  - [x] Create `btts_bot/state/position_tracker.py` — empty stub
  - [x] Create `btts_bot/core/__init__.py` (empty)
  - [x] Create `btts_bot/core/game_lifecycle.py` — empty stub
  - [x] Create `btts_bot/core/market_discovery.py` — empty stub
  - [x] Create `btts_bot/core/liquidity.py` — empty stub
  - [x] Create `btts_bot/core/order_execution.py` — empty stub
  - [x] Create `btts_bot/core/reconciliation.py` — empty stub
  - [x] Create `btts_bot/core/scheduling.py` — empty stub

- [x] Task 3: Implement __main__.py entry point (AC: #3)
  - [x] `__main__.py` must contain: `from btts_bot.main import main` and `if __name__ == "__main__": main()`
  - [x] `main.py` must contain a `main()` function that prints `"btts-bot starting..."` and returns (no actual logic yet)
  - [x] Run `uv run python -m btts_bot` and confirm it prints the startup message and exits 0

- [x] Task 4: Create config_btts.example.yaml (AC: #4)
  - [x] Create `config_btts.example.yaml` in the project root (next to `pyproject.toml`)
  - [x] File must contain all sections with example values per the canonical structure below

- [x] Task 5: Configure ruff in pyproject.toml
  - [x] Add `[tool.ruff]` section to `pyproject.toml` with `line-length = 100` and `target-version = "py314"` (or `py313` if fallback)
  - [x] Run `uv run ruff check btts_bot/` — should pass with no errors
  - [x] Run `uv run ruff format btts_bot/` — should complete cleanly

## Dev Notes

### Critical: uv init in existing directory

The project root already contains files (`_bmad-output/`, `docs/`, etc.). Run `uv init` **in the existing directory**, not by creating a new subdirectory:

```bash
# CORRECT — initialize in the current directory
uv init --python 3.14
# This generates pyproject.toml, .python-version, .gitignore, and hello.py in CWD

# THEN rename hello.py → we will replace it with our package structure
# uv init creates a hello.py stub — delete it, we create btts_bot/ package instead
```

Do NOT run `uv init btts-bot --python 3.14` as that creates a `btts-bot/` subdirectory. The project root IS `btts-bot`.

### py-clob-client Python version fallback

If `uv add py-clob-client` fails on Python 3.14 (compilation errors in native extensions), change `.python-version` to `3.13` and re-run. The architecture explicitly documents this fallback. Update `pyproject.toml` `requires-python` accordingly.

### Package entry point wiring

`__main__.py` is what makes `python -m btts_bot` work. It must be at `btts_bot/__main__.py` (not the project root). The content is minimal:

```python
from btts_bot.main import main

if __name__ == "__main__":
    main()
```

`main.py` at this stage just needs a `main()` function — no real logic:

```python
def main() -> None:
    print("btts-bot starting...")
```

### Stub files

All stub files (config.py, retry.py, logging_setup.py, all client/state/core modules) should be minimal but valid Python. Either empty with a module docstring, or with a single `# TODO: implemented in Story X.X` comment. Do NOT implement any real logic in this story — subsequent stories own those modules.

Example stub:
```python
"""
Pydantic configuration models for btts-bot.
Implemented in Story 1.2.
"""
```

### Canonical config_btts.example.yaml

Create exactly this structure (used by Story 1.2 for Pydantic model validation):

```yaml
leagues:
  - name: "Premier League"
    abbreviation: "EPL"
  - name: "La Liga"
    abbreviation: "LIGA"
  - name: "Bundesliga"
    abbreviation: "BL"
  - name: "Serie A"
    abbreviation: "SA"
  - name: "Ligue 1"
    abbreviation: "L1"

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

This exact structure is the contract for Story 1.2's Pydantic models (`BotConfig`, `LeagueConfig`, `BttsConfig`, `LiquidityConfig`, `TimingConfig`, `LoggingConfig`).

### Project Structure Notes

The complete final project tree (all files to create in this story):

```
btts-bot/                             ← project root (existing directory)
├── .python-version                   # Created by uv init: "3.14" or "3.13"
├── .gitignore                        # Created by uv init
├── pyproject.toml                    # Created by uv init, augmented with uv add
├── uv.lock                           # Created by uv add (commit this)
├── config_btts.example.yaml          # Created manually in Task 4
└── btts_bot/
    ├── __init__.py
    ├── __main__.py                   # entry: from btts_bot.main import main
    ├── main.py                       # main(): prints startup message
    ├── config.py                     # stub (Story 1.2)
    ├── constants.py                  # stub (later stories)
    ├── retry.py                      # stub (Story 1.4)
    ├── logging_setup.py              # stub (Story 1.3)
    ├── clients/
    │   ├── __init__.py
    │   ├── clob.py                   # stub (Story 1.5)
    │   ├── gamma.py                  # stub (Story 2.1)
    │   └── data_api.py               # stub (Story 5.1)
    ├── state/
    │   ├── __init__.py
    │   ├── market_registry.py        # stub (Story 1.6)
    │   ├── order_tracker.py          # stub (Story 3.1)
    │   └── position_tracker.py       # stub (Story 3.2)
    └── core/
        ├── __init__.py
        ├── game_lifecycle.py         # stub (Story 1.6)
        ├── market_discovery.py       # stub (Story 2.1)
        ├── liquidity.py              # stub (Story 2.4)
        ├── order_execution.py        # stub (Story 3.1)
        ├── reconciliation.py         # stub (Story 5.1)
        └── scheduling.py             # stub (Story 2.2)
```

Note: `uv init` generates a `hello.py` at the root — delete it. The `main.py` generated by `uv init` may conflict; replace it or use it as the base for `btts_bot/main.py`.

### Alignment with unified project structure

- Flat application layout (NOT `src/` layout) — this is by architectural decision, do not introduce a `src/` directory
- One class per file for major components (enforced from Story 1.2 onward)
- Sub-packages max one level deep: `btts_bot/clients/`, `btts_bot/state/`, `btts_bot/core/` — no further nesting
- Module naming: `snake_case.py` — never `camelCase.py`

### Downstream story contracts established by this story

This story establishes the skeleton that ALL future stories depend on. Do not skip any file:

- Story 1.2 (`config.py`): Will implement `BotConfig`, `LeagueConfig`, `BttsConfig`, `LiquidityConfig`, `TimingConfig`, `LoggingConfig` Pydantic models — the stub file must exist
- Story 1.3 (`logging_setup.py`): Will implement `setup_logging(config: LoggingConfig)` — stub must exist
- Story 1.4 (`retry.py`): Will implement `@with_retry` decorator — stub must exist
- Story 1.5 (`clients/clob.py`): Will implement `ClobClientWrapper` — stub must exist
- Story 1.6 (`state/market_registry.py`, `core/game_lifecycle.py`): Will implement `MarketRegistry` and `GameLifecycle` — stubs must exist

### References

- Architecture decision: Starter template selection — [Source: architecture.md#Starter Template Evaluation]
- Architecture decision: uv init command — [Source: architecture.md#First Implementation Priority]
- Architecture decision: Project directory structure — [Source: architecture.md#Complete Project Directory Structure]
- Architecture decision: Flat layout (not src/) — [Source: architecture.md#Selected Starter: uv init (application mode)]
- Epics: Story 1.1 acceptance criteria — [Source: epics.md#Story 1.1: Initialize Project with uv and Package Structure]
- Config canonical structure — [Source: architecture.md#Config YAML Canonical Structure]
- Runtime dependencies list — [Source: epics.md#Additional Requirements]
- `python -m btts_bot` invocation — [Source: architecture.md#Running the bot]
- Ruff configuration — [Source: architecture.md#Linting & Formatting]

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

- py-clob-client resolved successfully on Python 3.14 (no 3.13 fallback needed)
- uv init created root-level `main.py` stub — deleted and replaced by `btts_bot/` package
- All 22 package files created; ruff check and format passed cleanly on first run

### Completion Notes List

- Initialized uv project (Python 3.14) with all runtime deps: py-clob-client, pyyaml, requests, pydantic, pydantic-settings, apscheduler
- Added ruff as dev dependency; configured [tool.ruff] line-length=100, target-version=py314
- Created full btts_bot/ package structure: __init__.py, __main__.py, main.py, 4 top-level stubs, clients/ (3 files), state/ (3 files), core/ (6 files) — all with docstrings and TODO comments pointing to owning stories
- `uv run python -m btts_bot` prints "btts-bot starting..." and exits 0
- Created config_btts.example.yaml with canonical structure (leagues, btts, liquidity, timing, logging sections)
- All 5 acceptance criteria satisfied; ruff lint and format clean

### File List

- pyproject.toml (modified — added deps, [tool.ruff])
- uv.lock (generated)
- .python-version (generated — 3.14)
- .gitignore (generated)
- config_btts.example.yaml (created)
- btts_bot/__init__.py
- btts_bot/__main__.py
- btts_bot/main.py
- btts_bot/config.py
- btts_bot/constants.py
- btts_bot/retry.py
- btts_bot/logging_setup.py
- btts_bot/clients/__init__.py
- btts_bot/clients/clob.py
- btts_bot/clients/gamma.py
- btts_bot/clients/data_api.py
- btts_bot/state/__init__.py
- btts_bot/state/market_registry.py
- btts_bot/state/order_tracker.py
- btts_bot/state/position_tracker.py
- btts_bot/core/__init__.py
- btts_bot/core/game_lifecycle.py
- btts_bot/core/market_discovery.py
- btts_bot/core/liquidity.py
- btts_bot/core/order_execution.py
- btts_bot/core/reconciliation.py
- btts_bot/core/scheduling.py

## Change Log

- 2026-03-28: Story 1.1 implemented — uv project initialized, btts_bot package scaffold created, entry point verified, config example created, ruff configured
