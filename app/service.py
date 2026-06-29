"""Exchange service — the orchestration layer between the web app and the engine.

Responsibilities:
* Serialize order submission (one matching pass at a time) with an asyncio lock.
* Persist orders and trades to the database (durable audit log).
* Keep the in-memory order book in sync and rebuild it on startup.
* Trigger trade notifications and WebSocket broadcasts.

The pure matching logic lives in :mod:`app.matching_engine`; this module wires
it to I/O.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models, notifications
from .database import SessionLocal
from .matching_engine import Order as EngineOrder
from .matching_engine import OrderBook, Side, Trade, cents_to_euros, euros_to_cents
from .models import OrderStatus
from .schemas import (
    BookSide,
    MarketStats,
    OrderCreate,
    OrderOut,
    PriceLevel,
    PublicOrderOut,
    Snapshot,
    TradeOut,
)
from .websocket_manager import ConnectionManager

logger = logging.getLogger("market.service")

RECENT_TRADES_LIMIT = 100


class ExchangeService:
    def __init__(self) -> None:
        self.book = OrderBook()
        self.ws = ConnectionManager()
        self._lock = asyncio.Lock()

    # -- lifecycle ------------------------------------------------------------

    def rebuild_from_db(self) -> None:
        """Restore the in-memory book from open/partial orders in the database."""
        with SessionLocal() as db:
            rows = db.scalars(
                select(models.Order)
                .where(models.Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]))
                .order_by(models.Order.sequence)
            ).all()
            engine_orders = [
                EngineOrder(
                    id=row.id,
                    email=row.email,
                    side=Side(row.side),
                    quantity=row.quantity,
                    price_cents=row.price_cents,
                    remaining=row.remaining,
                    sequence=row.sequence,
                )
                for row in rows
            ]
            self.book.load(engine_orders)
        logger.info("Rebuilt order book with %d resting orders", len(self.book.open_orders()))

    # -- commands -------------------------------------------------------------

    async def submit_order(self, payload: OrderCreate) -> Tuple[models.Order, List[models.Trade]]:
        """Validate, persist, match, notify, and broadcast a new order."""
        async with self._lock:
            db_order, db_trades, engine_trades = await asyncio.to_thread(self._submit_sync, payload)

        if engine_trades:
            await notifications.notify_trades(engine_trades)
        await self.broadcast_snapshot()
        return db_order, db_trades

    def _submit_sync(self, payload: OrderCreate) -> Tuple[models.Order, List[models.Trade], List[Trade]]:
        """Synchronous DB + engine work, run in a worker thread under the lock."""
        with SessionLocal() as db:
            db_order = models.Order(
                email=payload.email,
                side=payload.side.value,
                quantity=payload.quantity,
                remaining=payload.quantity,
                price_cents=euros_to_cents(payload.price),
                status=OrderStatus.OPEN,
            )
            db.add(db_order)
            db.flush()  # assign primary key

            engine_order = EngineOrder(
                id=db_order.id,
                email=db_order.email,
                side=Side(db_order.side),
                quantity=db_order.quantity,
                price_cents=db_order.price_cents,
            )
            trades = self.book.add_order(engine_order)
            db_order.sequence = engine_order.sequence

            # Aggregate filled quantity per affected order id.
            filled: dict[int, int] = defaultdict(int)
            for t in trades:
                filled[t.buy_order_id] += t.quantity
                filled[t.sell_order_id] += t.quantity

            for order_id, qty in filled.items():
                order = db.get(models.Order, order_id)
                order.remaining -= qty
                order.status = (
                    OrderStatus.FILLED
                    if order.remaining == 0
                    else OrderStatus.PARTIAL
                )

            db_trades = [
                models.Trade(
                    buy_order_id=t.buy_order_id,
                    sell_order_id=t.sell_order_id,
                    buyer_email=t.buyer_email,
                    seller_email=t.seller_email,
                    quantity=t.quantity,
                    price_cents=t.price_cents,
                )
                for t in trades
            ]
            db.add_all(db_trades)
            db.commit()

            for obj in [db_order, *db_trades]:
                db.refresh(obj)
            db.expunge_all()
            return db_order, db_trades, trades

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel a resting order. Returns True if it was open and removed."""
        async with self._lock:
            removed = await asyncio.to_thread(self._cancel_sync, order_id)
        if removed:
            await self.broadcast_snapshot()
        return removed

    def _cancel_sync(self, order_id: int) -> bool:
        with SessionLocal() as db:
            order = db.get(models.Order, order_id)
            if order is None or order.status not in (OrderStatus.OPEN, OrderStatus.PARTIAL):
                return False
            self.book.cancel(order_id)
            order.status = OrderStatus.CANCELLED
            db.commit()
            return True

    # -- queries / snapshot ---------------------------------------------------

    def build_snapshot(self) -> Snapshot:
        return self._snapshot_sync()

    def _snapshot_sync(self) -> Snapshot:
        with SessionLocal() as db:
            book = self._book_side()

            trade_rows = db.scalars(
                select(models.Trade).order_by(models.Trade.id.desc()).limit(RECENT_TRADES_LIMIT)
            ).all()
            recent_trades = [self._trade_out(t) for t in trade_rows]

            open_rows = db.scalars(
                select(models.Order)
                .where(models.Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]))
                .order_by(models.Order.sequence.desc())
            ).all()
            open_orders = [self._public_order_out(o) for o in open_rows]

            total_trades = db.scalar(select(func.count(models.Trade.id))) or 0
            total_volume = db.scalar(select(func.coalesce(func.sum(models.Trade.quantity), 0))) or 0
            last_price = recent_trades[0].price if recent_trades else None

            best_bid_c = self.book.best_bid()
            best_ask_c = self.book.best_ask()
            best_bid = cents_to_euros(best_bid_c) if best_bid_c is not None else None
            best_ask = cents_to_euros(best_ask_c) if best_ask_c is not None else None
            spread = (
                round(best_ask - best_bid, 2)
                if best_bid is not None and best_ask is not None
                else None
            )

            stats = MarketStats(
                last_price=last_price,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                total_trades=total_trades,
                total_volume=total_volume,
                open_orders=len(open_orders),
            )
            return Snapshot(book=book, recent_trades=recent_trades, open_orders=open_orders, stats=stats)

    def _book_side(self) -> BookSide:
        def levels(book: dict, reverse: bool) -> List[PriceLevel]:
            out = []
            for price in sorted(book.keys(), reverse=reverse):
                level = book[price]
                out.append(
                    PriceLevel(
                        price=cents_to_euros(price),
                        quantity=sum(o.remaining for o in level),
                        orders=len(level),
                    )
                )
            return out

        return BookSide(
            bids=levels(self.book.bids, reverse=True),  # highest bid first
            asks=levels(self.book.asks, reverse=False),  # lowest ask first
        )

    @staticmethod
    def _order_out(o: models.Order) -> OrderOut:
        return OrderOut(
            id=o.id,
            email=o.email,
            side=Side(o.side),
            quantity=o.quantity,
            remaining=o.remaining,
            filled=o.filled,
            price=cents_to_euros(o.price_cents),
            status=o.status,
            created_at=o.created_at,
        )

    @staticmethod
    def _public_order_out(o: models.Order) -> PublicOrderOut:
        """Anonymised order (no email) for the public book."""
        return PublicOrderOut(
            id=o.id,
            side=Side(o.side),
            quantity=o.quantity,
            remaining=o.remaining,
            filled=o.filled,
            price=cents_to_euros(o.price_cents),
            status=o.status,
            created_at=o.created_at,
        )

    @staticmethod
    def _trade_out(t: models.Trade) -> TradeOut:
        return TradeOut(
            id=t.id,
            buy_order_id=t.buy_order_id,
            sell_order_id=t.sell_order_id,
            quantity=t.quantity,
            price=cents_to_euros(t.price_cents),
            created_at=t.created_at,
        )

    # -- broadcasting ---------------------------------------------------------

    async def broadcast_snapshot(self) -> None:
        snapshot = await asyncio.to_thread(self.build_snapshot)
        await self.ws.broadcast({"type": "snapshot", "data": snapshot.model_dump(mode="json")})


# Single shared instance used across the app.
exchange = ExchangeService()
