# Story 1.2: Configuration Loading and Validation with Pydantic

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to load and validate my YAML configuration file at startup,
So that I get clear error messages if my config is malformed or missing required fields.

## Acceptance Criteria

1. **Given** a valid `config_btts.yaml` with leagues, btts, liquidity, timing, and logging sections
   **When** the bot starts with `--config config_btts.yaml` or no argument (uses default path)
   **Then** all configuration values are loaded into typed Pydantic models (`BotConfig`, `LeagueConfig`, `BttsConfig`, `LiquidityConfig`, `TimingConfig`, `LoggingConfig`)
   **And** the `--config` CLI argument overrides the default config path

2. **Given** a YAML file with missing required fields or invalid types
   **When** the bot starts
   **Then** it exits with a non-zero exit code and a clear error message identifying which field is invalid
   **And** no partial startup occurs

3. **Given** no config file exists at the specified path
   **When** the bot starts
   **Then** it exits with a non-zero exit code and a message indicating the file was not found

## Tasks / Subtasks

- [x] Task 1: Implement Pydantic config models in `btts_bot/config.py` (AC: #1)
  - [x] Create `LeagueConfig(BaseModel)` with fields: `name: str`, `abbreviation: str`
  - [x] Create `BttsConfig(BaseModel)` with fields: `order_size: int`, `price_diff: float`, `min_order_size: int = 5`, `buy_expiration_hours: int = 12`
  - [x] Create `LiquidityConfig(BaseModel)` with fields: `standard_depth: int`, `deep_book_threshold: int`, `low_liquidity_total: int`, `tick_offset: float`
  - [x] Create `TimingConfig(BaseModel)` with fields: `daily_fetch_hour_utc: int`, `fill_poll_interval_seconds: int = 30`, `pre_kickoff_minutes: int = 10`
  - [x] Create `LoggingConfig(BaseModel)` with fields: `level: str = "INFO"`, `file_path: str = "btts_bot.log"`, `max_bytes: int = 10485760`, `backup_count: int = 5`
  - [x] Create `BotConfig(BaseModel)` as the top-level model with fields: `leagues: list[LeagueConfig]`, `btts: BttsConfig`, `liquidity: LiquidityConfig`, `timing: TimingConfig`, `logging: LoggingConfig`
  - [x] Add field validators where appropriate (e.g., `daily_fetch_hour_utc` must be 0-23, `order_size` must be positive, `price_diff` must be positive and < 1.0, `level` must be a valid Python log level)

- [x] Task 2: Implement YAML loading function in `btts_bot/config.py` (AC: #1, #2, #3)
  - [x] Create `load_config(config_path: Path) -> BotConfig` function
  - [x] Read and parse YAML file using `pyyaml` (`yaml.safe_load`)
  - [x] Pass parsed dict to `BotConfig(**data)` for Pydantic validation
  - [x] If file not found: raise `SystemExit(1)` with clear message `"Config file not found: {path}"`
  - [x] If YAML parse error: raise `SystemExit(1)` with clear message including the YAML error
  - [x] If Pydantic validation error: raise `SystemExit(1)` with Pydantic's formatted error output (field name + error description)

- [x] Task 3: Implement CLI argument parsing in `btts_bot/main.py` (AC: #1)
  - [x] Use `argparse.ArgumentParser` to define `--config` argument with default `"config_btts.yaml"`
  - [x] Parse args in `main()` before any other startup logic
  - [x] Pass the resolved config path to `load_config()`
  - [x] Print a startup message confirming the loaded config path

- [x] Task 4: Wire config loading into main entry point (AC: #1, #2, #3)
  - [x] Update `btts_bot/main.py` `main()` to: parse CLI args -> load config -> print confirmation -> exit (no further logic in this story)
  - [x] Ensure `sys.exit(1)` is called on any config error (file not found, parse error, validation error)
  - [x] Ensure no partial startup occurs — config loading must be the FIRST operation after arg parsing
  - [x] Ensure the `main()` function signature remains `def main() -> None`

- [x] Task 5: Verify with manual testing
  - [x] Copy `config_btts.example.yaml` to `config_btts.yaml` and run `uv run python -m btts_bot` — should load successfully
  - [x] Run `uv run python -m btts_bot --config config_btts.example.yaml` — should load successfully
  - [x] Run `uv run python -m btts_bot --config nonexistent.yaml` — should exit with error message
  - [x] Modify config to have an invalid field type and run — should exit with clear Pydantic validation error
  - [x] Run `uv run ruff check btts_bot/` and `uv run ruff format btts_bot/` — should pass cleanly

## Dev Notes

### Critical: Do NOT use `pydantic-settings` BaseSettings for YAML config

The architecture specifies `pydantic-settings` for **environment variable reading** (credentials in Story 1.5), NOT for YAML config loading. For this story, use standard `pydantic.BaseModel` subclasses for all config models. The config is loaded from a YAML file via `pyyaml`, not from environment variables.

`pydantic-settings` `BaseSettings` is reserved for Story 1.5 where `ClobClientWrapper` needs to read `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` from environment variables. Do NOT mix these concerns.

### Pydantic v2 API (version 2.12.5 installed)

Use Pydantic v2 syntax exclusively:
- Import from `pydantic`, not `pydantic.v1`
- Use `model_validator`, `field_validator` decorators (not `@validator`)
- Use `model_dump()` (not `.dict()`)
- Use `model_json_schema()` (not `.schema()`)
- Use `ConfigDict` for model configuration (not inner `class Config`)
- Type annotations use Python 3.14 syntax: `list[LeagueConfig]` not `List[LeagueConfig]`

### Config model field types and constraints

Use Pydantic's `Field()` for validation constraints where appropriate:

```python
from pydantic import BaseModel, Field, field_validator

class BttsConfig(BaseModel):
    order_size: int = Field(gt=0, description="Number of shares per buy order")
    price_diff: float = Field(gt=0, lt=1.0, description="Spread offset for sell price")
    min_order_size: int = Field(default=5, gt=0, description="Minimum shares to trigger sell")
    buy_expiration_hours: int = Field(default=12, gt=0, description="Buy order GTD expiration in hours")

class TimingConfig(BaseModel):
    daily_fetch_hour_utc: int = Field(ge=0, le=23, description="UTC hour for daily market fetch")
    fill_poll_interval_seconds: int = Field(default=30, gt=0)
    pre_kickoff_minutes: int = Field(default=10, gt=0)

class LoggingConfig(BaseModel):
    level: str = Field(default="INFO")
    file_path: str = Field(default="btts_bot.log")
    max_bytes: int = Field(default=10_485_760, gt=0)
    backup_count: int = Field(default=5, ge=0)

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"Invalid log level '{v}'. Must be one of: {', '.join(sorted(valid))}")
        return v.upper()
```

### YAML loading pattern

```python
from pathlib import Path
import sys
import yaml
from pydantic import ValidationError

def load_config(config_path: Path) -> BotConfig:
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)
    
    if data is None:
        print(f"Error: Config file is empty: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        return BotConfig(**data)
    except ValidationError as e:
        print(f"Error: Invalid configuration in {config_path}:\n{e}", file=sys.stderr)
        sys.exit(1)
```

### CLI argument parsing pattern

```python
import argparse
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="BTTS Bot - Polymarket trading bot")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config_btts.yaml"),
        help="Path to YAML configuration file (default: config_btts.yaml)",
    )
    args = parser.parse_args()
    
    config = load_config(args.config)
    print(f"btts-bot starting... config loaded from {args.config}")
```

### LeagueConfig: required fields, no defaults

Both `name` and `abbreviation` are required with no defaults — the operator must define their leagues explicitly. At least one league must be provided:

```python
class BotConfig(BaseModel):
    leagues: list[LeagueConfig] = Field(min_length=1)
    btts: BttsConfig
    liquidity: LiquidityConfig
    timing: TimingConfig
    logging: LoggingConfig
```

### Error message quality

Pydantic v2's `ValidationError` already produces excellent error messages. Print them directly — do NOT catch and reformat. Example output for a missing field:

```
Error: Invalid configuration in config_btts.yaml:
2 validation errors for BotConfig
btts.order_size
  Field required [type=missing, input_value={'price_diff': 0.02}, input_type=dict]
leagues
  List should have at least 1 item after validation, not 0 [type=too_short, ...]
```

### Files to modify

- `btts_bot/config.py` — **primary implementation**: all Pydantic models + `load_config()` function
- `btts_bot/main.py` — add argparse CLI parsing + call `load_config()` + updated startup message

### Files NOT to touch

- `btts_bot/__main__.py` — already correct from Story 1.1
- `config_btts.example.yaml` — already correct from Story 1.1
- All stub files in `clients/`, `state/`, `core/` — not relevant to this story
- `pyproject.toml` — no new dependencies needed (pydantic, pyyaml already installed)

### Project Structure Notes

- `config.py` is at `btts_bot/config.py` (top-level of the package, not in any sub-package)
- This follows the architecture decision: config is a top-level concern, not in `core/` or `clients/`
- The config is immutable after startup — loaded once into frozen-like Pydantic models. While we don't enforce `model_config = ConfigDict(frozen=True)` (not required by architecture), the config object is never mutated after construction.
- `main.py` is the composition root — it calls `load_config()` and will pass the config to other modules in later stories

### Downstream story dependencies

- Story 1.3 (logging): Will call `setup_logging(config.logging)` — depends on `LoggingConfig` existing
- Story 1.4 (retry): No direct config dependency, but retry params (base, max, retries) could be made configurable in the future
- Story 1.5 (CLOB auth): Will use `pydantic-settings` `BaseSettings` for env vars — completely separate from this YAML config
- Story 1.6 (state): No config dependency
- Story 2.1 (market discovery): Will use `config.leagues` for league filtering
- Story 2.2 (scheduling): Will use `config.timing.daily_fetch_hour_utc`
- Story 2.4 (liquidity): Will use `config.liquidity` thresholds
- Story 3.1 (buy orders): Will use `config.btts.order_size`, `config.btts.buy_expiration_hours`

### References

- Epics: Story 1.2 acceptance criteria — [Source: epics.md#Story 1.2: Configuration Loading and Validation with Pydantic]
- Architecture: Config YAML canonical structure — [Source: architecture.md#Config YAML Canonical Structure]
- Architecture: Pydantic models decision — [Source: architecture.md#Configuration & Environment]
- Architecture: config.py location — [Source: architecture.md#Complete Project Directory Structure]
- Architecture: Module organization — [Source: architecture.md#Module Organization]
- PRD: FR1 (CLI config path), FR2 (load config), FR4 (validate at startup) — [Source: prd.md#Configuration & Initialization]
- PRD: Config schema — [Source: prd.md#Configuration Schema]
- Previous story: Story 1.1 file list — [Source: 1-1-initialize-project-with-uv-and-package-structure.md#File List]

### Previous Story Intelligence

From Story 1.1 implementation:
- Python 3.14 was used successfully (no fallback to 3.13 needed)
- `py-clob-client` resolved on 3.14
- ruff configured with `line-length = 100`, `target-version = "py314"` — all code must conform
- `config_btts.example.yaml` already exists with the canonical structure — use it as the contract for model fields
- `main.py` currently contains only `def main() -> None: print("btts-bot starting...")` — this will be expanded
- `config.py` is a stub with docstring + TODO comment — replace entirely with implementation
- All stubs use module docstrings — maintain this pattern for the top of config.py

## Dev Agent Record

### Agent Model Used

github-copilot/gpt-5.3-codex

### Debug Log References

- `uv run python -m unittest discover -s tests -p "test_*.py" -t .`
- `uv run ruff check btts_bot/ tests/`
- `uv run ruff format --check btts_bot/ tests/`
- `cp "config_btts.example.yaml" "config_btts.yaml" && uv run python -m btts_bot`
- `uv run python -m btts_bot --config config_btts.example.yaml`
- `uv run python -m btts_bot --config nonexistent.yaml`
- `uv run python - <<'PY' ... invalid.yaml ... PY`

### Completion Notes List

- Implemented complete typed Pydantic v2 config model hierarchy in `btts_bot/config.py` with field constraints and log-level normalization/validation.
- Implemented `load_config(config_path: Path) -> BotConfig` with robust startup-fail behavior for missing files, YAML parse errors, empty YAML, and Pydantic validation errors.
- Implemented CLI parsing in `btts_bot/main.py` with `--config` override and default `config_btts.yaml`, ensuring config load is first startup action and no partial startup occurs on error.
- Added unit tests for config validation/loading and main CLI behavior in `tests/test_config.py` and `tests/test_main.py`.
- Verified successful and failing runtime scenarios plus lint/format/test validation.

### File List

- `btts_bot/config.py`
- `btts_bot/main.py`
- `tests/__init__.py`
- `tests/test_config.py`
- `tests/test_main.py`

### Change Log

- 2026-03-29: Implemented Story 1.2 config models, YAML loader, CLI config path handling, and validation/manual test coverage; set status to `review`.
