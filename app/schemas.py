"""Pydantic request/response schemas with input validation."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from . import config
from .matching_engine import Side


class OrderCreate(BaseModel):
    """Incoming order submission from the client."""

    email: EmailStr
    side: Side
    quantity: int = Field(..., ge=config.MIN_QUANTITY, le=config.MAX_QUANTITY)
    price: float = Field(..., gt=0, le=config.MAX_PRICE_EUROS, description="Limit price in euros")

    @field_validator("email")
    @classmethod
    def _check_domain(cls, value: str) -> str:
        if config.ALLOWED_EMAIL_DOMAINS:
            domain = value.split("@", 1)[1].lower()
            if not any(domain == d or domain.endswith("." + d) for d in config.ALLOWED_EMAIL_DOMAINS):
                allowed = ", ".join(config.ALLOWED_EMAIL_DOMAINS)
                raise ValueError(f"Email must belong to an approved university domain ({allowed}).")
        return value.lower()

    @field_validator("price")
    @classmethod
    def _round_price(cls, value: float) -> float:
        # Quantize to whole cents to avoid sub-cent prices.
        return round(value, 2)


class OrderOut(BaseModel):
    """Full order view — includes the trader's email. Admin-only."""

    id: int
    email: str
    side: Side
    quantity: int
    remaining: int
    filled: int
    price: float
    status: str
    created_at: datetime


class PublicOrderOut(BaseModel):
    """Anonymous order view for the public book — no email.

    Traders stay anonymous to everyone; identity is only revealed to the
    counterpart of an executed trade, via email.
    """

    id: int
    side: Side
    quantity: int
    remaining: int
    filled: int
    price: float
    status: str
    created_at: datetime


class TradeOut(BaseModel):
    id: int
    buy_order_id: int
    sell_order_id: int
    quantity: int
    price: float
    created_at: datetime


class PriceLevel(BaseModel):
    price: float
    quantity: int
    orders: int


class BookSide(BaseModel):
    bids: List[PriceLevel]
    asks: List[PriceLevel]


class MarketStats(BaseModel):
    last_price: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    total_trades: int
    total_volume: int
    open_orders: int


class Snapshot(BaseModel):
    """Public market snapshot pushed over WebSocket and returned by REST.

    Open orders are anonymised — no trader emails leave the server here.
    """

    book: BookSide
    recent_trades: List[TradeOut]
    open_orders: List[PublicOrderOut]
    stats: MarketStats


class OrderResponse(BaseModel):
    order: PublicOrderOut
    trades: List[TradeOut]
