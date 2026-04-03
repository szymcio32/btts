"""Tests for OrderTracker."""

import unittest

from btts_bot.state.order_tracker import BuyOrderRecord, OrderTracker


class OrderTrackerTests(unittest.TestCase):
    def test_has_buy_order_returns_false_for_unknown(self) -> None:
        """has_buy_order() returns False for an unknown token_id."""
        tracker = OrderTracker()
        assert tracker.has_buy_order("unknown-token") is False

    def test_has_buy_order_returns_true_after_record(self) -> None:
        """has_buy_order() returns True after record_buy() is called."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        assert tracker.has_buy_order("token-1") is True

    def test_get_buy_order_returns_none_for_unknown(self) -> None:
        """get_buy_order() returns None for an unknown token_id."""
        tracker = OrderTracker()
        assert tracker.get_buy_order("unknown-token") is None

    def test_get_buy_order_returns_record_after_record(self) -> None:
        """get_buy_order() returns a BuyOrderRecord after record_buy()."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        record = tracker.get_buy_order("token-1")
        assert isinstance(record, BuyOrderRecord)
        assert record.token_id == "token-1"
        assert record.order_id == "order-1"
        assert record.buy_price == 0.48
        assert record.sell_price == 0.50

    def test_get_buy_order_has_active_true_by_default(self) -> None:
        """get_buy_order() returns a record with active=True by default."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        record = tracker.get_buy_order("token-1")
        assert record is not None
        assert record.active is True

    def test_has_sell_order_returns_false_initially(self) -> None:
        """has_sell_order() returns False for any token_id (stub behavior)."""
        tracker = OrderTracker()
        assert tracker.has_sell_order("token-1") is False

    def test_record_buy_overwrites_existing(self) -> None:
        """record_buy() overwrites an existing buy order for the same token_id."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.record_buy("token-1", "order-2", 0.50, 0.52)
        record = tracker.get_buy_order("token-1")
        assert record is not None
        assert record.order_id == "order-2"
        assert record.buy_price == 0.50

    def test_get_order_alias_returns_buy_order(self) -> None:
        """get_order() is an alias for get_buy_order()."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        record = tracker.get_order("token-1")
        assert record is not None
        assert record.token_id == "token-1"

    def test_has_sell_order_returns_true_after_record_sell(self) -> None:
        """has_sell_order() returns True after record_sell() is called."""
        tracker = OrderTracker()
        tracker.record_sell("token-1", "sell-order-1")
        assert tracker.has_sell_order("token-1") is True

    def test_independent_tokens_tracked_separately(self) -> None:
        """Multiple tokens are tracked independently."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.record_buy("token-2", "order-2", 0.52, 0.54)
        assert tracker.has_buy_order("token-1") is True
        assert tracker.has_buy_order("token-2") is True
        assert tracker.has_buy_order("token-3") is False

    def test_mark_inactive_sets_active_false(self) -> None:
        """mark_inactive() sets active=False on the buy order record."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.mark_inactive("token-1")
        record = tracker.get_buy_order("token-1")
        assert record is not None
        assert record.active is False

    def test_mark_inactive_unknown_token_no_crash(self) -> None:
        """mark_inactive() on unknown token_id does not crash."""
        tracker = OrderTracker()
        tracker.mark_inactive("unknown-token")  # Should not raise

    def test_get_active_buy_orders_returns_all_active(self) -> None:
        """get_active_buy_orders() returns all records where active=True."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.record_buy("token-2", "order-2", 0.49, 0.51)
        active = tracker.get_active_buy_orders()
        assert len(active) == 2

    def test_get_active_buy_orders_excludes_inactive(self) -> None:
        """get_active_buy_orders() excludes records where active=False."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.record_buy("token-2", "order-2", 0.49, 0.51)
        tracker.mark_inactive("token-1")
        active = tracker.get_active_buy_orders()
        assert len(active) == 1
        assert active[0].token_id == "token-2"

    def test_get_active_buy_orders_empty_when_none(self) -> None:
        """get_active_buy_orders() returns empty list when no orders registered."""
        tracker = OrderTracker()
        assert tracker.get_active_buy_orders() == []

    def test_get_active_buy_orders_empty_when_all_inactive(self) -> None:
        """get_active_buy_orders() returns empty list when all orders are inactive."""
        tracker = OrderTracker()
        tracker.record_buy("token-1", "order-1", 0.48, 0.50)
        tracker.mark_inactive("token-1")
        assert tracker.get_active_buy_orders() == []


if __name__ == "__main__":
    unittest.main()
