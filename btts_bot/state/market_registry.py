"""
Market registry for tracking active BTTS markets.
Implemented in Story 1.6.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime

from btts_bot.core.game_lifecycle import GameLifecycle

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MarketEntry:
    token_id: str
    condition_id: str
    token_ids: list[str]
    kickoff_time: datetime
    league: str
    home_team: str
    away_team: str
    lifecycle: GameLifecycle


class MarketRegistry:
    def __init__(self) -> None:
        self._markets: dict[str, MarketEntry] = {}

    def register(
        self,
        token_id: str,
        condition_id: str,
        token_ids: list[str],
        kickoff_time: datetime,
        league: str,
        home_team: str,
        away_team: str,
    ) -> MarketEntry:
        if token_id in self._markets:
            raise ValueError(f"Market already registered for token_id={token_id}")
        lifecycle = GameLifecycle(token_id)
        entry = MarketEntry(
            token_id=token_id,
            condition_id=condition_id,
            token_ids=list(token_ids),
            kickoff_time=kickoff_time,
            league=league,
            home_team=home_team,
            away_team=away_team,
            lifecycle=lifecycle,
        )
        self._markets[token_id] = entry
        logger.info(
            "Market registered: [%s vs %s] token=%s league=%s kickoff=%s",
            home_team,
            away_team,
            token_id,
            league,
            kickoff_time.isoformat(),
        )
        return entry

    def get(self, token_id: str) -> MarketEntry | None:
        return self._markets.get(token_id)

    def is_processed(self, token_id: str) -> bool:
        return token_id in self._markets

    def all_markets(self) -> list[MarketEntry]:
        return list(self._markets.values())
