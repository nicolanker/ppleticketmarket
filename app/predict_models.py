"""SQLAlchemy models for the play-money LMSR prediction market.

Kept separate from the ticket market's models; they share the same database
and ``Base`` so ``init_db`` creates both sets of tables.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PredictOutcome(Base):
    """One nominee / outcome. ``q`` is shares outstanding (drives the price)."""

    __tablename__ = "predict_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    q: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class PredictUser(Base):
    """A trader, identified by email, with a play-money balance."""

    __tablename__ = "predict_users"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PredictHolding(Base):
    """How many shares of an outcome a user holds."""

    __tablename__ = "predict_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("predict_outcomes.id"), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class PredictTrade(Base):
    """Audit log of every trade against the maker."""

    __tablename__ = "predict_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("predict_outcomes.id"), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)  # signed
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    price_after: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PredictMarket(Base):
    """Singleton (id=1) holding resolution state."""

    __tablename__ = "predict_market"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    winner_outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
