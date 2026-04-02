"""Market discovery from Polymarket data sources."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from btts_bot.clients.gamma import GammaClient
from btts_bot.config import LeagueConfig
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker

logger = logging.getLogger(__name__)

BTTS_MARKET_TYPE = "both_teams_to_score"
BTTS_NO_TOKEN_INDEX = 1  # index 0 = Yes, index 1 = No


class MarketDiscoveryService:
    """Discovers BTTS markets from JSON data and registers them."""

    def __init__(
        self,
        gamma_client: GammaClient,
        market_registry: MarketRegistry,
        leagues: list[LeagueConfig],
        order_tracker: OrderTracker,
    ) -> None:
        self._gamma_client = gamma_client
        self._registry = market_registry
        self._order_tracker = order_tracker
        # Build a set of lowercase abbreviations for fast lookup
        self._league_abbreviations: set[str] = {league.abbreviation.lower() for league in leagues}

    def discover_markets(self) -> int:
        """Run the full discovery pipeline. Returns total new markets discovered."""
        games = self._gamma_client.fetch_games()
        if games is None:
            logger.error("Market discovery failed: could not fetch games data")
            return 0

        total_discovered = 0
        per_league_counts: dict[str, int] = {}

        for game in games:
            if not isinstance(game, dict):
                logger.warning(
                    "Skipping malformed game entry: expected object, got %s", type(game).__name__
                )
                continue

            league = game.get("league", "")
            if not isinstance(league, str):
                logger.warning(
                    "[%s vs %s] Invalid league value type (%s), skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    type(league).__name__,
                )
                continue

            league_key = league.lower()
            if league_key not in self._league_abbreviations:
                continue

            btts_market = self._find_btts_market(game)
            if btts_market is None:
                continue

            token_ids = btts_market.get("token_ids", [])
            if not isinstance(token_ids, list) or len(token_ids) < 2:
                logger.warning(
                    "[%s vs %s] BTTS market has insufficient token_ids, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            if not all(isinstance(token_id, str) and token_id for token_id in token_ids[:2]):
                logger.warning(
                    "[%s vs %s] BTTS market has invalid token_ids, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            no_token_id = token_ids[BTTS_NO_TOKEN_INDEX]

            # Duplicate check: already in registry
            if self._registry.is_processed(no_token_id):
                logger.debug(
                    "[%s vs %s] Already processed, skipping (token=%s)",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    no_token_id,
                )
                continue

            # Duplicate check: existing buy order (from API reconciliation)
            if self._order_tracker.has_buy_order(no_token_id):
                logger.info(
                    "[%s vs %s] Buy order already exists, skipping (token=%s)",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                    no_token_id,
                )
                continue

            # Parse kickoff time
            kickoff_utc = self._parse_kickoff(game.get("kickoff_utc", ""))
            if kickoff_utc is None:
                logger.warning(
                    "[%s vs %s] Invalid kickoff_utc, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            # Register in MarketRegistry
            condition_id = btts_market.get("condition_id")
            if not isinstance(condition_id, str) or not condition_id:
                logger.warning(
                    "[%s vs %s] BTTS market missing condition_id, skipping",
                    game.get("home_team", "?"),
                    game.get("away_team", "?"),
                )
                continue

            self._registry.register(
                token_id=no_token_id,
                condition_id=condition_id,
                token_ids=list(token_ids),
                kickoff_time=kickoff_utc,
                league=league_key,
                home_team=game.get("home_team", "Unknown"),
                away_team=game.get("away_team", "Unknown"),
            )

            total_discovered += 1
            per_league_counts[league_key] = per_league_counts.get(league_key, 0) + 1

        # Log per-league summary
        for league_abbr, count in per_league_counts.items():
            logger.info("Discovery: %s — %d BTTS markets found", league_abbr, count)

        # Log leagues with zero markets
        for abbr in self._league_abbreviations:
            if abbr not in per_league_counts:
                logger.info("Discovery: %s — 0 BTTS markets found", abbr)

        logger.info("Market discovery complete: %d new markets registered", total_discovered)
        return total_discovered

    def _find_btts_market(self, game: dict) -> dict | None:
        """Find the BTTS market in a game's polymarket data."""
        polymarket = game.get("polymarket", {})
        if not isinstance(polymarket, dict):
            return None
        markets = polymarket.get("markets", [])
        if not isinstance(markets, list):
            return None
        for market in markets:
            if not isinstance(market, dict):
                continue
            if market.get("market_type") == BTTS_MARKET_TYPE:
                return market
        return None

    def _parse_kickoff(self, kickoff_value: object) -> datetime | None:
        """Parse kickoff_utc string to timezone-aware datetime."""
        if not isinstance(kickoff_value, str) or not kickoff_value:
            return None
        try:
            # ISO 8601 format: "2026-03-22T04:00:00Z"
            parsed = datetime.fromisoformat(kickoff_value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

        if parsed.tzinfo is None:
            return None

        return parsed.astimezone(timezone.utc)
