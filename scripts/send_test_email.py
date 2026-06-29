"""Send a test email using whatever is configured in .env.

Usage:
    python -m scripts.send_test_email you@example.com

Run this after setting EMAIL_PROVIDER / SMTP_* / RESEND_API_KEY in .env to
confirm real delivery works before relying on trade notifications.
"""

import sys

from app import notifications


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.send_test_email <recipient@example.com>")
        raise SystemExit(1)
    recipient = sys.argv[1]
    try:
        status = notifications.send_test_email(recipient)
        print(status)
    except Exception as exc:  # surface config problems clearly
        print(f"FAILED to send test email: {exc}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
