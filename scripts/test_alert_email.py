#!/usr/bin/env python3
"""
Send a test alert email.

Verifies the SMTP settings actually work, rather than finding out the first
time a scraper breaks.

Usage:
    python scripts/test_alert_email.py

Reads the same environment variables the scraper service uses (SMTP_HOST,
SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_TLS, ALERT_EMAIL_TO,
ALERT_EMAIL_FROM). Load your .env first, e.g.:

    set -a && source .env && set +a && python scripts/test_alert_email.py
"""

import sys

from ka_events.health import STATUS_SUSPICIOUS
from ka_events.notifications import EmailNotifier, format_alert


def main():
    notifier = EmailNotifier()

    print("SMTP configuration")
    print(f"  host:      {notifier.host or '(empty)'}")
    print(f"  port:      {notifier.port}")
    print(f"  user:      {notifier.user or '(none)'}")
    print(f"  password:  {'set' if notifier.password else '(none)'}")
    print(f"  use TLS:   {notifier.use_tls}")
    print(f"  from:      {notifier.sender or '(empty)'}")
    print(f"  to:        {notifier.recipient or '(empty)'}")
    print()

    if not notifier.is_configured:
        print("Not configured - SMTP_HOST, ALERT_EMAIL_TO and a sender address")
        print("are all required. Alerts would only be logged to stdout.")
        return 1

    subject, body = format_alert(
        scraper_name='example_venue',
        status=STATUS_SUSPICIOUS,
        reasons=['this is a test alert, nothing is actually wrong'],
        consecutive_failures=2,
        events_found=0,
        stored_events=17,
        last_success={'run_at': '2026-01-01T06:00:00', 'events_found': 17},
    )
    subject = f"{subject} [TEST]"

    print(f"Sending to {notifier.recipient} ...")
    if notifier.send(subject, body):
        print("Sent. Check the inbox (and the spam folder).")
        return 0

    print("Failed - see the error above.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
