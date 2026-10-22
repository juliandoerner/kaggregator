"""
KA Events Web Service.

Flask application that serves event listings from SQLite database.
Plain HTML frontend, minimal CSS styling.
"""

import logging
import os

from flask import Flask, render_template, jsonify, request

from ka_events.database import (
    get_all_events,
    get_upcoming_events,
    get_distinct_locations,
    get_scraper_status,
    init_db,
)
from ka_events.logging_config import configure_logging


configure_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/events.db")

# Once at import time, not per request. This used to run from a before_request
# hook, so every single HTTP request re-issued the CREATE TABLE / CREATE INDEX
# statements and two PRAGMA table_info lookups.
#
# Failure here must not abort the import: a module-level exception stops
# gunicorn from starting at all, which is a crash loop with no diagnostics -
# exactly the failure mode that hid the broken web image for so long. Log it
# instead and let /health report the process as unhealthy.
try:
    init_db(DATABASE_PATH)
    logger.info("Database ready at %s", DATABASE_PATH)
except Exception as exc:
    logger.error("Could not initialise database at %s: %s: %s",
                 DATABASE_PATH, type(exc).__name__, exc)


@app.route('/')
def index():
    """Main page - list upcoming events (today and future), optionally filtered by location."""
    scraper_source = request.args.get('venue', '').strip()
    events = get_upcoming_events(DATABASE_PATH, scraper_source=scraper_source or None)
    locations = get_distinct_locations(DATABASE_PATH)
    return render_template('index.html', events=events, locations=locations, selected_venue=scraper_source)


@app.route('/api/events')
def api_events():
    """JSON API endpoint for upcoming events (today and future), optionally filtered by location."""
    scraper_source = request.args.get('venue', '').strip()
    events = get_upcoming_events(DATABASE_PATH, scraper_source=scraper_source or None)
    return jsonify(events)


@app.route('/api/events/all')
def api_all_events():
    """JSON API endpoint for all events (including past events)."""
    events = get_all_events(DATABASE_PATH)
    return jsonify(events)


@app.route('/api/status')
def api_status():
    """API endpoint for scraper status."""
    scrapers = get_scraper_status(DATABASE_PATH)
    return jsonify({
        "status": "ok",
        "scrapers": scrapers
    })


@app.route('/health')
def health():
    """Service health check.

    Deliberately touches the database rather than just returning 200: a web
    process that is up but cannot read its data is not healthy, and that is
    exactly the state a broken deployment leaves it in.
    """
    try:
        upcoming = len(get_upcoming_events(DATABASE_PATH))
    except Exception as exc:
        logger.error("health check failed: %s", exc)
        return jsonify({"status": "error", "detail": str(exc)}), 503

    return jsonify({"status": "ok", "upcoming_events": upcoming})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
