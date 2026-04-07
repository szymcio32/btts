"""
Game lifecycle state machine for BTTS markets.
Implemented in Story 1.6.
"""

import enum
import logging
import threading

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
    GameState.BUY_PLACED: frozenset(
        {
            GameState.FILLING,
            GameState.SKIPPED,
            GameState.EXPIRED,
            GameState.PRE_KICKOFF,
            GameState.GAME_STARTED,  # pre-kickoff failed, game started with unfilled/partially-filled buy
            GameState.DONE,  # pre-kickoff failed, game started with no fills
        }
    ),
    GameState.FILLING: frozenset(
        {
            GameState.SELL_PLACED,
            GameState.PRE_KICKOFF,
            GameState.EXPIRED,
            GameState.GAME_STARTED,  # pre-kickoff failed, game started with fills but no sell
            GameState.DONE,  # pre-kickoff failed, game started with no fills (edge case)
        }
    ),
    GameState.SELL_PLACED: frozenset(
        {
            GameState.PRE_KICKOFF,
            GameState.DONE,
            GameState.GAME_STARTED,  # Polymarket cancelled sell at game start when pre-kickoff failed
        }
    ),
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
        self._lock = threading.Lock()

    @property
    def state(self) -> GameState:
        with self._lock:
            return self._state

    def transition(self, new_state: GameState) -> None:
        with self._lock:
            if not isinstance(new_state, GameState):
                raise InvalidTransitionError(
                    f"Invalid transition: {self._state.value} → {new_state!r}"
                )
            allowed = VALID_TRANSITIONS.get(self._state, frozenset())
            if new_state not in allowed:
                raise InvalidTransitionError(
                    f"Invalid transition: {self._state.value} → {new_state.value}"
                )
            logger.info(
                "GameLifecycle [%s]: %s → %s",
                self.token_id,
                self._state.value,
                new_state.value,
            )
            self._state = new_state
