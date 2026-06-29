"""Email notifications for matched trades.

Three delivery backends are supported, selected by ``EMAIL_PROVIDER``:

* ``console`` (default) — log the message; nothing is actually sent. Lets the
  app run out of the box with zero configuration.
* ``smtp``    — send via a configured SMTP server (smtplib).
* ``resend``  — send via the Resend HTTP API.

Sending is performed off the event loop (``asyncio.to_thread``) so a slow mail
server never blocks order matching.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import List

import httpx

from . import config
from .matching_engine import Trade, cents_to_euros

logger = logging.getLogger("market.notifications")


def _trade_email(recipient: str, role: str, counterpart: str, trade: Trade) -> tuple[str, str]:
    """Build the (subject, body) for one side of a trade."""
    price = cents_to_euros(trade.price_cents)
    total = round(price * trade.quantity, 2)
    verb = "bought" if role == "buyer" else "sold"
    subject = f"✅ Trade executed — you {verb} {trade.quantity} ticket(s) @ €{price:.2f}"
    body = (
        f"Hi,\n\n"
        f"Your order on the PPLE Graduation Ticket Market has been matched.\n\n"
        f"  • You {verb}: {trade.quantity} ticket(s)\n"
        f"  • Price:    €{price:.2f} each (total €{total:.2f})\n\n"
        f"Please coordinate the handover and payment directly with your counterpart:\n\n"
        f"  • Counterpart ({'seller' if role == 'buyer' else 'buyer'}): {counterpart}\n\n"
        f"This market only matches orders and shares contact details — payment and "
        f"ticket transfer happen between the two of you.\n\n"
        f"— PPLE Graduation Ticket Market\n"
    )
    return subject, body


def _send_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
        if config.SMTP_USE_TLS:
            server.starttls()
        if config.SMTP_USERNAME:
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.send_message(msg)


def _send_resend(to: str, subject: str, body: str) -> None:
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
        json={"from": config.EMAIL_FROM, "to": [to], "subject": subject, "text": body},
        timeout=15,
    )
    if resp.status_code >= 400:
        # Surface Resend's error body (e.g. unverified domain / invalid key).
        raise RuntimeError(f"Resend API {resp.status_code}: {resp.text}")


def _send(to: str, subject: str, body: str) -> None:
    """Synchronous dispatch to whichever backend is actually configured.

    Resolution is by *available credentials*, not just EMAIL_PROVIDER, so a
    missing/mis-set EMAIL_PROVIDER never silently disables email: if a Resend
    key is present we send via Resend; if SMTP is configured we use that.
    Never raises upward — delivery failures must not break matching.
    """
    try:
        if config.EMAIL_PROVIDER == "smtp" and config.SMTP_HOST:
            _send_smtp(to, subject, body)
        elif config.RESEND_API_KEY:
            _send_resend(to, subject, body)
        elif config.SMTP_HOST:
            _send_smtp(to, subject, body)
        else:
            logger.info("[email:console] To: %s | %s\n%s", to, subject, body)
            return
        logger.info("Sent trade notification to %s", to)
    except Exception:  # pragma: no cover - delivery failures must not crash matching
        logger.exception("Failed to send trade notification to %s", to)


async def notify_trades(trades: List[Trade]) -> None:
    """Email both parties for every trade, concurrently and off the event loop."""
    tasks = []
    for trade in trades:
        buyer_subj, buyer_body = _trade_email(trade.buyer_email, "buyer", trade.seller_email, trade)
        seller_subj, seller_body = _trade_email(trade.seller_email, "seller", trade.buyer_email, trade)
        tasks.append(asyncio.to_thread(_send, trade.buyer_email, buyer_subj, buyer_body))
        tasks.append(asyncio.to_thread(_send, trade.seller_email, seller_subj, seller_body))
    if tasks:
        await asyncio.gather(*tasks)


def send_test_email(to: str) -> str:
    """Send a single test email using the configured provider.

    Unlike trade notifications, this **raises** on failure so configuration
    problems surface immediately. Returns a human-readable status string.
    """
    subject = "✅ PPLE Ticket Market — test email"
    body = (
        "This is a test email from the PPLE Graduation Ticket Market.\n\n"
        f"If you received this, your '{config.EMAIL_PROVIDER}' email configuration works.\n\n"
        "— PPLE Graduation Ticket Market\n"
    )
    if config.EMAIL_PROVIDER == "smtp":
        if not config.SMTP_HOST:
            raise RuntimeError("EMAIL_PROVIDER=smtp but SMTP_HOST is not set.")
        _send_smtp(to, subject, body)
        return f"Sent test email via SMTP ({config.SMTP_HOST}) to {to}"
    if config.EMAIL_PROVIDER == "resend":
        if not config.RESEND_API_KEY:
            raise RuntimeError("EMAIL_PROVIDER=resend but RESEND_API_KEY is not set.")
        _send_resend(to, subject, body)
        return f"Sent test email via Resend to {to}"
    logger.info("[email:console] (test) To: %s | %s\n%s", to, subject, body)
    return (
        "EMAIL_PROVIDER=console — nothing was actually sent (logged above).\n"
        "Set EMAIL_PROVIDER=smtp or resend in .env to send real email."
    )
