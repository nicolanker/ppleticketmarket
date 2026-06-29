"""Central Limit Order Book (CLOB) matching engine.

This module is intentionally free of any web, database, or I/O concerns. It
operates purely on in-memory ``Order`` objects and produces ``Trade`` records,
which makes it deterministic and trivially unit-testable.

Design
------
* **Price-time priority.** Orders are matched best-price first; ties are broken
  by arrival sequence (the order that arrived earlier trades first).
* **Resting-price execution.** A trade executes at the price of the *resting*
  order (the one already on the book), which is standard CLOB behaviour and
  rewards the order that provided liquidity.
* **Partial fills.** An incoming order may match several resting orders and any
  unfilled remainder rests on the book.
* **Integer cents.** Prices are stored as integer cents to avoid floating-point
  rounding errors. Helpers convert to/from euros at the boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from itertools import count
from typing import Deque, Dict, Iterable, List, Optional


class Side(str, Enum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


def euros_to_cents(euros: float) -> int:
    """Convert a euro amount to integer cents (rounded to the nearest cent)."""
    return int(round(euros * 100))


def cents_to_euros(cents: int) -> float:
    """Convert integer cents back to a euro float."""
    return round(cents / 100, 2)


@dataclass
class Order:
    """A single limit order living inside the engine.

    ``remaining`` tracks the unfilled quantity and is mutated as the order is
    matched. ``sequence`` is assigned by the engine and enforces time priority.
    """

    id: int
    email: str
    side: Side
    quantity: int
    price_cents: int
    remaining: int = field(default=None)  # type: ignore[assignment]
    sequence: int = field(default=0)

    def __post_init__(self) -> None:
        if self.remaining is None:
            self.remaining = self.quantity

    @property
    def is_filled(self) -> bool:
        return self.remaining == 0


@dataclass
class Trade:
    """An executed trade between a buyer and a seller."""

    buy_order_id: int
    sell_order_id: int
    buyer_email: str
    seller_email: str
    quantity: int
    price_cents: int

    @property
    def price_euros(self) -> float:
        return cents_to_euros(self.price_cents)


class OrderBook:
    """A price-time priority order book for a single instrument.

    Bids and asks are stored as maps from price level to a FIFO queue of orders.
    The FIFO queue gives time priority within a level; scanning levels in
    best-price order gives price priority across levels.
    """

    def __init__(self) -> None:
        # price_cents -> FIFO queue of resting orders
        self.bids: Dict[int, Deque[Order]] = {}
        self.asks: Dict[int, Deque[Order]] = {}
        self._sequence = count(1)

    # -- introspection helpers ------------------------------------------------

    def best_bid(self) -> Optional[int]:
        """Highest price anyone is willing to buy at, or ``None``."""
        return max(self.bids) if self.bids else None

    def best_ask(self) -> Optional[int]:
        """Lowest price anyone is willing to sell at, or ``None``."""
        return min(self.asks) if self.asks else None

    def open_orders(self) -> List[Order]:
        """All resting orders, sorted by arrival sequence."""
        orders: List[Order] = []
        for level in self.bids.values():
            orders.extend(level)
        for level in self.asks.values():
            orders.extend(level)
        return sorted(orders, key=lambda o: o.sequence)

    # -- mutation -------------------------------------------------------------

    def add_order(self, order: Order) -> List[Trade]:
        """Insert ``order`` and match it against the book.

        Returns the list of trades generated. Any unfilled remainder of a
        marketable order is rested on the book.
        """
        order.sequence = next(self._sequence)
        if order.side == Side.BUY:
            trades = self._match(order, self.asks, take_best=min, crosses=lambda ask: ask <= order.price_cents)
            if order.remaining > 0:
                self.bids.setdefault(order.price_cents, deque()).append(order)
        else:
            trades = self._match(order, self.bids, take_best=max, crosses=lambda bid: bid >= order.price_cents)
            if order.remaining > 0:
                self.asks.setdefault(order.price_cents, deque()).append(order)
        return trades

    def _match(self, incoming: Order, opposite: Dict[int, Deque[Order]], take_best, crosses) -> List[Trade]:
        """Walk the opposite side of the book filling ``incoming`` while it crosses.

        An incoming order matches *every* crossing resting order, best-price then
        time first, until it no longer crosses. This guarantees the resting book
        is never left crossed — so the bid is always below the ask and the spread
        can never be negative.
        """
        trades: List[Trade] = []
        while incoming.remaining > 0 and opposite:
            best_price = take_best(opposite)
            if not crosses(best_price):
                break
            level = opposite[best_price]
            resting = level[0]
            qty = min(incoming.remaining, resting.remaining)

            if incoming.side == Side.BUY:
                buyer, seller = incoming, resting
            else:
                buyer, seller = resting, incoming

            # Trades always execute at the resting order's price.
            trades.append(
                Trade(
                    buy_order_id=buyer.id,
                    sell_order_id=seller.id,
                    buyer_email=buyer.email,
                    seller_email=seller.email,
                    quantity=qty,
                    price_cents=resting.price_cents,
                )
            )

            incoming.remaining -= qty
            resting.remaining -= qty
            if resting.remaining == 0:
                level.popleft()
                if not level:
                    del opposite[best_price]
        return trades

    def cancel(self, order_id: int) -> Optional[Order]:
        """Remove a resting order by id. Returns the order if found."""
        for book in (self.bids, self.asks):
            for price, level in list(book.items()):
                for existing in list(level):
                    if existing.id == order_id:
                        level.remove(existing)
                        if not level:
                            del book[price]
                        return existing
        return None

    def load(self, orders: Iterable[Order]) -> None:
        """Rebuild the book from persisted open orders without matching.

        Used on startup to restore engine state from the database. Orders are
        assumed to be already non-crossing (they were resting when persisted)
        and are inserted in sequence order to preserve time priority.
        """
        for order in sorted(orders, key=lambda o: o.sequence):
            self._sequence = count(order.sequence + 1)
            book = self.bids if order.side == Side.BUY else self.asks
            book.setdefault(order.price_cents, deque()).append(order)
