"""
Database module for KA Events - Minimal schema.
Shared between scraper service and web service.
"""

import logging
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Set


logger = logging.getLogger(__name__)


DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "./data/events.db")  # type: ignore


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a database connection."""
    path = db_path or DATABASE_PATH

    db_dir = os.path.dirname(path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize the database with required tables."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Minimal events table: Date, Time, Event Name, Venue, Link
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_date TEXT NOT NULL,
            event_time TEXT,
            event_name TEXT,
            venue TEXT,
            link TEXT,
            scraper_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Scrapers tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scrapers (
            name TEXT PRIMARY KEY,
            last_run TEXT,
            last_status TEXT,
            events_found INTEGER DEFAULT 0
        )
    """)

    # Append-only history of scraper runs. The `scrapers` table only keeps the
    # latest run, which is not enough to answer "did this scraper used to
    # return more than this?" when deciding whether a run looks broken.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraper_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scraper_name TEXT NOT NULL,
            run_at TEXT NOT NULL,
            status TEXT NOT NULL,
            events_found INTEGER DEFAULT 0,
            message TEXT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scraper_runs_name_time
        ON scraper_runs (scraper_name, run_at DESC)
    """)

    # Alerting state, added to `scrapers` so /api/status surfaces it for free.
    # Existing databases predate these columns, hence the migration.
    _ensure_column(cursor, 'scrapers', 'consecutive_failures', 'INTEGER DEFAULT 0')
    _ensure_column(cursor, 'scrapers', 'alerted', 'INTEGER DEFAULT 0')

    # Richer event fields. Several scrapers already parsed these and threw them
    # away because the model had nowhere to put them.
    identity_changed = _ensure_column(cursor, 'events', 'source_event_id', 'TEXT')
    _ensure_column(cursor, 'events', 'description', 'TEXT')
    _ensure_column(cursor, 'events', 'category', 'TEXT')
    _ensure_column(cursor, 'events', 'image_url', 'TEXT')
    _ensure_column(cursor, 'events', 'price', 'TEXT')
    _ensure_column(cursor, 'events', 'updated_at', 'TEXT')

    if identity_changed:
        # Adding source_event_id changes how event IDs are derived, so every
        # stored upcoming row now has an ID no scraper will produce again.
        # Left alone they would sit alongside freshly scraped copies as
        # duplicates until orphan cleanup caught up - and cleanup would be
        # suppressed by the health guard, which quite correctly reads "replace
        # everything" as suspicious. Measured on a real database: 69 duplicated
        # events and four scrapers flagged.
        #
        # Clearing them is safe: upcoming events are fully rebuilt by the next
        # run, minutes later. Past events keep their old IDs and become the
        # first entries of the archive - nothing re-scrapes them, so their IDs
        # never need to match.
        cursor.execute("DELETE FROM events WHERE event_date >= date('now')")
        if cursor.rowcount:
            logger.warning(
                "schema upgrade: cleared %d upcoming events so they can be "
                "re-scraped under the new identity scheme (past events kept)",
                cursor.rowcount,
            )

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_date_source
        ON events (event_date, scraper_source)
    """)

    conn.commit()
    conn.close()


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> bool:
    """Add a column to an existing table if it isn't there yet.

    Returns True if the column was actually added, which lets callers run a
    one-time data migration alongside the schema change.
    """
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column in existing:
        return False
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


def upsert_events(events: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """Insert or update multiple events in a single transaction.

    One connection and one transaction for the whole batch: the previous
    implementation opened a connection and committed per event (41 connections
    for a Substage run), which was both wasteful and non-atomic - a failure
    part-way through left a venue half-updated.

    Duplicate IDs within `events` are folded together, so the returned count is
    the number of rows actually written. KOHI genuinely lists the same event
    twice on its page.
    """
    if not events:
        return 0

    deduplicated = {}
    for event in events:
        deduplicated[event.get('id')] = event

    now = datetime.now().isoformat()
    rows = [
        (
            event.get('id'),
            event.get('event_date'),
            event.get('event_time'),
            event.get('event_name'),
            event.get('venue'),
            event.get('link'),
            event.get('scraper_source'),
            event.get('source_event_id'),
            event.get('description'),
            event.get('category'),
            event.get('image_url'),
            event.get('price'),
            now,
        )
        for event in deduplicated.values()
    ]

    conn = get_connection(db_path)
    try:
        with conn:  # commits on success, rolls the whole batch back on error
            conn.executemany("""
                INSERT INTO events
                    (id, event_date, event_time, event_name, venue, link,
                     scraper_source, source_event_id, description, category,
                     image_url, price, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    event_date = excluded.event_date,
                    event_time = excluded.event_time,
                    event_name = excluded.event_name,
                    venue = excluded.venue,
                    link = excluded.link,
                    scraper_source = excluded.scraper_source,
                    source_event_id = excluded.source_event_id,
                    description = excluded.description,
                    category = excluded.category,
                    image_url = excluded.image_url,
                    price = excluded.price,
                    updated_at = excluded.updated_at
            """, rows)
    finally:
        conn.close()

    return len(rows)


def delete_orphaned_events(scraper_source: str, valid_ids: Set[str], db_path: Optional[str] = None) -> int:
    """Remove a scraper's *upcoming* events that the source no longer lists.

    Past events are deliberately kept. Scrapers return upcoming listings, so an
    event silently became an orphan the moment it happened and cleanup deleted
    it - the database held no history, /api/events/all was nearly identical to
    /api/events, and scripts/cleanup_past_events.py had almost nothing to do.
    Restricting cleanup to today and later turns those rows into an archive.
    Cancellations still disappear, because a cancelled event drops out of the
    listing while it is still in the future.

    Args:
        scraper_source: The scraper name to clean up events for
        valid_ids: Set of event IDs that should be kept
        db_path: Optional custom database path

    Returns:
        Number of deleted events
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT id FROM events
            WHERE scraper_source = ? AND event_date >= date('now')
        """, (scraper_source,))
        current_ids = {row['id'] for row in cursor.fetchall()}

        # Find orphaned IDs (in DB but not in current scrape)
        orphaned_ids = current_ids - valid_ids

        if orphaned_ids:
            placeholders = ','.join('?' * len(orphaned_ids))
            cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", tuple(orphaned_ids))
            conn.commit()
            return len(orphaned_ids)

        return 0
    except Exception as e:
        logger.error("error deleting orphaned events for %s: %s", scraper_source, e)
        conn.rollback()
        return 0
    finally:
        conn.close()


