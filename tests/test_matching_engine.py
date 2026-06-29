"""Unit tests for the pure CLOB matching engine.

Covers the four required scenarios — exact match, partial fill, multi-order
matching, and price-time priority — plus resting-price execution and cancels.
"""

from app.matching_engine import Order, OrderBook, Side


def buy(book: OrderBook, oid: int, qty: int, price: float, email: str = "b@uva.nl"):
    return book.add_order(Order(id=oid, email=email, side=Side.BUY, quantity=qty, price_cents=int(price * 100)))


def sell(book: OrderBook, oid: int, qty: int, price: float, email: str = "s@uva.nl"):
    return book.add_order(Order(id=oid, email=email, side=Side.SELL, quantity=qty, price_cents=int(price * 100)))


def test_exact_match():
    """A buy that exactly meets a resting sell fully fills both, no remainder."""
    book = OrderBook()
    assert sell(book, 1, 2, 50.0) == []  # rests, no trade
    trades = buy(book, 2, 2, 50.0)

    assert len(trades) == 1
    t = trades[0]
    assert t.quantity == 2
    assert t.price_cents == 5000
    assert t.buy_order_id == 2 and t.sell_order_id == 1
    # Book is now empty.
    assert book.best_bid() is None and book.best_ask() is None
    assert book.open_orders() == []


def test_partial_fill_incoming_rests():
    """A large buy partially fills a small sell, remainder rests as a bid."""
    book = OrderBook()
    sell(book, 1, 2, 50.0)
    trades = buy(book, 2, 5, 50.0)

    assert len(trades) == 1
    assert trades[0].quantity == 2
    # 3 left over should rest on the bid side at 50.00.
    assert book.best_bid() == 5000
    resting = book.open_orders()
    assert len(resting) == 1 and resting[0].remaining == 3


def test_partial_fill_resting_remains():
    """A small buy partially fills a large resting sell; the sell keeps resting."""
    book = OrderBook()
    sell(book, 1, 5, 50.0)
    trades = buy(book, 2, 2, 50.0)

    assert len(trades) == 1 and trades[0].quantity == 2
    assert book.best_ask() == 5000
    resting = book.open_orders()
    assert len(resting) == 1 and resting[0].remaining == 3


def test_multi_order_match():
    """One incoming order sweeps several resting orders across price levels."""
    book = OrderBook()
    sell(book, 1, 2, 50.0)
    sell(book, 2, 2, 51.0)
    sell(book, 3, 2, 52.0)

    # Buy 5 @ 52 should take all of 50 and 51, plus 1 from 52.
    trades = buy(book, 4, 5, 52.0)

    assert [t.quantity for t in trades] == [2, 2, 1]
    # Cheapest first (price priority): 50.00, then 51.00, then 52.00.
    assert [t.price_cents for t in trades] == [5000, 5100, 5200]
    # One ticket left resting at 52.00 on the ask side.
    assert book.best_ask() == 5200
    assert sum(o.remaining for o in book.open_orders()) == 1


def test_price_time_priority():
    """Same price → earlier order fills first (time priority)."""
    book = OrderBook()
    sell(book, 1, 2, 50.0, email="first@uva.nl")
    sell(book, 2, 2, 50.0, email="second@uva.nl")

    trades = buy(book, 3, 2, 50.0)

    assert len(trades) == 1
    # The earlier resting sell (id=1) must be the counterparty.
    assert trades[0].sell_order_id == 1
    assert trades[0].seller_email == "first@uva.nl"
    # The later one still rests.
    assert book.open_orders()[0].id == 2


def test_better_price_beats_time():
    """Price priority dominates time priority."""
    book = OrderBook()
    sell(book, 1, 1, 51.0)  # earlier but worse price
    sell(book, 2, 1, 50.0)  # later but better price

    trades = buy(book, 3, 1, 51.0)

    assert trades[0].sell_order_id == 2  # cheaper ask fills first
    assert trades[0].price_cents == 5000


def test_trade_executes_at_resting_price():
    """An aggressive buy executes at the resting sell's price, not its own."""
    book = OrderBook()
    sell(book, 1, 1, 48.0)  # resting
    trades = buy(book, 2, 1, 50.0)  # willing to pay 50

    assert trades[0].price_cents == 4800  # pays the resting 48, not 50


def test_no_cross_no_trade():
    """A bid below the best ask does not trade and rests."""
    book = OrderBook()
    sell(book, 1, 1, 50.0)
    trades = buy(book, 2, 1, 49.0)

    assert trades == []
    assert book.best_bid() == 4900 and book.best_ask() == 5000


def test_cancel_removes_resting_order():
    book = OrderBook()
    sell(book, 1, 2, 50.0)
    assert book.cancel(1) is not None
    assert book.best_ask() is None
    assert book.cancel(999) is None  # unknown id


def test_self_trade_prevention():
    """A trader's order never matches their own resting order."""
    book = OrderBook()
    sell(book, 1, 2, 50.0, email="me@uva.nl")
    # Same person sends a crossing buy — must NOT self-trade; it rests instead.
    trades = buy(book, 2, 2, 50.0, email="me@uva.nl")

    assert trades == []
    assert book.best_bid() == 5000 and book.best_ask() == 5000  # both rest
    assert len(book.open_orders()) == 2


def test_self_trade_skips_to_other_trader():
    """Own order is skipped; a different trader's order fills instead."""
    book = OrderBook()
    sell(book, 1, 1, 50.0, email="me@uva.nl")     # own, best price — skipped
    sell(book, 2, 1, 51.0, email="other@uva.nl")  # someone else, worse price
    trades = buy(book, 3, 1, 51.0, email="me@uva.nl")

    assert len(trades) == 1
    assert trades[0].sell_order_id == 2            # matched the other trader
    assert trades[0].price_cents == 5100
    # Own resting sell at 50 is untouched.
    assert book.best_ask() == 5000


def test_load_preserves_time_priority():
    """Rebuilding from persisted orders keeps sequence-based time priority."""
    src = OrderBook()
    sell(src, 1, 1, 50.0, email="first@uva.nl")
    sell(src, 2, 1, 50.0, email="second@uva.nl")

    restored = OrderBook()
    restored.load(src.open_orders())

    trades = buy(restored, 3, 1, 50.0)
    assert trades[0].sell_order_id == 1  # earliest still fills first
