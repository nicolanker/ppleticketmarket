"""Application configuration loaded from environment variables.

Values are read once at import time. A ``.env`` file (see ``.env.example``) is
loaded automatically in development via python-dotenv.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# -- Database -----------------------------------------------------------------
# Defaults to a local SQLite file. Set DATABASE_URL to a postgresql:// URL in
# production — the SQLAlchemy layer is written to work with either.
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./market.db")
# Managed hosts (Render, Heroku, Railway) often hand out a "postgres://" URL,
# which SQLAlchemy no longer recognises. Normalise it to "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# -- Admin --------------------------------------------------------------------
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "changeme")

# -- Order constraints --------------------------------------------------------
MIN_QUANTITY: int = int(os.getenv("MIN_QUANTITY", "1"))
MAX_QUANTITY: int = int(os.getenv("MAX_QUANTITY", "5"))
MAX_PRICE_EUROS: float = float(os.getenv("MAX_PRICE_EUROS", "10000"))

# Optional university email gate. If set (e.g. "uva.nl,student.uva.nl"), only
# emails ending in one of these domains are accepted. Empty = accept any valid
# email address.
ALLOWED_EMAIL_DOMAINS: list[str] = [
    d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()
]

# -- Email delivery -----------------------------------------------------------
# Provider: "console" (log only, the default), "smtp", or "resend".
EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "console").strip().lower()
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "PPLE Ticket Market <market@example.com>")

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS: bool = _bool("SMTP_USE_TLS", True)

RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
