"""FastAPI application: REST API, WebSocket feed, admin endpoints, static UI.

The web layer is deliberately thin — all market logic lives in
:mod:`app.service` and :mod:`app.matching_engine`.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from . import config, models
from .database import SessionLocal, init_db
from .models import OrderStatus
from .schemas import OrderCreate, OrderOut, OrderResponse, Snapshot
from .service import exchange

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("market")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    exchange.rebuild_from_db()
    logger.info("PPLE Graduation Ticket Market started.")
    yield


app = FastAPI(title="PPLE Graduation Ticket Market", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Public REST API
# ---------------------------------------------------------------------------


@app.post("/api/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate) -> OrderResponse:
    """Submit a buy/sell limit order. Returns the order and any trades it caused."""
    db_order, db_trades = await exchange.submit_order(payload)
    return OrderResponse(
        order=exchange._public_order_out(db_order),
        trades=[exchange._trade_out(t) for t in db_trades],
    )


@app.get("/api/snapshot", response_model=Snapshot)
async def get_snapshot() -> Snapshot:
    """Full market snapshot: book, recent trades, open orders, and stats."""
    return exchange.build_snapshot()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Push a snapshot on connect, then stream updates on every market change."""
    await exchange.ws.connect(websocket)
    try:
        snapshot = exchange.build_snapshot()
        await websocket.send_json({"type": "snapshot", "data": snapshot.model_dump(mode="json")})
        while True:
            # We don't expect inbound messages; this keeps the socket alive and
            # lets us detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await exchange.ws.disconnect(websocket)
    except Exception:
        await exchange.ws.disconnect(websocket)


# ---------------------------------------------------------------------------
# Admin API (HTTP Basic auth)
# ---------------------------------------------------------------------------

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Constant-time check of admin credentials."""
    user_ok = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/api/admin/orders", response_model=list[OrderOut])
def admin_list_orders(_: str = Depends(require_admin)) -> list[OrderOut]:
    """List every order (all statuses), newest first."""
    with SessionLocal() as db:
        rows = db.query(models.Order).order_by(models.Order.id.desc()).all()
        return [exchange._order_out(o) for o in rows]


@app.delete("/api/admin/orders/{order_id}")
async def admin_cancel_order(order_id: int, _: str = Depends(require_admin)) -> dict:
    """Cancel a resting order by id."""
    removed = await exchange.cancel_order(order_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Order not open or not found")
    return {"cancelled": order_id}


@app.post("/api/admin/reset")
async def admin_reset(_: str = Depends(require_admin)) -> dict:
    """Wipe all orders and trades — launch a fresh market. Irreversible."""
    return await exchange.reset_market()


@app.get("/api/admin/stats")
def admin_stats(_: str = Depends(require_admin)) -> dict:
    """Aggregate market statistics for the admin dashboard."""
    snapshot = exchange.build_snapshot()
    with SessionLocal() as db:
        total_orders = db.query(models.Order).count()
        cancelled = db.query(models.Order).filter(models.Order.status == OrderStatus.CANCELLED).count()
        filled = db.query(models.Order).filter(models.Order.status == OrderStatus.FILLED).count()
    return {
        "stats": snapshot.stats.model_dump(mode="json"),
        "total_orders": total_orders,
        "filled_orders": filled,
        "cancelled_orders": cancelled,
        "open_orders": snapshot.stats.open_orders,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page(_: str = Depends(require_admin)) -> FileResponse:
    """Hidden, password-protected admin console."""
    return FileResponse(STATIC_DIR / "admin.html")


# Serve CSS/JS assets.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
