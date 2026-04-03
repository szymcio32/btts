"""Position tracker for monitoring fill accumulation."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks accumulated fill sizes per token_id.

    Pure data manager — holds state and answers queries.
    Never initiates API calls.
    """

    def __init__(self) -> None:
        self._fills: dict[str, float] = {}

    def accumulate(self, token_id: str, fill_size: float) -> None:
        """Add fill_size to the running total for token_id."""
        self._fills[token_id] = self._fills.get(token_id, 0.0) + fill_size
        logger.debug(
            "Fill accumulated: token=%s +%.2f (total: %.2f)",
            token_id,
            fill_size,
            self._fills[token_id],
        )

    def get_accumulated_fills(self, token_id: str) -> float:
        """Return accumulated fill size for token_id (default 0.0)."""
        return self._fills.get(token_id, 0.0)

    def has_reached_threshold(self, token_id: str, min_size: float) -> bool:
        """Return True if accumulated fills >= min_size."""
        return self._fills.get(token_id, 0.0) >= min_size
