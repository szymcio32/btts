"""Tests for MarketDiscoveryService."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from btts_bot.config import LeagueConfig
from btts_bot.core.market_discovery import MarketDiscoveryService
from btts_bot.state.market_registry import MarketRegistry
from btts_bot.state.order_tracker import OrderTracker


def _make_game(
    league: str = "epl",
    home: str = "Arsenal",
    away: str = "Chelsea",
    kickoff: str = "2026-04-01T15:00:00Z",
    yes_token: str = "yes-token-id",
    no_token: str = "no-token-id",
    condition_id: str = "0xabc",
) -> dict:
    """Helper to create a game dict matching JSON structure."""
    return {
        "id": "123",
        "league": league,
        "home_team": home,
        "away_team": away,
        "kickoff_utc": kickoff,
        "polymarket": {
            "markets": [
                {
                    "condition_id": condition_id,
                    "question": f"{home} vs. {away}: Both Teams to Score",
                    "outcome_label": "Both Teams to Score",
                    "market_type": "both_teams_to_score",
                    "token_ids": [yes_token, no_token],
                }
            ]
        },
    }


def _make_service(
    games: list[dict] | None,
    leagues: list[str] | None = None,
    registry: MarketRegistry | None = None,
    order_tracker: OrderTracker | None = None,
) -> tuple[MarketDiscoveryService, MagicMock, MarketRegistry]:
    """Create a MarketDiscoveryService with a mocked GammaClient."""
    gamma = MagicMock()
    gamma.fetch_games.return_value = games

    if registry is None:
        registry = MarketRegistry()

    if leagues is None:
        leagues = ["epl"]
    league_configs = [LeagueConfig(name=abbr, abbreviation=abbr) for abbr in leagues]

    if order_tracker is None:
        order_tracker = OrderTracker()

    service = MarketDiscoveryService(gamma, registry, league_configs, order_tracker)
    return service, gamma, registry


class MarketDiscoveryServiceTests(unittest.TestCase):
    # --- AC #1: basic discovery ---

    def test_discovers_btts_markets_for_configured_leagues_only(self) -> None:
        """Markets are registered only for leagues in config, others skipped."""
        games = [_make_game(league="epl"), _make_game(league="liga", no_token="no-liga")]
        service, _, registry = _make_service(games, leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 1)
        self.assertTrue(registry.is_processed("no-token-id"))
        self.assertFalse(registry.is_processed("no-liga"))

    def test_discover_registers_correct_fields(self) -> None:
        """register() is called with the correct market fields."""
        games = [
            _make_game(
                league="epl",
                home="Arsenal",
                away="Chelsea",
                kickoff="2026-04-01T15:00:00Z",
                yes_token="yes-abc",
                no_token="no-abc",
                condition_id="0xCOND",
            )
        ]
        service, _, registry = _make_service(games, leagues=["epl"])

        service.discover_markets()

        entry = registry.get("no-abc")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.condition_id, "0xCOND")
        self.assertEqual(entry.token_ids, ["yes-abc", "no-abc"])
        self.assertEqual(entry.league, "epl")
        self.assertEqual(entry.home_team, "Arsenal")
        self.assertEqual(entry.away_team, "Chelsea")
        self.assertEqual(
            entry.kickoff_time,
            datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc),
        )

    def test_token_id_is_no_token_at_index_1(self) -> None:
        """The 'No' token (index 1) is used as the canonical token_id key."""
        games = [_make_game(yes_token="yes-token", no_token="no-token")]
        service, _, registry = _make_service(games, leagues=["epl"])

        service.discover_markets()

        self.assertTrue(registry.is_processed("no-token"))
        self.assertFalse(registry.is_processed("yes-token"))

    # --- AC #2: zero markets for a league ---

    def test_skips_games_for_non_configured_leagues(self) -> None:
        """Games for leagues not in config are silently skipped."""
        games = [_make_game(league="liga"), _make_game(league="bl")]
        service, _, registry = _make_service(games, leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)
        self.assertEqual(registry.all_markets(), [])

    def test_logs_zero_markets_for_configured_league_with_no_games(
        self,
    ) -> None:
        """Logs INFO for leagues with zero discovered markets."""
        service, _, registry = _make_service([], leagues=["epl"])

        with self.assertLogs("btts_bot.core.market_discovery", level="INFO") as log:
            count = service.discover_markets()

        self.assertEqual(count, 0)
        combined = "\n".join(log.output)
        self.assertIn("epl", combined.lower())
        self.assertIn("0", combined)

    # --- AC #3: GammaClient returns None (retries exhausted) ---

    def test_handles_gamma_client_returning_none(self) -> None:
        """When GammaClient returns None, discover_markets returns 0 (non-fatal)."""
        service, _, _ = _make_service(None)

        count = service.discover_markets()

        self.assertEqual(count, 0)

    def test_logs_error_when_gamma_client_returns_none(self) -> None:
        """Logs ERROR when GammaClient returns None."""
        service, _, _ = _make_service(None)

        with self.assertLogs("btts_bot.core.market_discovery", level="ERROR") as log:
            service.discover_markets()

        self.assertTrue(any("discovery failed" in msg.lower() for msg in log.output))

    # --- AC #4: duplicate prevention ---

    def test_skips_already_processed_markets(self) -> None:
        """Second encounter of same no_token_id is skipped (duplicate check)."""
        game = _make_game(no_token="no-dup")
        service, gamma, registry = _make_service([game, game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 1)  # Second identical game is a duplicate

    def test_skips_already_registered_token_in_registry(self) -> None:
        """Markets already in registry from a prior run are skipped."""
        registry = MarketRegistry()
        # Pre-register the same no_token_id
        registry.register(
            token_id="no-token-id",
            condition_id="0xprev",
            token_ids=["yes-token-id", "no-token-id"],
            kickoff_time=datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc),
            league="epl",
            home_team="Arsenal",
            away_team="Chelsea",
        )

        games = [_make_game(no_token="no-token-id")]
        service, _, _ = _make_service(games, leagues=["epl"], registry=registry)

        count = service.discover_markets()

        self.assertEqual(count, 0)  # Already processed, skipped

    def test_duplicate_skip_logs_debug(self) -> None:
        """Duplicate markets are logged at DEBUG level."""
        registry = MarketRegistry()
        registry.register(
            token_id="no-token-id",
            condition_id="0xprev",
            token_ids=["yes-token-id", "no-token-id"],
            kickoff_time=datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc),
            league="epl",
            home_team="Arsenal",
            away_team="Chelsea",
        )

        games = [_make_game(no_token="no-token-id")]
        service, _, _ = _make_service(games, leagues=["epl"], registry=registry)

        with self.assertLogs("btts_bot.core.market_discovery", level="DEBUG") as log:
            service.discover_markets()

        # Should have a DEBUG message about skipping
        debug_msgs = [m for m in log.output if "DEBUG" in m]
        self.assertTrue(any("already processed" in m.lower() for m in debug_msgs))

    # --- AC #5: games without BTTS market ---

    def test_skips_games_without_btts_market(self) -> None:
        """Games without a 'both_teams_to_score' market are silently skipped."""
        game_no_btts = {
            "id": "999",
            "league": "epl",
            "home_team": "A",
            "away_team": "B",
            "kickoff_utc": "2026-04-01T15:00:00Z",
            "polymarket": {
                "markets": [
                    {
                        "condition_id": "0xother",
                        "market_type": "winner",
                        "token_ids": ["yes", "no"],
                    }
                ]
            },
        }
        service, _, registry = _make_service([game_no_btts], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)

    # --- AC #6: summary log ---

    def test_logs_per_league_count_at_info(self) -> None:
        """Logs per-league discovery count at INFO level."""
        games = [
            _make_game(league="epl", no_token="no-1"),
            _make_game(league="epl", no_token="no-2"),
        ]
        service, _, _ = _make_service(games, leagues=["epl"])

        with self.assertLogs("btts_bot.core.market_discovery", level="INFO") as log:
            count = service.discover_markets()

        self.assertEqual(count, 2)
        combined = "\n".join(log.output)
        self.assertIn("2", combined)  # 2 BTTS markets found

    def test_logs_total_summary_at_info(self) -> None:
        """Logs total discovery summary at INFO level."""
        games = [_make_game()]
        service, _, _ = _make_service(games, leagues=["epl"])

        with self.assertLogs("btts_bot.core.market_discovery", level="INFO") as log:
            count = service.discover_markets()

        self.assertEqual(count, 1)
        combined = "\n".join(log.output)
        self.assertIn("complete", combined.lower())
        self.assertIn("1", combined)

    # --- Edge cases ---

    def test_league_matching_is_case_insensitive(self) -> None:
        """League abbreviation matching is case-insensitive."""
        games = [_make_game(league="EPL")]  # uppercase in data
        service, _, registry = _make_service(games, leagues=["epl"])  # lowercase in config

        count = service.discover_markets()

        self.assertEqual(count, 1)

    def test_insufficient_token_ids_skips_game(self) -> None:
        """Games whose BTTS market has fewer than 2 token_ids are skipped."""
        game = {
            "id": "99",
            "league": "epl",
            "home_team": "A",
            "away_team": "B",
            "kickoff_utc": "2026-04-01T15:00:00Z",
            "polymarket": {
                "markets": [
                    {
                        "condition_id": "0xabc",
                        "market_type": "both_teams_to_score",
                        "token_ids": ["only-one-token"],
                    }
                ]
            },
        }
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)

    def test_invalid_kickoff_utc_skips_game(self) -> None:
        """Games with invalid kickoff_utc are skipped."""
        game = _make_game(kickoff="not-a-date")
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)

    def test_missing_kickoff_utc_skips_game(self) -> None:
        """Games with missing kickoff_utc are skipped."""
        game = {
            "id": "99",
            "league": "epl",
            "home_team": "A",
            "away_team": "B",
            "polymarket": {
                "markets": [
                    {
                        "condition_id": "0xabc",
                        "market_type": "both_teams_to_score",
                        "token_ids": ["yes", "no"],
                    }
                ]
            },
        }
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)

    def test_multiple_leagues_counted_separately(self) -> None:
        """Markets across multiple leagues are tracked per league."""
        games = [
            _make_game(league="epl", no_token="no-epl"),
            _make_game(league="liga", no_token="no-liga"),
        ]
        service, _, registry = _make_service(games, leagues=["epl", "liga"])

        count = service.discover_markets()

        self.assertEqual(count, 2)
        self.assertTrue(registry.is_processed("no-epl"))
        self.assertTrue(registry.is_processed("no-liga"))

    def test_discovery_skips_non_dict_game_entries(self) -> None:
        """Non-dict entries in games list are skipped safely."""
        service, _, registry = _make_service(["bad-entry", 123, _make_game()], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 1)
        self.assertTrue(registry.is_processed("no-token-id"))

    def test_discovery_skips_market_with_missing_condition_id(self) -> None:
        """BTTS market missing condition_id is skipped without crashing."""
        game = _make_game()
        del game["polymarket"]["markets"][0]["condition_id"]
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)
        self.assertEqual(registry.all_markets(), [])

    def test_discovery_skips_invalid_token_ids_type(self) -> None:
        """BTTS market with non-list token_ids is skipped safely."""
        game = _make_game()
        game["polymarket"]["markets"][0]["token_ids"] = "yes,no"
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)
        self.assertEqual(registry.all_markets(), [])

    def test_discovery_skips_non_string_kickoff(self) -> None:
        """Non-string kickoff_utc values are skipped safely."""
        game = _make_game()
        game["kickoff_utc"] = 12345
        service, _, registry = _make_service([game], leagues=["epl"])

        count = service.discover_markets()

        self.assertEqual(count, 0)
        self.assertEqual(registry.all_markets(), [])

    def test_discovery_logs_consistent_league_summary_for_case_variants(self) -> None:
        """League summary does not produce contradictory zero/non-zero logs for case variants."""
        games = [_make_game(league="EPL", no_token="no-epl")]
        service, _, _ = _make_service(games, leagues=["epl"])

        with self.assertLogs("btts_bot.core.market_discovery", level="INFO") as log:
            count = service.discover_markets()

        self.assertEqual(count, 1)
        combined = "\n".join(log.output).lower()
        self.assertIn("discovery: epl", combined)
        self.assertNotIn("discovery: epl - 0", combined)

    # --- AC #3 (story 2.3): OrderTracker buy-order deduplication ---

    def test_skips_market_with_existing_buy_order(self) -> None:
        """Markets with an existing buy order in OrderTracker are skipped with INFO log."""
        order_tracker = OrderTracker()
        order_tracker.record_buy("no-token-id", "existing-order", 0.48, 0.50)
        service, _, registry = _make_service(
            [_make_game()], leagues=["epl"], order_tracker=order_tracker
        )

        with self.assertLogs("btts_bot.core.market_discovery", level="INFO") as log:
            count = service.discover_markets()

        self.assertEqual(count, 0)
        self.assertFalse(registry.is_processed("no-token-id"))
        self.assertTrue(any("Buy order already exists" in m for m in log.output))

    def test_skips_market_with_existing_buy_order_logs_info_not_debug(self) -> None:
        """Buy-order skip is logged at INFO level (not DEBUG)."""
        order_tracker = OrderTracker()
        order_tracker.record_buy("no-token-id", "existing-order", 0.48, 0.50)
        service, _, _ = _make_service([_make_game()], leagues=["epl"], order_tracker=order_tracker)

        with self.assertLogs("btts_bot.core.market_discovery", level="DEBUG") as log:
            service.discover_markets()

        info_msgs = [m for m in log.output if "INFO" in m]
        self.assertTrue(any("Buy order already exists" in m for m in info_msgs))

    def test_processes_market_when_no_buy_order(self) -> None:
        """Markets without existing buy orders are processed normally."""
        order_tracker = OrderTracker()  # empty — no buy orders
        service, _, registry = _make_service(
            [_make_game()], leagues=["epl"], order_tracker=order_tracker
        )

        count = service.discover_markets()

        self.assertEqual(count, 1)
        self.assertTrue(registry.is_processed("no-token-id"))

    def test_registry_check_takes_precedence_over_buy_order_check(self) -> None:
        """Registry duplicate check fires before the buy-order check (two separate guards)."""
        registry = MarketRegistry()
        registry.register(
            token_id="no-token-id",
            condition_id="0xprev",
            token_ids=["yes-token-id", "no-token-id"],
            kickoff_time=datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc),
            league="epl",
            home_team="Arsenal",
            away_team="Chelsea",
        )
        # Also has a buy order — but registry check should fire first
        order_tracker = OrderTracker()
        order_tracker.record_buy("no-token-id", "order-1", 0.48, 0.50)
        service, _, _ = _make_service(
            [_make_game()], leagues=["epl"], registry=registry, order_tracker=order_tracker
        )

        with self.assertLogs("btts_bot.core.market_discovery", level="DEBUG") as log:
            count = service.discover_markets()

        self.assertEqual(count, 0)
        debug_msgs = [m for m in log.output if "DEBUG" in m]
        self.assertTrue(any("already processed" in m.lower() for m in debug_msgs))


if __name__ == "__main__":
    unittest.main()
