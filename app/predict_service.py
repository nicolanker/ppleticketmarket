"""Play-money LMSR prediction market for the 'best thesis' nominees.

Self-contained and independent of the ticket market. State lives in the
database; an LMSR maker (see :mod:`app.lmsr`) prices every nominee, seeded
uniformly at 1/N. Trading is serialised with a lock.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from .database import SessionLocal
from .lmsr import cost_to_trade, prices
from .predict_models import (
    PredictHolding,
    PredictMarket,
    PredictOutcome,
    PredictTrade,
    PredictUser,
)

# Nominees for best thesis. Edit this list, then POST /api/predict/admin/reset
# (admin) to re-seed. Order here is only the initial display order.
NOMINEES = [
    "Bruno Griguoli",
    "Ana Aceto Navarro",
    "Lotta Bader",
    "Luisa Leibensberger",
    "Leyla Teschke Panah",
    "Zissa Rudolph",
    "Noah Erdoğan",
    "Natalie Clarke",
    "Matthew Kelleher",
    "Anna Rumpf",
    "Eliška Brčáková",
    "Elisabeth Knetsch",
    "Léane L'Aot",
    "Alice Maffoni",
    "Paula Zetsche",
    "Clara Steinhart",
    "Greta Butkevičiūtė",
    "Roos Bosgraaf",
]

START_BALANCE: float = float(os.getenv("PREDICT_START_BALANCE", "1000"))
B: float = float(os.getenv("LMSR_B", "100"))  # LMSR liquidity parameter
MAX_TRADE_SHARES = 100_000

_lock = threading.Lock()
_EPS = 1e-9


def ensure_seeded() -> None:
    """Create nominees + market row on first run (idempotent)."""
    with SessionLocal() as db:
        if db.query(PredictOutcome).count() == 0:
            for i, name in enumerate(NOMINEES):
                db.add(PredictOutcome(idx=i, name=name, q=0.0))
        if db.get(PredictMarket, 1) is None:
            db.add(PredictMarket(id=1, resolved=False))
        db.commit()


def _mask(email: str) -> str:
    local = email.split("@", 1)[0]
    return (local[:3] + "…") if len(local) > 3 else local


def _outcomes(db):
    return db.query(PredictOutcome).order_by(PredictOutcome.idx).all()


def get_state() -> dict:
    """Public market snapshot: prices, resolution, and leaderboard."""
    with SessionLocal() as db:
        outs = _outcomes(db)
        ps = prices([o.q for o in outs], B)
        market = db.get(PredictMarket, 1)
        resolved = bool(market and market.resolved)
        winner = None
        if resolved and market.winner_outcome_id:
            w = db.get(PredictOutcome, market.winner_outcome_id)
            winner = w.name if w else None

        outcomes = [
            {"id": o.id, "name": o.name, "prob": ps[i], "q": o.q}
            for i, o in enumerate(outs)
        ]

        # Leaderboard by net worth (balance + mark-to-market holdings).
        idx_by_id = {o.id: i for i, o in enumerate(outs)}
        leaderboard = []
        for u in db.query(PredictUser).all():
            net = u.balance
            if not resolved:
                for h in db.query(PredictHolding).filter_by(email=u.email).all():
                    net += h.shares * ps[idx_by_id[h.outcome_id]]
            leaderboard.append({"name": _mask(u.email), "net_worth": round(net, 2)})
        leaderboard.sort(key=lambda x: -x["net_worth"])

        return {
            "resolved": resolved,
            "winner": winner,
            "b": B,
            "start_balance": START_BALANCE,
            "outcomes": outcomes,
            "leaderboard": leaderboard[:10],
        }


def get_history(max_points: int = 500) -> dict:
    """Reconstruct every candidate's probability over time from the trade log.

    Replays trades in order, recomputing the full LMSR price vector after each,
    so the frontend can plot any candidate's history (e.g. the current top 5).
    Begins from the uniform 1/N baseline.
    """
    with SessionLocal() as db:
        outs = _outcomes(db)
        idx_by_id = {o.id: i for i, o in enumerate(outs)}
        q = [0.0] * len(outs)

        points = [{"t": None, "probs": prices(q, B)}]  # baseline (uniform 1/N)
        for t in db.query(PredictTrade).order_by(PredictTrade.id).all():
            q[idx_by_id[t.outcome_id]] += t.shares
            ts = t.created_at.isoformat() if t.created_at else datetime.now(timezone.utc).isoformat()
            points.append({"t": ts, "probs": prices(q, B)})

        if len(points) > max_points:  # downsample, always keeping the last point
            step = len(points) / max_points
            sampled = [points[int(i * step)] for i in range(max_points)]
            sampled[-1] = points[-1]
            points = sampled

        return {
            "outcomes": [{"id": o.id, "name": o.name} for o in outs],
            "points": points,
        }


def get_portfolio(email: str) -> dict:
    """A trader's balance, holdings, and net worth. Creates the user if new."""
    email = email.strip().lower()
    with SessionLocal() as db:
        user = db.get(PredictUser, email)
        if user is None:
            user = PredictUser(email=email, balance=START_BALANCE)
            db.add(user)
            db.commit()
            db.refresh(user)

        outs = _outcomes(db)
        ps = prices([o.q for o in outs], B)
        idx_by_id = {o.id: i for i, o in enumerate(outs)}

        holdings = []
        net = user.balance
        for h in db.query(PredictHolding).filter_by(email=email).all():
            if abs(h.shares) < _EPS:
                continue
            i = idx_by_id[h.outcome_id]
            value = h.shares * ps[i]
            net += value
            holdings.append(
                {
                    "id": h.outcome_id,
                    "name": outs[i].name,
                    "shares": round(h.shares, 2),
                    "price": ps[i],
                    "value": round(value, 2),
                }
            )
        return {
            "email": email,
            "balance": round(user.balance, 2),
            "net_worth": round(net, 2),
            "holdings": holdings,
        }


