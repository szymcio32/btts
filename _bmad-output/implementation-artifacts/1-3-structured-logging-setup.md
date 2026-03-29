# Story 1.3: Structured Logging Setup

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want the bot to log all events with timestamps, levels, and context to both file and console,
So that I can monitor operations in real-time and review logs later for troubleshooting.

## Acceptance Criteria

1. **Given** a valid logging configuration (level, file_path, max_bytes, backup_count)
   **When** the bot starts
   **Then** a `RotatingFileHandler` is configured with the specified file path, max bytes, and backup count
   **And** a console handler (`StreamHandler`) outputs to stdout simultaneously
   **And** log format matches `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
   **And** the log file is created with owner-only read/write permissions (`0o600`)

2. **Given** a log message is emitted from any module
   **When** the message contains patterns matching private keys or API secrets
   **Then** the secret filter redacts them before writing to file or console
   **And** credentials never appear in any log output

3. **Given** the logging setup is complete
   **When** any module calls `logging.getLogger(__name__)`
   **Then** the returned logger inherits the configured handlers and format
   **And** the root logger level matches `config.logging.level`

## Tasks / Subtasks

- [x] Task 1: Implement `SecretFilter` class in `btts_bot/logging_setup.py` (AC: #2)
  - [x] Create `SecretFilter(logging.Filter)` that reads secret patterns from environment variables at initialization
  - [x] Read `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` from `os.environ` (use `.get()` — do not crash if not set; there will be no patterns to redact in that case)
  - [x] In `filter(record)` method: convert `record.msg` and `record.args` to string, search for any loaded secret pattern, replace with `[REDACTED]`
  - [x] Also redact `record.exc_text` if present (exception tracebacks that include credential values)
  - [x] Handle `record.args` properly: if `record.args` is a tuple/dict, format the message first, then redact, then set `record.msg` to the redacted string and `record.args` to `None`

- [x] Task 2: Implement `setup_logging(config: LoggingConfig)` function in `btts_bot/logging_setup.py` (AC: #1, #3)
  - [x] Accept a `LoggingConfig` instance (imported from `btts_bot.config`)
  - [x] Get the root logger via `logging.getLogger()`
  - [x] Set root logger level to `config.level` (already normalized to uppercase by `LoggingConfig.validate_log_level`)
  - [x] Create a `logging.Formatter` with format string `"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"`
  - [x] Create a `RotatingFileHandler` with `filename=config.file_path`, `maxBytes=config.max_bytes`, `backupCount=config.backup_count`, `encoding="utf-8"`
  - [x] Create a `StreamHandler` writing to `sys.stdout` (not stderr — stdout is for monitoring)
  - [x] Attach the formatter to both handlers
  - [x] Add `SecretFilter` instance to both handlers (filter at handler level, not logger level, to catch all messages)
  - [x] Add both handlers to the root logger
  - [x] Clear any existing handlers on root logger before adding (prevent duplicate handlers on repeated calls)

- [x] Task 3: Set log file permissions to `0o600` (AC: #1)
  - [x] After the `RotatingFileHandler` creates the log file, set permissions via `os.chmod(config.file_path, 0o600)`
  - [x] Handle the case where the file doesn't exist yet (RotatingFileHandler with `delay=False` creates it immediately — this is the default)
  - [x] On Windows (where `os.chmod` has limited effect), wrap in a try/except and log a warning — do not crash

- [x] Task 4: Wire `setup_logging()` into `btts_bot/main.py` (AC: #1, #3)
  - [x] Import `setup_logging` from `btts_bot.logging_setup`
  - [x] Call `setup_logging(config.logging)` immediately after `load_config()` returns
  - [x] Capture the `BotConfig` return value from `load_config()` (currently discarded — must fix)
  - [x] Replace `print(...)` startup message with `logger.info(...)` using a module-level logger
  - [x] Create module-level logger: `logger = logging.getLogger(__name__)`

- [x] Task 5: Verify with manual testing
  - [x] Run `uv run python -m btts_bot` with a valid config — confirm log output appears on console with correct format
  - [x] Check that `btts_bot.log` (or configured path) is created with correct content
  - [x] Check log file permissions (on Linux/WSL): `stat -c %a btts_bot.log` should show `600`
  - [x] Set `POLYMARKET_PRIVATE_KEY=test_secret_key_12345` env var, add a temporary `logger.info("key is test_secret_key_12345")` call, and verify the output shows `[REDACTED]` instead of the key value
  - [x] Run `uv run ruff check btts_bot/` and `uv run ruff format btts_bot/` — should pass cleanly

## Dev Notes

### Critical: This story establishes logging infrastructure ONLY

This story creates the logging foundation: handlers, formatters, secret filter, file permissions. The `LoggerAdapter` for per-market context binding (`[Home vs Away]`) is NOT part of this story — that is Story 5.2. All modules in Epics 2-4 should use standard module loggers (`logging.getLogger(__name__)`); the market-context adapter is layered on in Epic 5 without requiring changes to this infrastructure.

### SecretFilter implementation pattern

The filter must catch secrets even when they appear in formatted exception tracebacks. The safest approach is to redact at the string level after formatting:

```python
import logging
import os
import re


