"""Order tracker for monitoring active buy and sell orders."""

from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class BuyOrderRecord:
    """Record of a placed buy order."""

    token_id: str
    order_id: str
    buy_price: float
    sell_price: float
    active: bool = True


@dataclasses.dataclass
class SellOrderRecord:
    """Record of a placed sell order."""

    token_id: str
    order_id: str
    sell_price: float
    sell_size: float


class OrderTracker:
    """Tracks buy and sell orders keyed by token_id.

    Pure data manager — holds state and answers queries.
    Never initiates API calls.
    """

    def __init__(self) -> None:
        self._buy_orders: dict[str, BuyOrderRecord] = {}
        self._sell_orders: dict[str, SellOrderRecord] = {}

    def record_buy(self, token_id: str, order_id: str, buy_price: float, sell_price: float) -> None:
        """Record a buy order for a token."""
        self._buy_orders[token_id] = BuyOrderRecord(
            token_id=token_id,
            order_id=order_id,
            buy_price=buy_price,
            sell_price=sell_price,
        )
        logger.info(
            "Buy order recorded: token=%s order=%s price=%.4f",
            token_id,
            order_id,
            buy_price,
        )

    def has_buy_order(self, token_id: str) -> bool:
        """Check if a buy order exists for the given token."""
        return token_id in self._buy_orders

    def get_buy_order(self, token_id: str) -> BuyOrderRecord | None:
        """Get the buy order record for a token, or None if not found."""
        return self._buy_orders.get(token_id)

    def mark_inactive(self, token_id: str) -> None:
        """Mark a buy order as inactive (fully filled or expired)."""
        record = self._buy_orders.get(token_id)
        if record is not None:
            record.active = False
            logger.info("Buy order marked inactive: token=%s order=%s", token_id, record.order_id)

    def get_active_buy_orders(self) -> list[BuyOrderRecord]:
        """Return all buy order records where active is True."""
        return [r for r in self._buy_orders.values() if r.active]

    def has_sell_order(self, token_id: str) -> bool:
        """Check if a sell order exists for the given token."""
        return token_id in self._sell_orders

    def record_sell(
        self, token_id: str, order_id: str, sell_price: float, sell_size: float
    ) -> None:
        """Record a sell order for a token."""
        self._sell_orders[token_id] = SellOrderRecord(
            token_id=token_id,
            order_id=order_id,
            sell_price=sell_price,
            sell_size=sell_size,
        )
        logger.info(
            "Sell order recorded: token=%s order=%s price=%.4f size=%.2f",
            token_id,
            order_id,
            sell_price,
            sell_size,
        )

    def get_sell_order(self, token_id: str) -> SellOrderRecord | None:
        """Get the sell order record for a token, or None if not found."""
        return self._sell_orders.get(token_id)

    def remove_sell_order(self, token_id: str) -> None:
        """Remove the sell order record for a token (used before cancel-and-replace)."""
        self._sell_orders.pop(token_id, None)

    def get_order(self, token_id: str) -> BuyOrderRecord | None:
        """Get buy order info for a token. Alias for get_buy_order."""
        return self.get_buy_order(token_id)
