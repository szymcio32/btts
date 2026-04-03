"""Tests for btts_bot.state.position_tracker — PositionTracker."""

from btts_bot.state.position_tracker import PositionTracker


def test_accumulate_adds_fills():
    """accumulate() adds fill amounts to the running total."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    tracker.accumulate("token-1", 5.0)
    assert tracker.get_accumulated_fills("token-1") == 15.0


def test_get_accumulated_fills_default():
    """get_accumulated_fills() returns 0.0 for unknown token_id."""
    tracker = PositionTracker()
    assert tracker.get_accumulated_fills("unknown") == 0.0


def test_has_reached_threshold_true():
    """has_reached_threshold() returns True when accumulated >= min_size."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    assert tracker.has_reached_threshold("token-1", 5.0) is True


def test_has_reached_threshold_true_exact():
    """has_reached_threshold() returns True when accumulated == min_size (boundary)."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 5.0)
    assert tracker.has_reached_threshold("token-1", 5.0) is True


def test_has_reached_threshold_false():
    """has_reached_threshold() returns False when accumulated < min_size."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 3.0)
    assert tracker.has_reached_threshold("token-1", 5.0) is False


def test_has_reached_threshold_unknown_token_false():
    """has_reached_threshold() returns False for unknown token_id."""
    tracker = PositionTracker()
    assert tracker.has_reached_threshold("unknown", 1.0) is False


def test_multiple_accumulate_calls_sum_correctly():
    """Multiple accumulate() calls sum correctly."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    tracker.accumulate("token-1", 5.0)
    tracker.accumulate("token-1", 3.5)
    assert tracker.get_accumulated_fills("token-1") == 18.5


def test_separate_tokens_tracked_independently():
    """Different token_ids are tracked independently."""
    tracker = PositionTracker()
    tracker.accumulate("token-1", 10.0)
    tracker.accumulate("token-2", 20.0)
    assert tracker.get_accumulated_fills("token-1") == 10.0
    assert tracker.get_accumulated_fills("token-2") == 20.0