class SecretFilter(logging.Filter):
    """Redacts sensitive values from log records before output."""

    def __init__(self) -> None:
        super().__init__()
        self._patterns: list[re.Pattern[str]] = []
        for env_var in ("POLYMARKET_PRIVATE_KEY", "POLYMARKET_PROXY_ADDRESS"):
            value = os.environ.get(env_var)
            if value:
                self._patterns.append(re.compile(re.escape(value)))

    def filter(self, record: logging.LogRecord) -> bool:
        if self._patterns:
            # Format the message with args first, then redact
            record.msg = self._redact(record.getMessage())
            record.args = None
            if record.exc_text:
                record.exc_text = self._redact(record.exc_text)
        return True

    def _redact(self, text: str) -> str:
        for pattern in self._patterns:
            text = pattern.sub("[REDACTED]", text)
        return text
```

Key implementation details:
- Call `record.getMessage()` to merge `msg` + `args` into the final string, then redact the merged result, then set `args = None` to prevent double-formatting
- Return `True` always — the filter redacts but never suppresses messages
- Build regex patterns from `re.escape()` to handle special chars in keys/addresses
- Initialize patterns once at construction time, not on every `filter()` call

### RotatingFileHandler configuration

```python
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    filename=config.file_path,
    maxBytes=config.max_bytes,
    backupCount=config.backup_count,
    encoding="utf-8",
)
```

- `maxBytes=10_485_760` (10 MB default from config) — file rotates when this size is exceeded
- `backupCount=5` (default from config) — keeps `btts_bot.log`, `btts_bot.log.1` through `btts_bot.log.5`
- `encoding="utf-8"` — explicit encoding for cross-platform consistency
- Do NOT set `delay=True` — the file must be created immediately so permissions can be set

### Console handler must use stdout, not stderr

```python
import sys

console_handler = logging.StreamHandler(sys.stdout)
```

Architecture specifies stdout for console output. `StreamHandler()` defaults to `stderr` — must explicitly pass `sys.stdout`.

### Log format string — exact match required

```python
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
```

This format is mandated by the architecture document. The `%(levelname)-8s` left-pads the level name to 8 characters for alignment. Do NOT modify this format.

Example output:
```
2026-03-28 15:00:12,345 | INFO     | btts_bot.main | btts-bot starting... config loaded from config_btts.yaml
```

### File permissions implementation

```python
import os
from pathlib import Path

def _set_file_permissions(file_path: str) -> None:
    """Set log file to owner-only read/write (0o600)."""
    try:
        os.chmod(file_path, 0o600)
    except OSError:
        # Windows or permission error — non-fatal, log a warning
        pass
```

Call this after creating the `RotatingFileHandler` (which creates the file). On Windows, `os.chmod` has limited effect but won't crash. The `pass` in the except is acceptable here because logging isn't set up yet when this runs — use a bare `pass` or print to stderr.

**Important:** Rotated log files (`btts_bot.log.1`, etc.) will NOT have `0o600` permissions set by default. To handle this properly, the `RotatingFileHandler` could be subclassed to set permissions on rotation, but this is a nice-to-have — the primary file permission is the critical requirement.

### main.py changes — capture config and use logger

The current `main.py` discards the `BotConfig` return value from `load_config()`. This must be fixed:

```python
import argparse
import logging
from pathlib import Path

from btts_bot.config import load_config
from btts_bot.logging_setup import setup_logging

logger = logging.getLogger(__name__)


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
    setup_logging(config.logging)
    logger.info("btts-bot starting... config loaded from %s", args.config)
