"""Tests for MarketRegistry (Story 1.6)."""

import logging
from datetime import datetime, timezone

import pytest

from btts_bot.core.game_lifecycle import GameState
from btts_bot.state.market_registry import MarketEntry, MarketRegistry

KICKOFF = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)


def _make_registry() -> MarketRegistry:
    return MarketRegistry()


def _register_one(reg: MarketRegistry, token_id: str = "tok-1") -> MarketEntry:
    return reg.register(
        token_id,
        "cond-1",
        [token_id, "tok-other"],
        KICKOFF,
        "EPL",
        "Arsenal",
        "Chelsea",
    )


# --- register() ---


def test_register_creates_entry():
    reg = _make_registry()
    entry = _register_one(reg)
    assert entry.token_id == "tok-1"
    assert entry.condition_id == "cond-1"
    assert entry.token_ids == ["tok-1", "tok-other"]
    assert entry.kickoff_time == KICKOFF
    assert entry.league == "EPL"
    assert entry.home_team == "Arsenal"
    assert entry.away_team == "Chelsea"


def test_register_lifecycle_starts_discovered():
    reg = _make_registry()
    entry = _register_one(reg)
    assert entry.lifecycle.state == GameState.DISCOVERED


def test_register_lifecycle_token_id_matches():
    reg = _make_registry()
    entry = _register_one(reg, "special-token")
    assert entry.lifecycle.token_id == "special-token"


def test_register_returns_market_entry_instance():
    reg = _make_registry()
    entry = _register_one(reg)
    assert isinstance(entry, MarketEntry)


# --- get() ---


def test_get_returns_registered_entry():
    reg = _make_registry()
    _register_one(reg, "tok-1")
    result = reg.get("tok-1")
    assert result is not None
    assert result.token_id == "tok-1"


def test_get_returns_none_for_unknown():
    reg = _make_registry()
    assert reg.get("not-registered") is None


def test_get_returns_same_object_as_register():
    reg = _make_registry()
    entry = _register_one(reg, "tok-1")
    assert reg.get("tok-1") is entry


# --- is_processed() ---


def test_is_processed_true_for_registered():
    reg = _make_registry()
    _register_one(reg, "tok-1")
    assert reg.is_processed("tok-1") is True


def test_is_processed_false_for_unknown():
    reg = _make_registry()
    assert reg.is_processed("not-registered") is False


# --- all_markets() ---


def test_all_markets_empty_initially():
    reg = _make_registry()
    assert reg.all_markets() == []


def test_all_markets_returns_all_entries():
    reg = _make_registry()
    _register_one(reg, "tok-1")
    reg.register("tok-2", "cond-2", ["tok-2"], KICKOFF, "LIGA", "Real Madrid", "Atletico")
    markets = reg.all_markets()
    assert len(markets) == 2
    token_ids = {m.token_id for m in markets}
    assert token_ids == {"tok-1", "tok-2"}


def test_all_markets_returns_list_copy():
    reg = _make_registry()
    _register_one(reg, "tok-1")
    result = reg.all_markets()
    result.clear()
    assert len(reg.all_markets()) == 1


# --- logging ---


def test_register_logs_info(caplog):
    reg = _make_registry()
    with caplog.at_level(logging.INFO, logger="btts_bot.state.market_registry"):
        reg.register("tok-1", "cond-1", ["tok-1"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    assert "Arsenal" in caplog.text
    assert "Chelsea" in caplog.text
    assert "tok-1" in caplog.text


def test_register_logs_league_and_kickoff(caplog):
    reg = _make_registry()
    with caplog.at_level(logging.INFO, logger="btts_bot.state.market_registry"):
        reg.register("tok-1", "cond-1", ["tok-1"], KICKOFF, "EPL", "Arsenal", "Chelsea")
    assert "EPL" in caplog.text
    assert "2026-04-01" in caplog.text


def test_register_duplicate_token_id_raises_value_error():
    reg = _make_registry()
    _register_one(reg, "tok-1")
    with pytest.raises(ValueError, match="tok-1"):
        _register_one(reg, "tok-1")


def test_register_defensively_copies_token_ids():
    reg = _make_registry()
    ids = ["tok-1", "tok-2"]
    entry = reg.register(
        "tok-1",
        "cond-1",
        ids,
        KICKOFF,
        "EPL",
        "Arsenal",
        "Chelsea",
    )
    ids.append("tok-3")
    assert entry.token_ids == ["tok-1", "tok-2"]