def trade(email: str, outcome_id: int, shares: float) -> dict:
    """Buy (shares > 0) or sell (shares < 0) shares of an outcome via the maker."""
    email = email.strip().lower()
    if shares == 0:
        raise ValueError("Enter a non-zero number of shares.")
    if abs(shares) > MAX_TRADE_SHARES:
        raise ValueError("Trade size too large.")

    with _lock:
        with SessionLocal() as db:
            market = db.get(PredictMarket, 1)
            if market and market.resolved:
                raise ValueError("The market is resolved — trading is closed.")

            outs = _outcomes(db)
            idx_by_id = {o.id: i for i, o in enumerate(outs)}
            if outcome_id not in idx_by_id:
                raise ValueError("Unknown nominee.")
            i = idx_by_id[outcome_id]

            q = [o.q for o in outs]
            c = cost_to_trade(q, i, shares, B)

            user = db.get(PredictUser, email)
            if user is None:
                user = PredictUser(email=email, balance=START_BALANCE)
                db.add(user)
                db.flush()

            holding = db.query(PredictHolding).filter_by(email=email, outcome_id=outcome_id).first()
            have = holding.shares if holding else 0.0
            if shares < 0 and -shares > have + _EPS:
                raise ValueError("You can't sell more shares than you own.")
            if c > user.balance + _EPS:
                raise ValueError("Insufficient balance for this trade.")

            outs[i].q += shares
            user.balance -= c
            if holding is None:
                holding = PredictHolding(email=email, outcome_id=outcome_id, shares=0.0)
                db.add(holding)
            holding.shares += shares
            if abs(holding.shares) < _EPS:
                holding.shares = 0.0

            price_after = prices([o.q for o in outs], B)[i]
            db.add(
                PredictTrade(
                    email=email,
                    outcome_id=outcome_id,
                    shares=shares,
                    cost=c,
                    price_after=price_after,
                )
            )
            db.commit()

    return get_portfolio(email)


def resolve(winner_outcome_id: int) -> dict:
    """Declare the winner: each share of that outcome pays out 1 point."""
    with _lock:
        with SessionLocal() as db:
            market = db.get(PredictMarket, 1)
            if market is None:
                raise ValueError("Market not initialised.")
            if market.resolved:
                raise ValueError("Market is already resolved.")
            winner = db.get(PredictOutcome, winner_outcome_id)
            if winner is None:
                raise ValueError("Unknown nominee.")

            paid = 0.0
            for h in db.query(PredictHolding).filter_by(outcome_id=winner_outcome_id).all():
                if h.shares <= 0:
                    continue
                u = db.get(PredictUser, h.email)
                if u:
                    u.balance += h.shares  # 1 point per winning share
                    paid += h.shares

            market.resolved = True
            market.winner_outcome_id = winner_outcome_id
            db.commit()
            return {"resolved": True, "winner": winner.name, "points_paid": round(paid, 2)}


def reset() -> dict:
    """Wipe all prediction-market data and re-seed nominees from NOMINEES."""
    with _lock:
        with SessionLocal() as db:
            db.query(PredictTrade).delete()
            db.query(PredictHolding).delete()
            db.query(PredictUser).delete()
            db.query(PredictOutcome).delete()
            db.query(PredictMarket).delete()
            db.commit()
    ensure_seeded()
    return {"reset": True, "nominees": len(NOMINEES)}