```

Key changes from current:
- Import and call `setup_logging(config.logging)`
- Capture `config = load_config(args.config)` instead of discarding the return
- Replace `print()` with `logger.info()` using `%s` formatting (not f-string — logging best practice for deferred formatting)
- Module-level `logger = logging.getLogger(__name__)` following project convention

### setup_logging function — clear existing handlers

```python
def setup_logging(config: LoggingConfig) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(config.level)

    # Clear any existing handlers to prevent duplicates
    root_logger.handlers.clear()

    # ... create and add handlers ...
```

Clearing handlers is critical to prevent duplicate output if `setup_logging` is ever called more than once (e.g., in tests).

### Files to modify

- `btts_bot/logging_setup.py` — **primary implementation**: `SecretFilter` class + `setup_logging()` function
- `btts_bot/main.py` — wire `setup_logging()` call, capture config, replace print with logger

### Files NOT to touch

- `btts_bot/config.py` — `LoggingConfig` already exists with correct fields from Story 1.2
- `btts_bot/__main__.py` — already correct from Story 1.1
- `config_btts.example.yaml` — already has logging section from Story 1.1
- All stub files in `clients/`, `state/`, `core/` — not relevant to this story

### LoggingConfig reference (from Story 1.2, already implemented)

```python
class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: str = "btts_bot.log"
    max_bytes: int = Field(default=10_485_760, gt=0)
    backup_count: int = Field(default=5, ge=0)

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = value.upper()
        if normalized not in valid_levels:
            allowed = ", ".join(sorted(valid_levels))
            raise ValueError(f"Invalid log level '{value}'. Must be one of: {allowed}")
        return normalized
```

The `level` field is already normalized to uppercase (e.g., `"INFO"`) by the validator. Pass it directly to `root_logger.setLevel(config.level)` — Python's `logging.setLevel()` accepts string level names.

### Downstream story dependencies

- Story 1.4 (retry decorator): Will log retry attempts at WARNING level and exhausted retries at ERROR level — depends on logging being configured
- Story 1.5 (CLOB auth): Will set env vars `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` — the `SecretFilter` must already be in place to redact these from logs
- Story 5.2 (LoggerAdapter): Builds on this foundation by adding `LoggerAdapter` for per-market `[Home vs Away]` context — requires NO changes to this logging infrastructure
- Story 5.3 (credential protection): Extends the secret filter pattern to also cover API key, secret, passphrase — the filter architecture here must be extensible (it is, via the env var list)

### Architecture compliance checklist

- [x] Log format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s` — matches architecture spec exactly
- [x] RotatingFileHandler for long-running operation — as specified
- [x] Dual output: file + console (stdout) simultaneously — as specified
- [x] Per-module loggers via `logging.getLogger(__name__)` — as specified
- [x] Secret filter to redact credentials from all log output — as specified (NFR5)
- [x] Log file permissions: owner-only read/write (0o600) — as specified (NFR7)
- [x] Config-driven: log level, file path, rotation settings from `LoggingConfig` — as specified

### Python 3.14 stdlib logging — no API changes

Python 3.14's `logging` module has no breaking changes from 3.13. The only 3.14 addition is `QueueListener` context manager support, which is irrelevant here. All patterns in this story use stable, long-standing logging APIs.

### Project Structure Notes

- `logging_setup.py` is at `btts_bot/logging_setup.py` (top-level of the package)
- This follows the architecture: logging setup is a top-level infrastructure concern
- No circular imports: `logging_setup.py` imports only from `btts_bot.config` (for type hints) and stdlib `logging`/`os`/`sys`/`re`
- The `setup_logging` function signature is `setup_logging(config: LoggingConfig) -> None` to match downstream expectations

### References

