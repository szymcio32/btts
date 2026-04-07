"""Position tracker for monitoring fill accumulation."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks accumulated fill sizes per token_id.

    Pure data manager — holds state and answers queries.
    Never initiates API calls.
    Thread-safe: all public methods protected by a per-instance lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fills: dict[str, float] = {}

    def accumulate(self, token_id: str, fill_size: float) -> None:
        """Add fill_size to the running total for token_id."""
        with self._lock:
            self._fills[token_id] = self._fills.get(token_id, 0.0) + fill_size
            total = self._fills[token_id]
        logger.debug(
            "Fill accumulated: token=%s +%.2f (total: %.2f)",
            token_id,
            fill_size,
            total,
        )

    def get_accumulated_fills(self, token_id: str) -> float:
        """Return accumulated fill size for token_id (default 0.0)."""
        with self._lock:
            return self._fills.get(token_id, 0.0)

    def has_reached_threshold(self, token_id: str, min_size: float) -> bool:
        """Return True if accumulated fills >= min_size."""
        with self._lock:
            return self._fills.get(token_id, 0.0) >= min_size
