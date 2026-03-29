# Story 1.5: Polymarket CLOB Client Authentication

Status: review

## Story

As an operator,
I want the bot to authenticate with Polymarket using my environment variables,
so that it can place and manage orders on my behalf.

## Acceptance Criteria

1. **Given** environment variables `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` are set
   **When** the bot starts
   **Then** `ClobClientWrapper` builds an L1 `ClobClient` (key + chain_id) to derive API credentials via `create_or_derive_api_creds()`
   **And** constructs an L2 `ClobClient` (key + chain_id + creds + signature_type=2 + funder=proxy_address) ready for order operations
   **And** tick-size cache is initialized (built into `py-clob-client` — no extra cache needed in wrapper)

2. **Given** `POLYMARKET_PRIVATE_KEY` or `POLYMARKET_PROXY_ADDRESS` environment variables are missing
   **When** the bot starts
   **Then** it exits with a non-zero exit code and a clear error message (without exposing credential values)

3. **Given** a successful authentication
   **When** any module inspects log output
   **Then** no private key, API key, API secret, or passphrase values appear in logs (enforced by existing `SecretFilter` in `logging_setup.py`)

4. **Given** `ClobClientWrapper` is instantiated
   **When** the `get_tick_size(token_id)` method is called
   **Then** it delegates to `self._client.get_tick_size(token_id)` (TTL-cached internally by `py-clob-client`)
   **And** returns the tick size string for that token

## Tasks / Subtasks

