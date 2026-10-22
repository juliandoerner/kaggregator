"""
Email notifications for scraper health.

Uses the standard library only. If SMTP isn't configured the notifier turns
itself into a no-op that logs to stdout, so local development and tests never
try to send mail. Sending failures are swallowed: a broken mail server must
never take down a scrape run.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional


logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


class EmailNotifier:
    """Sends alert mail over SMTP, configured from the environment."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        use_tls: Optional[bool] = None,
    ):
        self.host = host if host is not None else os.environ.get('SMTP_HOST', '').strip()
        self.port = port if port is not None else int(os.environ.get('SMTP_PORT', 587))
        self.user = user if user is not None else os.environ.get('SMTP_USER', '').strip()
        self.password = (
            password if password is not None else os.environ.get('SMTP_PASSWORD', '')
        )
        self.recipient = (
            recipient if recipient is not None
            else os.environ.get('ALERT_EMAIL_TO', '').strip()
        )
        self.sender = (
            sender if sender is not None
            else os.environ.get('ALERT_EMAIL_FROM', '').strip() or self.user
        )
        self.use_tls = use_tls if use_tls is not None else _env_flag('SMTP_USE_TLS', True)

    @property
    def is_configured(self) -> bool:
        """Whether there is enough configuration to attempt a send."""
        return bool(self.host and self.recipient and self.sender)

    def send(self, subject: str, body: str) -> bool:
        """Send a message. Returns whether it went out; never raises."""
        if not self.is_configured:
            logger.info("SMTP not configured; would have sent: %s", subject)
            return False

        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = self.sender
        message['To'] = self.recipient
        message.set_content(body)

        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as smtp:
                    self._authenticate(smtp)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                    if self.use_tls:
                        smtp.starttls()
                    self._authenticate(smtp)
                    smtp.send_message(message)
        except Exception as exc:
            logger.error("failed to send mail: %s: %s", type(exc).__name__, exc)
            return False

        logger.info("sent alert mail: %s", subject)
        return True

    def _authenticate(self, smtp: smtplib.SMTP) -> None:
        if self.user and self.password:
            smtp.login(self.user, self.password)


def format_alert(
    scraper_name: str,
    status: str,
    reasons: list,
    consecutive_failures: int,
    events_found: int,
    stored_events: int,
    last_success: Optional[dict] = None,
) -> tuple:
    """Build the (subject, body) of a scraper failure alert."""
    subject = f"[KA Events] Scraper '{scraper_name}' is {status}"

    lines = [
        f"Scraper:              {scraper_name}",
        f"Status:               {status}",
        f"Consecutive failures: {consecutive_failures}",
        f"Events scraped:       {events_found}",
        f"Events still stored:  {stored_events}",
    ]

    if last_success:
        lines.append(
            f"Last healthy run:     {last_success.get('run_at')} "
            f"({last_success.get('events_found')} events)"
        )
    else:
        lines.append("Last healthy run:     none on record")

    lines.append("")
    lines.append("What went wrong:")
    for reason in reasons or ["unknown"]:
        lines.append(f"  - {reason}")

    lines.append("")
    lines.append(
        "Stored events were left untouched, so the site keeps showing the last\n"
        "good data until the scraper works again."
    )
    lines.append("")
    lines.append(f"Check the venue site and `ka_events/scrapers/{scraper_name}.py`.")

    return subject, "\n".join(lines)


def format_recovery(scraper_name: str, events_found: int) -> tuple:
    """Build the (subject, body) of a scraper recovery notice."""
    subject = f"[KA Events] Scraper '{scraper_name}' recovered"
    body = (
        f"Scraper '{scraper_name}' is healthy again and returned "
        f"{events_found} events.\n\nNo action needed."
    )
    return subject, body
