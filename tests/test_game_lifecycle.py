"""Tests for GameLifecycle state machine (Story 1.6)."""

import logging

import pytest

from btts_bot.core.game_lifecycle import (
    GameLifecycle,
    GameState,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)


def test_initial_state():
    gl = GameLifecycle("token-123")
    assert gl.state == GameState.DISCOVERED


def test_token_id_stored():
    gl = GameLifecycle("token-abc")
    assert gl.token_id == "token-abc"


def test_valid_transition_discovered_to_analysed():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.ANALYSED)
    assert gl.state == GameState.ANALYSED


def test_valid_transition_discovered_to_skipped():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.SKIPPED)
    assert gl.state == GameState.SKIPPED


def test_valid_transition_full_happy_path():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.ANALYSED)
    gl.transition(GameState.BUY_PLACED)
    gl.transition(GameState.FILLING)
    gl.transition(GameState.SELL_PLACED)
    gl.transition(GameState.PRE_KICKOFF)
    gl.transition(GameState.GAME_STARTED)
    gl.transition(GameState.RECOVERY_COMPLETE)
    gl.transition(GameState.DONE)
    assert gl.state == GameState.DONE


def test_invalid_transition_raises():
    gl = GameLifecycle("token-123")
    with pytest.raises(InvalidTransitionError, match="DISCOVERED.*DONE"):
        gl.transition(GameState.DONE)


def test_invalid_transition_discovered_to_buy_placed():
    gl = GameLifecycle("token-123")
    with pytest.raises(InvalidTransitionError, match="DISCOVERED.*BUY_PLACED"):
        gl.transition(GameState.BUY_PLACED)


def test_terminal_state_done_rejects_all():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.ANALYSED)
    gl.transition(GameState.BUY_PLACED)
    gl.transition(GameState.FILLING)
    gl.transition(GameState.SELL_PLACED)
    gl.transition(GameState.DONE)
    with pytest.raises(InvalidTransitionError):
        gl.transition(GameState.DISCOVERED)


def test_terminal_state_skipped_rejects_all():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.SKIPPED)
    with pytest.raises(InvalidTransitionError):
        gl.transition(GameState.ANALYSED)


def test_terminal_state_expired_rejects_all():
    gl = GameLifecycle("token-123")
    gl.transition(GameState.ANALYSED)
    gl.transition(GameState.BUY_PLACED)
    gl.transition(GameState.EXPIRED)
    with pytest.raises(InvalidTransitionError):
        gl.transition(GameState.FILLING)


def test_transition_logs_info(caplog):
    with caplog.at_level(logging.INFO, logger="btts_bot.core.game_lifecycle"):
        gl = GameLifecycle("token-abc")
        gl.transition(GameState.ANALYSED)
    assert "DISCOVERED" in caplog.text
    assert "ANALYSED" in caplog.text


def test_transition_log_includes_token_id(caplog):
    with caplog.at_level(logging.INFO, logger="btts_bot.core.game_lifecycle"):
        gl = GameLifecycle("my-special-token")
        gl.transition(GameState.SKIPPED)
    assert "my-special-token" in caplog.text


def test_all_states_defined():
    expected = {
        "DISCOVERED",
        "ANALYSED",
        "BUY_PLACED",
        "FILLING",
        "SELL_PLACED",
        "PRE_KICKOFF",
        "GAME_STARTED",
        "RECOVERY_COMPLETE",
        "DONE",
        "SKIPPED",
        "EXPIRED",
    }
    actual = {s.value for s in GameState}
    assert actual == expected


def test_all_states_have_transition_entry():
    for state in GameState:
        assert state in VALID_TRANSITIONS, f"{state} missing from VALID_TRANSITIONS"


def test_terminal_states_have_empty_transitions():
    for terminal in (GameState.DONE, GameState.SKIPPED, GameState.EXPIRED):
        assert VALID_TRANSITIONS[terminal] == frozenset()


def test_invalid_transition_error_message_format():
    gl = GameLifecycle("token-123")
    with pytest.raises(InvalidTransitionError) as exc_info:
        gl.transition(GameState.DONE)
    msg = str(exc_info.value)
    assert "DISCOVERED" in msg
    assert "DONE" in msg


def test_state_cannot_be_directly_assigned():
    gl = GameLifecycle("token-123")
    with pytest.raises(AttributeError):
        gl.state = GameState.DONE


def test_invalid_new_state_type_raises_invalid_transition_error():
    gl = GameLifecycle("token-123")
    with pytest.raises(InvalidTransitionError, match="DISCOVERED"):
        gl.transition("DONE")  # type: ignore[arg-type]