- Epics: Story 1.3 acceptance criteria — [Source: epics.md#Story 1.3: Structured Logging Setup]
- Epics: Cross-Epic Dependency Note on LoggerAdapter — [Source: epics.md#Story 1.3, dependency note]
- Architecture: Logging & Observability decision — [Source: architecture.md#Logging & Observability]
- Architecture: Log format string — [Source: architecture.md#Log Message Format]
- Architecture: Logging levels — [Source: architecture.md#Communication Patterns > Logging Levels]
- Architecture: Secret filter location — [Source: architecture.md#Cross-Cutting Concerns > Location table]
- Architecture: logging_setup.py purpose — [Source: architecture.md#Complete Project Directory Structure]
- PRD: FR25 (structured logging), FR28 (credential exclusion) — [Source: prd.md via epics.md#Requirements Inventory]
- PRD: NFR5 (no credentials in logs), NFR7 (restrictive log file permissions) — [Source: prd.md via epics.md#Requirements Inventory]
- Previous story 1.2: LoggingConfig model — [Source: 1-2-configuration-loading-and-validation-with-pydantic.md#Completion Notes]
- Previous story 1.2: main.py current state — [Source: 1-2-configuration-loading-and-validation-with-pydantic.md#File List]
- Python 3.14 RotatingFileHandler docs — [Source: docs.python.org/3/library/logging.handlers.html#rotatingfilehandler]

### Previous Story Intelligence

From Story 1.2 implementation:
- `LoggingConfig` is fully implemented in `btts_bot/config.py` with `level`, `file_path`, `max_bytes`, `backup_count` fields
- `level` field has a `@field_validator` that normalizes to uppercase — safe to pass directly to `logging.setLevel()`
- `main.py` currently does NOT capture the `BotConfig` return value from `load_config()` — this MUST be fixed in this story
- `main.py` uses `print()` for startup message — must be replaced with `logger.info()`
- Pydantic v2 syntax is used throughout — maintain consistency
- ruff is configured with `line-length = 100`, `target-version = "py314"` — all code must conform
- Python 3.14 is in use (no 3.13 fallback was needed)
- Tests exist in `tests/test_config.py` and `tests/test_main.py` — be aware they test `main()` behavior and may need updates if `main()` changes affect exit behavior

## Dev Agent Record

### Agent Model Used

github-copilot/gpt-5.4

### Debug Log References

- `uv run python -m unittest tests.test_logging_setup tests.test_main tests.test_config`
- `uv run ruff check btts_bot tests`
- `uv run ruff format --check btts_bot tests`
- `uv run python -m btts_bot --config config_btts.example.yaml`
- `POLYMARKET_PRIVATE_KEY=test_secret_key_12345 uv run python -c "import logging; from btts_bot.config import LoggingConfig; from btts_bot.logging_setup import setup_logging; setup_logging(LoggingConfig(level='INFO', file_path='secret_test.log', max_bytes=1024, backup_count=1)); logging.getLogger(__name__).info('key is %s', 'test_secret_key_12345')"`
- `uv run python -c "from pathlib import Path; import tempfile, subprocess, textwrap, os; config_text = textwrap.dedent('''leagues:\n  - name: Premier League\n    abbreviation: EPL\nbtts:\n  order_size: 30\n  price_diff: 0.02\nliquidity:\n  standard_depth: 1000\n  deep_book_threshold: 2000\n  low_liquidity_total: 500\n  tick_offset: 0.01\ntiming:\n  daily_fetch_hour_utc: 23\nlogging:\n  level: INFO\n  file_path: /tmp/btts_bot_story13.log\n  max_bytes: 10485760\n  backup_count: 5\n'''); tmp = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False); tmp.write(config_text); tmp.close(); subprocess.run(['uv', 'run', 'python', '-m', 'btts_bot', '--config', tmp.name], check=True); print(oct(Path('/tmp/btts_bot_story13.log').stat().st_mode & 0o777)); os.unlink(tmp.name)"`

### Completion Notes List

- Implemented `SecretFilter` and `setup_logging()` in `btts_bot/logging_setup.py` with root logger handler reset, shared formatter, handler-level secret redaction, and restrictive log-file permission handling.
- Updated `btts_bot/main.py` to capture the loaded config, initialize logging immediately, and emit the startup message through a module logger instead of `print()`.
- Added coverage in `tests/test_logging_setup.py` for redaction, handler wiring, formatter reuse, and permission checks, and updated `tests/test_main.py` for logging bootstrap behavior.
- Verified runtime behavior manually with the example config, a secret-redaction smoke test, and a Linux `/tmp` permission check confirming `0o600` on a native filesystem.

### File List

- `btts_bot/logging_setup.py`
- `btts_bot/main.py`
- `tests/test_logging_setup.py`
- `tests/test_main.py`

## Change Log

- 2026-03-29: Implemented Story 1.3 structured logging, secret redaction, startup logger integration, and automated/manual verification; set status to `review`.
