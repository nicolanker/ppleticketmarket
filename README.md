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

## Hosting (deploy live)
This app needs a real **ASGI** process and persistent **WebSocket** connections,
so WSGI-only hosts like **PythonAnywhere won't work**. Use Render (easiest),
Railway, Fly.io, or a VPS. A ready-to-use Render blueprint (`render.yaml`) and a
`Procfile` are included.

### Deploy on Render (recommended, free tier)
1. **Push to GitHub** (one-time):
   ```bash
   gh repo create pple-ticket-market --private --source . --push
   # or: create an empty repo on github.com, then
   #   git remote add origin https://github.com/<you>/pple-ticket-market.git
   #   git push -u origin main
   ```
2. On <https://render.com>: **New + → Blueprint**, connect the repo. Render reads
   `render.yaml` and creates the web service **and** a Postgres database, wiring
   `DATABASE_URL` automatically.
3. In the service's **Environment**, set `RESEND_API_KEY` (and change
   `ADMIN_PASSWORD` if you don't want the auto-generated one).
4. Deploy. Your market is live at `https://pple-ticket-market.onrender.com`.

Tables are created automatically on first boot — no migration step.

**Free-tier caveats:** the web service sleeps after ~15 min idle (≈30 s cold
start, and WebSocket clients reconnect on wake); free Postgres expires after
~90 days. Upgrade either to a paid plan for always-on production use.

### Other hosts
- **Railway** — `railway up`; add a Postgres plugin; it uses the `Procfile`.
- **Fly.io** — `fly launch` (add a Dockerfile or use the Python buildpack) + `fly postgres create`.
- **VPS** — run uvicorn behind nginx with TLS; point `DATABASE_URL` at your Postgres.

Start command (all hosts): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
