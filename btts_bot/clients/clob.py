"""CLOB client wrapper for Polymarket."""

import logging
import os
import sys
import threading

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.constants import POLYGON

from btts_bot.constants import CLOB_HOST, POLY_GNOSIS_SAFE
from btts_bot.retry import with_retry

logger = logging.getLogger(__name__)


class ClobClientWrapper:
    """Authenticated Polymarket CLOB client wrapper.

    Performs three-phase authentication on instantiation:
      Phase 1 — L1 ClobClient (key + chain_id) used only to derive API creds.
      Phase 2 — derive/create API credentials via create_or_derive_api_creds().
      Phase 3 — L2 ClobClient (key + chain_id + creds + signature_type=POLY_GNOSIS_SAFE).

    Exits with SystemExit(1) if required environment variables are missing.
    Thread-safe: all methods that access self._client are protected by a per-instance lock.
    The lock is held per-attempt (not across retry attempts) so other threads can make
    CLOB calls between retries.
    """

    def __init__(self) -> None:
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        proxy_address = os.environ.get("POLYMARKET_PROXY_ADDRESS")

        if not private_key:
            print(
                "Error: POLYMARKET_PRIVATE_KEY environment variable is not set.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        if not proxy_address:
            print(
                "Error: POLYMARKET_PROXY_ADDRESS environment variable is not set.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        self._lock = threading.Lock()

        # Phase 1: L1 client — only used to derive creds
        l1_client = ClobClient(host=CLOB_HOST, chain_id=POLYGON, key=private_key)

        # Phase 2: Derive or create API credentials
        creds = l1_client.create_or_derive_api_creds()

        # Phase 3: L2 client — the operational client
        self._client = ClobClient(
            host=CLOB_HOST,
            chain_id=POLYGON,
            key=private_key,
            creds=creds,
            signature_type=POLY_GNOSIS_SAFE,
            funder=proxy_address,
        )

        # Discard L1 reference immediately
        del l1_client

        logger.info("ClobClientWrapper initialized — L2 auth established")

    def get_tick_size(self, token_id: str) -> str:
        """Return the tick size for the given token (TTL-cached internally by py-clob-client)."""
        with self._lock:
            return self._client.get_tick_size(token_id)

    @with_retry
    def get_order_book(self, token_id: str):
        """Fetch the order book for a token."""
        with self._lock:
            return self._client.get_order_book(token_id)

    @with_retry
    def get_order(self, order_id: str):
        """Fetch a specific order by ID."""
        with self._lock:
            return self._client.get_order(order_id)

    @with_retry
    def post_order(self, order, order_type: str = "GTC"):
        """Post an order to the CLOB."""
        with self._lock:
            return self._client.post_order(order, order_type)

    @with_retry
    def cancel_order(self, order_id: str):
        """Cancel a single order by ID."""
        with self._lock:
            return self._client.cancel({"orderID": order_id})

    @with_retry
    def cancel_orders(self, order_ids: list[str]):
        """Cancel multiple orders by their IDs."""
        with self._lock:
            return self._client.cancel_orders([{"orderID": oid} for oid in order_ids])

    @with_retry
    def create_buy_order(
        self, token_id: str, price: float, size: float, expiration_ts: int
    ) -> dict | None:
        """Create and post a GTD limit buy order.

        Returns the API response dict containing the order ID,
        or None if the retry decorator exhausts retries.
        """
        with self._lock:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=float(size),
                side="BUY",
                expiration=expiration_ts,
            )
            signed_order = self._client.create_order(order_args)
            return self._client.post_order(signed_order, orderType=OrderType.GTD)

    @with_retry
    def create_sell_order(self, token_id: str, price: float, size: float) -> dict | None:
        """Create and post a GTC limit sell order.

        Returns the API response dict containing the order ID,
        or None if the retry decorator exhausts retries.
        """
        with self._lock:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=float(size),
                side="SELL",
                expiration=0,  # GTC -- no expiration
            )
            signed_order = self._client.create_order(order_args)
            return self._client.post_order(signed_order, orderType=OrderType.GTC)

    @with_retry
    def get_open_orders(self) -> list | None:
        """Fetch all open orders for the authenticated wallet.

        Returns a list of order objects on success,
        or None if retries are exhausted.
        """
        with self._lock:
            return self._client.get_orders(params={"status": "LIVE"})
