"""Thread-safety tests for state managers and OrderTracker atomic methods (AC #4)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from btts_bot.core.game_lifecycle import GameLifecycle, GameState, InvalidTransitionError
from btts_bot.state.order_tracker import OrderTracker
from btts_bot.state.position_tracker import PositionTracker


# ---------------------------------------------------------------------------
# OrderTracker thread-safety
# ---------------------------------------------------------------------------


def test_order_tracker_concurrent_record_and_has_sell_no_data_corruption() -> None:
    """Concurrent record_sell + has_sell_order on OrderTracker — no data corruption."""
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    errors: list[Exception] = []

    def writer(i: int) -> None:
        try:
            tracker.record_sell("token-1", f"sell-{i}", 0.48, float(i))
        except Exception as e:
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(50):
                # Should never raise — just return True or False
                tracker.has_sell_order("token-1")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    threads += [threading.Thread(target=reader) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"Thread errors: {errors}"
    # Final state must be consistent — sell order for token-1 exists
    assert tracker.has_sell_order("token-1")


def test_order_tracker_record_sell_if_absent_only_one_thread_wins() -> None:
    """record_sell_if_absent atomicity: two threads race; exactly one wins (returns True)."""
    tracker = OrderTracker()
    results: list[bool] = []
    lock = threading.Lock()

    def try_record(i: int) -> None:
        result = tracker.record_sell_if_absent("token-1", f"sell-{i}", 0.48, 10.0)
        with lock:
            results.append(result)

    # Start 10 threads all racing to record the first sell for token-1
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_record, i) for i in range(10)]
        for f in futures:
            f.result()

    # Exactly one thread should have won
    assert results.count(True) == 1
    assert results.count(False) == 9

    # The sell order must exist in the tracker
    sell = tracker.get_sell_order("token-1")
    assert sell is not None


def test_order_tracker_concurrent_mark_inactive_no_corruption() -> None:
    """Concurrent mark_inactive calls do not corrupt buy order records."""
    tracker = OrderTracker()
    tracker.record_buy("token-1", "buy-order-1", 0.48, 0.52)
    errors: list[Exception] = []

    def mark_inactive() -> None:
        try:
            tracker.mark_inactive("token-1")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=mark_inactive) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    buy = tracker.get_buy_order("token-1")
    assert buy is not None
    assert buy.active is False


# ---------------------------------------------------------------------------
# PositionTracker thread-safety
# ---------------------------------------------------------------------------


def test_position_tracker_concurrent_accumulate_no_lost_updates() -> None:
    """Concurrent accumulate() calls on PositionTracker — no lost updates."""
    tracker = PositionTracker()
    num_threads = 50
    fill_per_thread = 1.0

    errors: list[Exception] = []

    def accumulate_fill() -> None:
        try:
            tracker.accumulate("token-1", fill_per_thread)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=accumulate_fill) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    total = tracker.get_accumulated_fills("token-1")
    assert total == pytest.approx(num_threads * fill_per_thread)


# ---------------------------------------------------------------------------
# GameLifecycle thread-safety
# ---------------------------------------------------------------------------


def test_game_lifecycle_concurrent_state_reads_are_consistent() -> None:
    """Concurrent state reads from GameLifecycle never raise or return garbage."""
    lifecycle = GameLifecycle("token-1")
    errors: list[Exception] = []

    def read_state() -> None:
        try:
            for _ in range(100):
                state = lifecycle.state
                # state must always be a valid GameState
                assert isinstance(state, GameState)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=read_state) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors


def test_game_lifecycle_concurrent_transition_no_invalid_state() -> None:
    """Concurrent transition() calls — only valid transitions succeed, no corruption."""
    lifecycle = GameLifecycle("token-1")
    # Advance to BUY_PLACED so threads can race on the FILLING/SKIPPED/etc transitions
    lifecycle.transition(GameState.ANALYSED)
    lifecycle.transition(GameState.BUY_PLACED)

    successes: list[GameState] = []
    lock = threading.Lock()

    def try_transition_to_filling() -> None:
        try:
            lifecycle.transition(GameState.FILLING)
            with lock:
                successes.append(GameState.FILLING)
        except InvalidTransitionError:
            pass  # Expected when another thread already transitioned

    threads = [threading.Thread(target=try_transition_to_filling) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # Exactly one transition to FILLING should have succeeded
    assert len(successes) == 1
    assert lifecycle.state == GameState.FILLING
