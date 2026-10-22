"""
Logging setup.

Both entry points call `configure_logging()` once at startup. Everything else
uses `logging.getLogger(__name__)`, so output carries a timestamp, a level and
the module it came from - none of which bare print() gave us when reading
service logs.
"""

import logging
import os
import sys


DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: str = None) -> None:
    """Configure root logging. Safe to call more than once."""
    global _configured
    if _configured:
        return

    resolved = (level or os.environ.get('LOG_LEVEL', 'INFO')).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(getattr(logging, resolved, logging.INFO))
    root.handlers = [handler]

    # APScheduler logs every job submission at INFO, which drowns out the
    # scraper's own output on a 6-hourly job.
    logging.getLogger('apscheduler').setLevel(logging.WARNING)

    _configured = True
