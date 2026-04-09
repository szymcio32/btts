"""Data API client for Polymarket position data."""

import logging
import threading

import requests

from btts_bot.constants import DATA_API_HOST
from btts_bot.retry import with_retry

logger = logging.getLogger(__name__)


class DataApiClient:
    """Thin wrapper around the Polymarket Data API for querying wallet positions.

    The Data API is a public REST API (no authentication required).
    Positions are filtered by proxy wallet address.

    Thread-safe: all methods protected by a per-instance lock.
    """

    def __init__(self, proxy_address: str) -> None:
        self._proxy_address = proxy_address
        self._lock = threading.Lock()

    @with_retry
    def get_positions(self) -> list[dict] | None:
        """Query the Polymarket Data API for all open positions of the proxy wallet.

        Returns a list of position dicts (each with 'asset' and 'size' fields),
        or None if retries are exhausted.
        """
        with self._lock:
            url = f"{DATA_API_HOST}/positions"
            params = {"user": self._proxy_address}
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list):
            logger.warning(
                "DataApiClient.get_positions: unexpected response format (expected list, got %s)",
                type(data).__name__,
            )
            return []

        logger.info("DataApiClient: fetched %d positions for proxy wallet", len(data))
        return data
