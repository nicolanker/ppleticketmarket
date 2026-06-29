# PPLE Graduation Ticket Market

A miniature electronic exchange for university graduation tickets, built on a
**central limit order book (CLOB)** with price-time priority, partial fills,
real-time updates, and email notifications.

## Stack
- **Backend:** FastAPI (Python)
- **Engine:** pure-Python CLOB, fully decoupled from the web layer
- **DB:** SQLAlchemy — SQLite in dev, PostgreSQL-ready
- **Frontend:** vanilla HTML/CSS/JS + Chart.js (step chart)
- **Real-time:** WebSockets
- **Email:** console / SMTP / Resend

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional; defaults work out of the box
python main.py                # or: uvicorn app.main:app --reload
```
Then open <http://127.0.0.1:8000>. Admin console: <http://127.0.0.1:8000/admin>
(default credentials `admin` / `changeme` — change these in `.env`).

In PyCharm, just press ▶ on `main.py`.

## Tests
```bash
pytest
```
The engine suite covers exact match, partial fill, multi-order matching, and
price-time priority.

## Architecture
| Layer | Module | Responsibility |
|-------|--------|----------------|
| Engine | `app/matching_engine.py` | Pure CLOB: orders → trades. No I/O. |
| Service | `app/service.py` | Persistence, locking, notifications, broadcast. |
| Web | `app/main.py` | REST + WebSocket + admin + static. |
| Persistence | `app/models.py`, `app/database.py` | ORM + engine/session. |
| Notifications | `app/notifications.py` | Trade emails (console/SMTP/Resend). |
| Real-time | `app/websocket_manager.py` | Connection registry + broadcast. |

### How matching works
- Buy orders match against the lowest asks; sells against the highest bids.
- Within a price level, earlier orders fill first (time priority).
- Trades **execute at the resting order's price**.
- Unfilled remainder rests on the book; matched parties are emailed each
  other's contact details to settle peer-to-peer.

## Configuration
See `.env.example`. Key knobs: `DATABASE_URL`, `ADMIN_PASSWORD`,
`MAX_QUANTITY`, `ALLOWED_EMAIL_DOMAINS`, and the email provider settings.

## Email setup (Resend)
1. Create a free account at <https://resend.com> and generate an API key.
2. Put it in `.env`: `RESEND_API_KEY=re_xxx`.
3. Test it: `python -m scripts.send_test_email your-signup-email@example.com`
4. **Testing vs production:** with no verified domain, Resend only delivers to
   your own signup address and `EMAIL_FROM` must be `onboarding@resend.dev`. To
   email arbitrary university addresses, verify a domain in the Resend dashboard
   (add the DNS records) and set `EMAIL_FROM` to an address on that domain.

If `EMAIL_PROVIDER=resend` but no key is set, trade emails harmlessly fall back
to console logging — matching never breaks because of email problems.

## Hosting
This app needs a real **ASGI** process and persistent **WebSocket** connections.
- ❌ **PythonAnywhere** — WSGI-only; no ASGI/WebSocket support. Not a fit.
- ✅ **Render / Railway / Fly.io** — run `uvicorn app.main:app`, support
  WebSockets, and offer a managed Postgres add-on. Set `DATABASE_URL`,
  `ADMIN_PASSWORD`, and `RESEND_API_KEY` as environment variables. Use Resend
  (HTTPS) for email since these hosts block outbound SMTP ports.
- ✅ **A small VPS** (Fly/Hetzner/DigitalOcean) behind nginx for full control.

Start command for any of them:
```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