- [x] Task 1: Implement `ClobClientWrapper` in `btts_bot/clients/clob.py` (AC: #1, #2, #3, #4)
  - [x] Add module-level logger: `logger = logging.getLogger(__name__)`
  - [x] Read `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` from `os.environ` in `__init__`; exit with clear message (no credential values) if missing
  - [x] Build L1 client: `ClobClient(host=CLOB_HOST, chain_id=POLYGON, key=private_key)` — used only to derive creds
  - [x] Derive API creds: `creds = l1_client.create_or_derive_api_creds()` (creates if not exists, derives if already created)
  - [x] Build L2 client: `ClobClient(host=CLOB_HOST, chain_id=POLYGON, key=private_key, creds=creds, signature_type=2, funder=proxy_address)`
  - [x] Store L2 client as `self._client`; discard L1 reference immediately
  - [x] Implement `get_tick_size(self, token_id: str) -> str` — delegates to `self._client.get_tick_size(token_id)`
  - [x] Implement `get_order_book(self, token_id: str)` — delegates to `self._client.get_order_book(token_id)`, decorated with `@with_retry`
  - [x] Implement `get_order(self, order_id: str)` — delegates to `self._client.get_order(order_id)`, decorated with `@with_retry`
  - [x] Implement `post_order(self, order, order_type)` — delegates to `self._client.post_order(order, order_type)`, decorated with `@with_retry`
  - [x] Implement `cancel_order(self, order_id: str)` — delegates to `self._client.cancel({"orderID": order_id})`, decorated with `@with_retry`
  - [x] Implement `cancel_orders(self, order_ids: list[str])` — delegates to `self._client.cancel_orders([{"orderID": oid} for oid in order_ids])`, decorated with `@with_retry`
  - [x] Log at INFO: `"ClobClientWrapper initialized — L2 auth established"` (no credential values)

- [x] Task 2: Add `CLOB_HOST` constant to `btts_bot/constants.py` (AC: #1)
  - [x] Add `CLOB_HOST: str = "https://clob.polymarket.com"`
  - [x] Add `CHAIN_ID: int = 137` (POLYGON)
  - [x] Add `POLY_GNOSIS_SAFE: int = 2` (signature type for proxy wallet / Gnosis Safe)

- [x] Task 3: Wire `ClobClientWrapper` into `main.py` startup (AC: #2)
  - [x] After `setup_logging()`, instantiate `ClobClientWrapper()` — it exits cleanly on missing env vars
  - [x] Log at INFO: `"Authentication successful"` after wrapper initializes

- [x] Task 4: Add tests in `tests/test_clob_client.py` (AC: #1, #2, #3, #4)
  - [x] Test: missing `POLYMARKET_PRIVATE_KEY` → `SystemExit` with non-zero code, error message contains no key value
  - [x] Test: missing `POLYMARKET_PROXY_ADDRESS` → `SystemExit` with non-zero code
  - [x] Test: valid env vars → L1 client created, `create_or_derive_api_creds` called, L2 client constructed with `signature_type=2` and `funder=proxy_address`
  - [x] Test: `get_tick_size` delegates to internal `_client.get_tick_size`
  - [x] Test: `get_order_book` uses `@with_retry` (mock to return None on exhaustion → wrapper returns None)
  - [x] Test: log output contains no credential values (use `assertLogs` and inspect messages)

- [x] Task 5: Lint and format (all stories convention)
  - [x] `uv run ruff check btts_bot/ tests/` — zero issues
  - [x] `uv run ruff format btts_bot/ tests/` — no changes needed

## Dev Notes

### File locations

- `btts_bot/clients/clob.py` — replace the stub entirely (currently 5-line TODO)
- `btts_bot/constants.py` — replace stub, add `CLOB_HOST`, `CHAIN_ID`, `POLY_GNOSIS_SAFE`
- `btts_bot/main.py` — add `ClobClientWrapper()` instantiation after `setup_logging()`
- `tests/test_clob_client.py` — new file (does not exist yet)

### CLOB authentication: three-phase pattern

Architecture mandates: "Three-phase CLOB authentication: derive API creds from private key (L1), construct L2 client with proxy wallet and GNOSIS_SAFE signature type."

```python
# Phase 1: L1 client — only used to derive creds
l1 = ClobClient(host=CLOB_HOST, chain_id=CHAIN_ID, key=private_key)

# Phase 2: Derive or create API credentials
creds: ApiCreds = l1.create_or_derive_api_creds()
# ApiCreds is a dataclass: api_key, api_secret, api_passphrase

# Phase 3: L2 client — the operational client
self._client = ClobClient(
    host=CLOB_HOST,
    chain_id=CHAIN_ID,
    key=private_key,
    creds=creds,
    signature_type=POLY_GNOSIS_SAFE,  # 2 = POLY_GNOSIS_SAFE
    funder=proxy_address,             # proxy wallet address
)
```

**Critical import paths:**
```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
```

**`GNOSIS_SAFE` is NOT importable from `py_clob_client.constants`** (it does not exist there). The architecture description refers to the signature type value. The numeric value is `2` (`POLY_GNOSIS_SAFE`). Store it in `btts_bot/constants.py` as `POLY_GNOSIS_SAFE = 2`.

**`BUY`/`SELL` are NOT importable from `py_clob_client.clob_types`**. Side is specified as string: `"BUY"` or `"SELL"` in `OrderArgs.side`. Add `BUY_SIDE = "BUY"` and `SELL_SIDE = "SELL"` to `btts_bot/constants.py` for use in later stories.

### `py-clob-client` tick-size cache behavior

`ClobClient.get_tick_size(token_id)` has a built-in TTL cache (default 300s). The architecture says "tick-size cache per token ID in ClobClientWrapper (per-session, no invalidation needed)" — this is already provided by `py-clob-client` itself. Do NOT implement a second cache in `ClobClientWrapper`. Just delegate:
```python
def get_tick_size(self, token_id: str) -> str:
    return self._client.get_tick_size(token_id)
```

Note: `get_tick_size` makes an HTTP call if cache miss — it **is** retryable by nature. However, it is called indirectly via `create_order()` internally by `py-clob-client`. For direct calls in Story 3.1 (tick size fetch before order placement), the wrapper delegates. Story 3.1 should decorate the tick-size call with `@with_retry` at its own call site OR accept that `py-clob-client`'s internal retry is sufficient. For consistency, Story 3.1 should use `@with_retry` on `get_tick_size` — leave the option open by keeping the method plain (not decorated here).

### `@with_retry` placement on wrapper methods

All methods that make external API calls MUST be decorated with `@with_retry` per architecture rule "All API calls must be wrapped with `@with_retry` — no exceptions."

- `get_order_book(token_id)` — YES, decorate with `@with_retry`
- `get_order(order_id)` — YES, decorate with `@with_retry`
- `post_order(order, order_type)` — YES, decorate with `@with_retry`
- `cancel_order(order_id)` — YES, decorate with `@with_retry`
- `cancel_orders(order_ids)` — YES, decorate with `@with_retry`
- `get_tick_size(token_id)` — leave plain for now (used inline inside `create_order` by the SDK; Story 3.1 handles retry at call site)

```python
from btts_bot.retry import with_retry

class ClobClientWrapper:
    ...
    @with_retry
    def get_order_book(self, token_id: str):
        return self._client.get_order_book(token_id)

    @with_retry
    def get_order(self, order_id: str):
        return self._client.get_order(order_id)

    @with_retry
    def post_order(self, order, order_type: str = "GTC"):
        return self._client.post_order(order, order_type)

    @with_retry
    def cancel_order(self, order_id: str):
        return self._client.cancel({"orderID": order_id})

    @with_retry
    def cancel_orders(self, order_ids: list[str]):
        return self._client.cancel_orders([{"orderID": oid} for oid in order_ids])
```

### Credential protection

The existing `SecretFilter` in `logging_setup.py` redacts `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` env var values from all log messages. This story adds no new secret filter logic. However, `creds.api_key`, `creds.api_secret`, `creds.api_passphrase` derived by `create_or_derive_api_creds()` are not in `_SECRET_ENV_VARS`. Do NOT log creds directly at any point. Confirm in tests by asserting no key/secret/passphrase values appear.

### Missing env var exit pattern

```python
import os
import sys

private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
proxy_address = os.environ.get("POLYMARKET_PROXY_ADDRESS")

if not private_key:
    print("Error: POLYMARKET_PRIVATE_KEY environment variable is not set.", file=sys.stderr)
    raise SystemExit(1)

if not proxy_address:
    print("Error: POLYMARKET_PROXY_ADDRESS environment variable is not set.", file=sys.stderr)
    raise SystemExit(1)
```

**Critical:** The error message must NOT include the variable value (there is no value anyway — it's missing). Log at ERROR before exiting if logging is already set up; otherwise `print` to stderr.

### `create_or_derive_api_creds()` behavior

This L1 method calls `create_api_key(nonce)` first; if that fails (key already created), it falls back to `derive_api_key(nonce)`. Both make HTTP requests to the Polymarket CLOB auth endpoints. This call itself is not wrapped with `@with_retry` in the wrapper — it happens in `__init__` before the L2 client exists. If this fails (network error during startup), it is acceptable for the bot to crash with an unhandled exception at startup, since startup failures are CRITICAL per architecture. Do not add silent retry logic here.

### `cancel()` vs `cancel_order()` in py-clob-client

The SDK method for cancelling a single order is `ClobClient.cancel({"orderID": order_id})`. There is no `cancel_order` method on `ClobClient`. The wrapper exposes `cancel_order(order_id)` as a cleaner interface that internally calls `self._client.cancel(...)`.

For batch cancellation: `ClobClient.cancel_orders([{"orderID": id1}, {"orderID": id2}])`.

### Existing infrastructure to leverage

- `btts_bot/logging_setup.py` — `SecretFilter` already handles `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS` redaction. No changes needed here.
- `btts_bot/retry.py` — `@with_retry` decorator is fully implemented (Story 1.4). Import directly.
- `btts_bot/main.py` — `setup_logging()` is called before CLOB init; ensure logging is setup before `ClobClientWrapper()` so the wrapper's INFO log appears.

### Constants to add to `btts_bot/constants.py`

```python
"""Constants for btts-bot: API URLs, enums, and shared values."""

# Polymarket CLOB API
CLOB_HOST: str = "https://clob.polymarket.com"
CHAIN_ID: int = 137  # POLYGON

# Signature type for Polymarket proxy wallets (POLY_GNOSIS_SAFE = 2)
POLY_GNOSIS_SAFE: int = 2

# Order sides (used in OrderArgs.side)
BUY_SIDE: str = "BUY"
SELL_SIDE: str = "SELL"
```

`BUY_SIDE` and `SELL_SIDE` are not used in this story but establishing them here prevents later stories from hardcoding string literals.

### Project Structure Notes

Files touched in this story:
- `btts_bot/clients/clob.py` — replace stub with `ClobClientWrapper`
- `btts_bot/constants.py` — replace stub with CLOB constants
- `btts_bot/main.py` — add `ClobClientWrapper()` instantiation
- `tests/test_clob_client.py` — new test file

Files NOT to touch:
- `btts_bot/retry.py` — complete from Story 1.4
- `btts_bot/logging_setup.py` — complete from Story 1.3
- `btts_bot/config.py` — complete from Story 1.2
- `btts_bot/clients/gamma.py`, `btts_bot/clients/data_api.py` — stubs for later stories
- `btts_bot/state/*`, `btts_bot/core/*` — stubs for later stories

### Testing pattern

Mock `ClobClient` entirely — do not make real network calls:

```python
from unittest.mock import MagicMock, patch
import os
import pytest

@patch("btts_bot.clients.clob.ClobClient")
def test_init_success(mock_clob_cls, monkeypatch):
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xdeadbeef")
    monkeypatch.setenv("POLYMARKET_PROXY_ADDRESS", "0xproxy")

    mock_l1 = MagicMock()
    mock_creds = MagicMock()
    mock_creds.api_key = "test_key"
    mock_creds.api_secret = "test_secret"
    mock_creds.api_passphrase = "test_pass"
    mock_l1.create_or_derive_api_creds.return_value = mock_creds
    mock_l2 = MagicMock()
    mock_clob_cls.side_effect = [mock_l1, mock_l2]

    wrapper = ClobClientWrapper()

    assert wrapper._client is mock_l2
    # Verify L2 constructed with signature_type=2 and funder=proxy_address
    l2_call = mock_clob_cls.call_args_list[1]
    assert l2_call.kwargs["signature_type"] == 2
    assert l2_call.kwargs["funder"] == "0xproxy"
```

### References

- [Source: epics.md#Story 1.5: Polymarket CLOB Client Authentication] — acceptance criteria
- [Source: architecture.md#API Client Architecture & Retry Strategy] — `ClobClientWrapper` design, L0/L1/L2 auth tiers, tick-size caching
- [Source: architecture.md#Enforcement Guidelines] — "Wrap all API calls with `@with_retry` — no exceptions"
- [Source: architecture.md#Complete Project Directory Structure] — `clients/clob.py` location
- [Source: architecture.md#Core Architectural Decisions > Configuration & Environment] — `pydantic-settings` for env vars (not used here — env vars read directly for credentials per NFR5/NFR6)
- py-clob-client `ClobClient.__init__` signature: `(host, chain_id, key, creds, signature_type, funder)`
- py-clob-client signature type `2` = `POLY_GNOSIS_SAFE` (confirmed from `rfq_types.py` docstring: "0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE")
- py-clob-client `cancel()` takes `{"orderID": id}`, not a plain string

## Dev Agent Record

### Agent Model Used

github-copilot/claude-sonnet-4.6

### Debug Log References

None.

### Completion Notes List

- Implemented `ClobClientWrapper` in `btts_bot/clients/clob.py` with three-phase L1→creds→L2 authentication pattern.
- `SystemExit(1)` on missing `POLYMARKET_PRIVATE_KEY` or `POLYMARKET_PROXY_ADDRESS` — no credential values in error messages.
- All five external-call methods (`get_order_book`, `get_order`, `post_order`, `cancel_order`, `cancel_orders`) decorated with `@with_retry`; `get_tick_size` left plain per story spec.
- `btts_bot/constants.py` stub replaced with `CLOB_HOST`, `CHAIN_ID`, `POLY_GNOSIS_SAFE`, `BUY_SIDE`, `SELL_SIDE`.
- `btts_bot/main.py` updated to import and instantiate `ClobClientWrapper()` after `setup_logging()`; logs `"Authentication successful"`.
- `tests/test_clob_client.py` created with 15 tests covering all ACs: missing env vars, L1/L2 construction, delegation, retry exhaustion, credential redaction in logs.
- `tests/test_main.py` updated to patch `ClobClientWrapper` in existing tests and add 2 new tests for wrapper instantiation and auth-success log.
- 50/50 tests passing; `ruff check` and `ruff format --check` report zero issues.

### File List

- `btts_bot/clients/clob.py` — replaced stub with `ClobClientWrapper`
- `btts_bot/constants.py` — replaced stub with CLOB constants
- `btts_bot/main.py` — added `ClobClientWrapper` import and instantiation
- `tests/test_clob_client.py` — new file (15 tests)
- `tests/test_main.py` — updated to patch `ClobClientWrapper`; 2 new tests added

### Change Log

- 2026-03-29: Story 1.5 implemented — Polymarket CLOB client authentication with three-phase L1/L2 pattern, constants, main wiring, 15 new tests, full lint pass.
