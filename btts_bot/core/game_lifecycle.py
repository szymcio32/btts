"""
Game lifecycle state machine for BTTS markets.
Implemented in Story 1.6.
"""

import enum
import logging

logger = logging.getLogger(__name__)


class GameState(enum.Enum):
    DISCOVERED = "DISCOVERED"
    ANALYSED = "ANALYSED"
    BUY_PLACED = "BUY_PLACED"
    FILLING = "FILLING"
    SELL_PLACED = "SELL_PLACED"
    PRE_KICKOFF = "PRE_KICKOFF"
    GAME_STARTED = "GAME_STARTED"
    RECOVERY_COMPLETE = "RECOVERY_COMPLETE"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"


class InvalidTransitionError(Exception):
    pass


VALID_TRANSITIONS: dict[GameState, frozenset[GameState]] = {
    GameState.DISCOVERED: frozenset({GameState.ANALYSED, GameState.SKIPPED}),
    GameState.ANALYSED: frozenset({GameState.BUY_PLACED, GameState.SKIPPED}),
    GameState.BUY_PLACED: frozenset({GameState.FILLING, GameState.SKIPPED, GameState.EXPIRED}),
    GameState.FILLING: frozenset({GameState.SELL_PLACED, GameState.PRE_KICKOFF, GameState.EXPIRED}),
    GameState.SELL_PLACED: frozenset({GameState.PRE_KICKOFF, GameState.DONE}),
    GameState.PRE_KICKOFF: frozenset({GameState.GAME_STARTED, GameState.DONE}),
    GameState.GAME_STARTED: frozenset({GameState.RECOVERY_COMPLETE, GameState.DONE}),
    GameState.RECOVERY_COMPLETE: frozenset({GameState.DONE}),
    GameState.DONE: frozenset(),  # terminal
    GameState.SKIPPED: frozenset(),  # terminal
    GameState.EXPIRED: frozenset(),  # terminal
}


class GameLifecycle:
    def __init__(self, token_id: str) -> None:
        self.token_id = token_id
        self._state = GameState.DISCOVERED

    @property
    def state(self) -> GameState:
        return self._state

    def transition(self, new_state: GameState) -> None:
        if not isinstance(new_state, GameState):
            raise InvalidTransitionError(f"Invalid transition: {self.state.value} → {new_state!r}")
        allowed = VALID_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Invalid transition: {self.state.value} → {new_state.value}"
            )
        logger.info(
            "GameLifecycle [%s]: %s → %s",
            self.token_id,
            self.state.value,
            new_state.value,
        )
        self._state = new_state