def update_scraper_status(name: str, status: str, events_found: int, db_path: Optional[str] = None) -> None:
    """Update scraper run status.

    Uses an upsert rather than INSERT OR REPLACE so the alerting columns
    (consecutive_failures, alerted) survive a status update.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO scrapers (name, last_run, last_status, events_found)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run = excluded.last_run,
            last_status = excluded.last_status,
            events_found = excluded.events_found
    """, (name, datetime.now().isoformat(), status, events_found))

    conn.commit()
    conn.close()


def record_scraper_run(
    name: str,
    status: str,
    events_found: int,
    message: Optional[str] = None,
    db_path: Optional[str] = None
) -> None:
    """Append a run to the scraper history."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO scraper_runs (scraper_name, run_at, status, events_found, message)
        VALUES (?, ?, ?, ?, ?)
    """, (name, datetime.now().isoformat(), status, events_found, message))

    conn.commit()
    conn.close()


def get_recent_runs(name: str, limit: int = 20, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get the most recent runs for a scraper, newest first."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM scraper_runs
        WHERE scraper_name = ?
        ORDER BY run_at DESC, id DESC
        LIMIT ?
    """, (name, limit))
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_last_successful_run(name: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get the most recent healthy run for a scraper, if there is one."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM scraper_runs
        WHERE scraper_name = ? AND status = 'healthy'
        ORDER BY run_at DESC, id DESC
        LIMIT 1
    """, (name,))
    row = cursor.fetchone()

    conn.close()
    return dict(row) if row else None


def get_event_ids_for_scraper(name: str, db_path: Optional[str] = None) -> Set[str]:
    """Get the IDs of a scraper's *upcoming* stored events.

    This is the baseline a run is judged against: comparing it with the IDs a
    run just produced shows exactly how many rows orphan cleanup would delete.

    It must therefore use the same window as `delete_orphaned_events`. If it
    counted archived past events too, every accumulated archive row would look
    like a pending deletion, the ratio would creep upwards run after run, and
    the health guard would eventually flag every scraper as suspicious.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id FROM events
        WHERE scraper_source = ? AND event_date >= date('now')
    """, (name,))
    ids = {row['id'] for row in cursor.fetchall()}

    conn.close()
    return ids


def get_scraper_health(name: str, db_path: Optional[str] = None) -> Dict[str, int]:
    """Get alerting state for a scraper (defaults for an unknown scraper)."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT consecutive_failures, alerted FROM scrapers WHERE name = ?", (name,)
    )
    row = cursor.fetchone()

    conn.close()

    if not row:
        return {'consecutive_failures': 0, 'alerted': 0}
    return {
        'consecutive_failures': row['consecutive_failures'] or 0,
        'alerted': row['alerted'] or 0,
    }


def set_scraper_health(
    name: str,
    consecutive_failures: int,
    alerted: int,
    db_path: Optional[str] = None
) -> None:
    """Persist alerting state for a scraper."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO scrapers (name, consecutive_failures, alerted)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            consecutive_failures = excluded.consecutive_failures,
            alerted = excluded.alerted
    """, (name, consecutive_failures, alerted))

    conn.commit()
    conn.close()


def get_all_events(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all events from database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM events ORDER BY event_date ASC, event_time ASC")
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_upcoming_events(db_path: Optional[str] = None, scraper_source: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get only upcoming events (today and future dates), optionally filtered by scraper_source (location)."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Filter: event_date >= today's date
    if scraper_source:
        cursor.execute("""
            SELECT * FROM events
            WHERE event_date >= date('now') AND scraper_source = ?
            ORDER BY event_date ASC, event_time ASC
        """, (scraper_source,))
    else:
        cursor.execute("""
            SELECT * FROM events
            WHERE event_date >= date('now')
            ORDER BY event_date ASC, event_time ASC
        """)
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_distinct_locations(db_path: Optional[str] = None) -> List[Dict[str, str]]:
    """Get locations with upcoming events, for use in a filter dropdown.

    Grouped by scraper_source (not raw venue text) so that a scraper's multiple
    sub-locations collapse into a single filter option - "KOHI", "KOHI @ Jubez"
    and "KOHI @ Querfunk" are all one place to a user. Labels come from
    config.yaml, falling back to the raw scraper key.

    Returns {'value': scraper_source, 'label': display_name}, sorted by label.
    """
    from ka_events.config import get_config  # local import: config is optional here

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT scraper_source FROM events
        WHERE scraper_source IS NOT NULL AND scraper_source != '' AND event_date >= date('now')
    """)
    sources = [row['scraper_source'] for row in cursor.fetchall()]

    conn.close()

    config = get_config()
    locations = [
        {'value': source, 'label': config.display_name(source)}
        for source in sources
    ]
    locations.sort(key=lambda loc: loc['label'].lower())
    return locations


def get_scraper_status(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get status of all scrapers."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM scrapers")
    rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]
