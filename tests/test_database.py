"""
Tests for database.py - Database operations.
"""

import pytest
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from ka_events.database import (
    get_connection,
    init_db,
    upsert_events,
    update_scraper_status,
    delete_orphaned_events,
    get_all_events,
    get_scraper_status
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


class TestGetConnection:
    """Test cases for get_connection function."""

    def test_get_connection_creates_file(self, temp_db):
        """Test that get_connection creates the database file."""
        conn = get_connection(temp_db)
        assert conn is not None
        assert os.path.exists(temp_db)
        conn.close()

    def test_get_connection_returns_valid_connection(self, temp_db):
        """Test that returned connection is valid."""
        conn = get_connection(temp_db)

        # Should be able to execute queries
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()

        assert result[0] == 1
        conn.close()


class TestInitDb:
    """Test cases for init_db function."""

    def test_init_db_creates_tables(self, temp_db):
        """Test that init_db creates required tables."""
        init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Check events table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='events'
        """)
        assert cursor.fetchone() is not None

        # Check scrapers table exists (not scraper_status)
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='scrapers'
        """)
        assert cursor.fetchone() is not None

        conn.close()

    def test_init_db_events_table_schema(self, temp_db):
        """Test that events table has correct schema."""
        init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(events)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Actual schema from database.py
        assert 'id' in columns
        assert 'event_date' in columns
        assert 'event_time' in columns
        assert 'event_name' in columns
        assert 'venue' in columns
        assert 'link' in columns
        assert 'scraper_source' in columns
        assert 'created_at' in columns
        # Note: no 'updated_at' in actual schema

        conn.close()

    def test_init_db_scrapers_table_schema(self, temp_db):
        """Test that scrapers table has correct schema."""
        init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(scrapers)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Actual schema: name, last_run, last_status, events_found
        assert 'name' in columns
        assert 'last_run' in columns
        assert 'last_status' in columns
        assert 'events_found' in columns

        conn.close()

    def test_init_db_idempotent(self, temp_db):
        """Test that init_db can be called multiple times safely."""
        init_db(temp_db)
        init_db(temp_db)  # Should not raise error
        init_db(temp_db)  # Should still work

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Tables should still exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        assert 'events' in tables
        assert 'scrapers' in tables

        conn.close()


class TestUpsertEvents:
    """Test cases for upsert_events function."""

    def test_upsert_events_insert_new(self, temp_db):
        """Test inserting new events."""
        init_db(temp_db)

        events = [
            {
                'id': 'abc123',
                'event_name': 'Test Event 1',
                'event_date': '2026-07-15',
                'event_time': '20:00',
                'venue': 'KOHI',
                'link': 'https://test.com/1',
                'scraper_source': 'kohi'
            },
            {
                'id': 'def456',
                'event_name': 'Test Event 2',
                'event_date': '2026-07-16',
                'event_time': '21:00',
                'venue': 'Substage',
                'link': 'https://test.com/2',
                'scraper_source': 'substage'
            }
        ]

        count = upsert_events(events, temp_db)

        assert count == 2

        # Verify events were inserted
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_upsert_events_updates_existing(self, temp_db):
        """Test updating existing events (upsert behavior)."""
        init_db(temp_db)

        # Insert initial event
        events1 = [{
            'id': 'abc123',
            'event_name': 'Original Name',
            'event_date': '2026-07-15',
            'event_time': '20:00',
            'venue': 'KOHI',
            'link': 'https://test.com/1',
            'scraper_source': 'kohi'
        }]
        upsert_events(events1, temp_db)

        # Update same event
        events2 = [{
            'id': 'abc123',
            'event_name': 'Updated Name',
            'event_date': '2026-07-15',
            'event_time': '21:00',  # Changed time
            'venue': 'KOHI',
            'link': 'https://test.com/1',
            'scraper_source': 'kohi'
        }]
        upsert_events(events2, temp_db)

        # Verify update happened (not duplicate)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT event_name, event_time FROM events WHERE id = 'abc123'")
        row = cursor.fetchone()

        assert row[0] == 'Updated Name'
        assert row[1] == '21:00'
        assert cursor.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1

        conn.close()

    def test_upsert_events_empty_list(self, temp_db):
        """Test upserting empty list."""
        init_db(temp_db)

        count = upsert_events([], temp_db)

        assert count == 0

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_upsert_events_multiple_scrapers(self, temp_db):
        """Test upserting events from multiple scrapers."""
        init_db(temp_db)

        events = [
            {'id': 'a1', 'event_name': 'KOHI Event', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 's1', 'event_name': 'Substage Event', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'Substage', 'link': 'https://substage.de/1',
             'scraper_source': 'substage'},
            {'id': 'z1', 'event_name': 'Z10 Event', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'Z10', 'link': 'https://z10.info/1',
             'scraper_source': 'z10'},
        ]

        count = upsert_events(events, temp_db)
        assert count == 3

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT scraper_source FROM events")
        sources = [row[0] for row in cursor.fetchall()]

        assert set(sources) == {'kohi', 'substage', 'z10'}
        conn.close()


class TestSchemaMigration:
    """Upgrading an existing database in place."""

    @staticmethod
    def _legacy_db(path):
        """A database as it existed before the richer event model."""
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE events (
                id TEXT PRIMARY KEY, event_date TEXT NOT NULL, event_time TEXT,
                event_name TEXT, venue TEXT, link TEXT, scraper_source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)
        """)
        conn.execute("""
            CREATE TABLE scrapers (
                name TEXT PRIMARY KEY, last_run TEXT, last_status TEXT,
                events_found INTEGER DEFAULT 0)
        """)
        future = (datetime.now().date() + timedelta(days=7)).isoformat()
        past = (datetime.now().date() - timedelta(days=7)).isoformat()
        conn.executemany(
            "INSERT INTO events (id,event_date,event_name,venue,link,scraper_source)"
            " VALUES (?,?,?,?,?,?)",
            [('old-future', future, 'Upcoming', 'KOHI', 'https://kohi.de/1', 'kohi'),
             ('old-past', past, 'Happened', 'KOHI', 'https://kohi.de/2', 'kohi')])
        conn.commit()
        conn.close()

    def test_migration_adds_columns_without_losing_the_archive(self, temp_db):
        os.remove(temp_db)
        self._legacy_db(temp_db)

        init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
        remaining = {r[0] for r in conn.execute("SELECT id FROM events")}
        conn.close()

        assert {'source_event_id', 'description', 'category',
                'image_url', 'price', 'updated_at'} <= columns
        assert 'old-past' in remaining, "past events are the archive; keep them"

    def test_migration_clears_upcoming_events_once(self, temp_db):
        """Their IDs came from the old scheme, so no scraper will produce them
        again. Left in place they sit beside freshly scraped copies as
        duplicates, and the health guard suppresses the cleanup that would
        resolve it - measured on a real database: 69 duplicates, 4 scrapers
        flagged."""
        os.remove(temp_db)
        self._legacy_db(temp_db)

        init_db(temp_db)

        remaining = {e['id'] for e in get_all_events(temp_db)}
        assert 'old-future' not in remaining

    def test_migration_is_idempotent(self, temp_db):
        os.remove(temp_db)
        self._legacy_db(temp_db)
        init_db(temp_db)

        upsert_events([{
            'id': 'fresh', 'event_name': 'Fresh',
            'event_date': (datetime.now().date() + timedelta(days=3)).isoformat(),
            'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/3',
            'scraper_source': 'kohi',
        }], temp_db)

        init_db(temp_db)  # second run must not wipe anything

        assert 'fresh' in {e['id'] for e in get_all_events(temp_db)}


class TestUpsertEventsBatch:
    """The batch is one transaction, not one transaction per event."""

    def test_duplicate_ids_within_a_batch_are_folded(self, temp_db):
        """KOHI genuinely lists the same event twice; the count must reflect
        rows actually written, not entries submitted."""
        init_db(temp_db)

        duplicate = {
            'id': 'same', 'event_name': 'Listed Twice', 'event_date': '2026-09-12',
            'event_time': '19:00', 'venue': 'KOHI', 'link': 'https://kohi.de/x',
            'scraper_source': 'kohi',
        }

        count = upsert_events([duplicate, dict(duplicate)], temp_db)

        assert count == 1
        assert len(get_all_events(temp_db)) == 1

    def test_batch_rolls_back_entirely_on_failure(self, temp_db):
        """A mid-batch failure must not leave a venue half-updated."""
        init_db(temp_db)
        upsert_events([{
            'id': 'existing', 'event_name': 'Already here', 'event_date': '2026-09-01',
            'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
            'scraper_source': 'kohi',
        }], temp_db)

        # event_date is NOT NULL, so the second row fails and should take the
        # first one down with it.
        bad_batch = [
            {'id': 'good', 'event_name': 'Fine', 'event_date': '2026-09-02',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/2',
             'scraper_source': 'kohi'},
            {'id': 'bad', 'event_name': 'Broken', 'event_date': None,
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/3',
             'scraper_source': 'kohi'},
        ]

        with pytest.raises(sqlite3.IntegrityError):
            upsert_events(bad_batch, temp_db)

        stored = {e['id'] for e in get_all_events(temp_db)}
        assert stored == {'existing'}, "partial batch was committed"

    def test_update_preserves_created_at(self, temp_db):
        """ON CONFLICT DO UPDATE keeps the original row, so created_at still
        means 'first seen'. INSERT OR REPLACE used to reset it every run."""
        init_db(temp_db)
        event = {
            'id': 'e1', 'event_name': 'Original', 'event_date': '2026-09-01',
            'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
            'scraper_source': 'kohi',
        }
        upsert_events([event], temp_db)

        conn = sqlite3.connect(temp_db)
        first_seen = conn.execute("SELECT created_at FROM events WHERE id='e1'").fetchone()[0]
        conn.close()

        event['event_name'] = 'Renamed'
        upsert_events([event], temp_db)

        conn = sqlite3.connect(temp_db)
        name, created_at = conn.execute(
            "SELECT event_name, created_at FROM events WHERE id='e1'").fetchone()
        conn.close()

        assert name == 'Renamed'
        assert created_at == first_seen


class TestDeleteOrphanedEvents:
    """Cleanup removes upcoming events the source dropped, and keeps the past.

    These use dates relative to today rather than literals: the previous
    versions hard-coded 2026-07-15, which silently became a *past* date and so
    stopped exercising the behaviour they were written for.
    """

    @staticmethod
    def _event(event_id, days_from_today, scraper='kohi'):
        date = (datetime.now().date() + timedelta(days=days_from_today)).isoformat()
        return {
            'id': event_id, 'event_name': f'Event {event_id}', 'event_date': date,
            'event_time': '20:00', 'venue': 'KOHI', 'link': f'https://kohi.de/{event_id}',
            'scraper_source': scraper,
        }

    def test_delete_orphaned_removes_missing(self, temp_db):
        """An upcoming event dropped from the listing is removed."""
        init_db(temp_db)
        upsert_events([self._event('keep1', 7), self._event('delete1', 7)], temp_db)

        deleted = delete_orphaned_events('kohi', {'keep1'}, temp_db)

        assert deleted == 1
        assert [e['id'] for e in get_all_events(temp_db)] == ['keep1']

    def test_delete_orphaned_only_specified_scraper(self, temp_db):
        """Other scrapers' events are untouched."""
        init_db(temp_db)
        upsert_events([self._event('k1', 7), self._event('s1', 7, scraper='substage')], temp_db)

        deleted = delete_orphaned_events('kohi', set(), temp_db)

        assert deleted == 1
        remaining = get_all_events(temp_db)
        assert len(remaining) == 1 and remaining[0]['id'] == 's1'

    def test_delete_orphaned_no_valid_ids(self, temp_db):
        """An empty valid set clears the scraper's upcoming events.

        The health guard is what stops this happening on a silently broken run;
        the database function itself stays dumb.
        """
        init_db(temp_db)
        upsert_events([self._event('e1', 7)], temp_db)

        assert delete_orphaned_events('kohi', set(), temp_db) == 1

    def test_delete_orphaned_all_valid(self, temp_db):
        init_db(temp_db)
        upsert_events([self._event('e1', 7)], temp_db)

        assert delete_orphaned_events('kohi', {'e1'}, temp_db) == 0

    def test_past_events_are_archived_not_deleted(self, temp_db):
        """Past events are kept even though scrapers stop listing them.

        Scrapers return upcoming listings only, so without this an event was
        deleted the moment it happened and the database kept no history.
        """
        init_db(temp_db)
        upsert_events([self._event('yesterday', -1), self._event('last_month', -30),
                       self._event('upcoming', 7)], temp_db)

        # The scraper now only reports the upcoming one
        deleted = delete_orphaned_events('kohi', {'upcoming'}, temp_db)

        assert deleted == 0, "past events must not be treated as orphans"
        assert {e['id'] for e in get_all_events(temp_db)} == {
            'yesterday', 'last_month', 'upcoming'}

    def test_todays_events_are_still_cleaned(self, temp_db):
        """Today counts as upcoming, so a same-day cancellation still applies."""
        init_db(temp_db)
        upsert_events([self._event('today', 0)], temp_db)

        assert delete_orphaned_events('kohi', set(), temp_db) == 1


class TestEventIdBaseline:
    """The guard's baseline must use the same window as cleanup."""

    def test_baseline_ignores_archived_past_events(self, temp_db):
        """Otherwise archived rows look like pending deletions, the ratio creeps
        up every run, and every scraper eventually gets flagged."""
        from ka_events.database import get_event_ids_for_scraper

        init_db(temp_db)
        old = (datetime.now().date() - timedelta(days=60)).isoformat()
        soon = (datetime.now().date() + timedelta(days=5)).isoformat()
        upsert_events([
            {'id': 'archived', 'event_name': 'Old', 'event_date': old,
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/a',
             'scraper_source': 'kohi'},
            {'id': 'future', 'event_name': 'New', 'event_date': soon,
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/b',
             'scraper_source': 'kohi'},
        ], temp_db)

        assert get_event_ids_for_scraper('kohi', temp_db) == {'future'}


class TestUpdateScraperStatus:
    """Test cases for update_scraper_status function."""

    def test_update_scraper_status_success(self, temp_db):
        """Test updating scraper status on success."""
        init_db(temp_db)

        update_scraper_status('kohi', 'success', 14, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, last_status, events_found
            FROM scrapers
            WHERE name = 'kohi'
        """)
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == 'kohi'
        assert row[1] == 'success'
        assert row[2] == 14

        conn.close()

    def test_update_scraper_status_error(self, temp_db):
        """Test updating scraper status on error."""
        init_db(temp_db)

        error_msg = "Connection timeout"
        update_scraper_status('kohi', f'error: {error_msg}', 0, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT last_status
            FROM scrapers
            WHERE name = 'kohi'
        """)
        row = cursor.fetchone()

        assert 'error:' in row[0]
        assert error_msg in row[0]

        conn.close()

    def test_update_scraper_status_updates_timestamp(self, temp_db):
        """Test that last_run timestamp is updated."""
        init_db(temp_db)

        update_scraper_status('kohi', 'success', 5, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT last_run FROM scrapers WHERE name = 'kohi'")
        row = cursor.fetchone()

        assert row[0] is not None

        # Get timestamp and verify it's recent (within last minute)
        last_run = datetime.fromisoformat(row[0])
        now = datetime.now()
        diff = (now - last_run).total_seconds()

        assert diff < 60  # Within 60 seconds

        conn.close()

    def test_update_scraper_status_multiple_updates(self, temp_db):
        """Test multiple status updates."""
        init_db(temp_db)

        update_scraper_status('kohi', 'success', 10, temp_db)
        update_scraper_status('kohi', 'success', 12, temp_db)
        update_scraper_status('kohi', 'success', 15, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT events_found FROM scrapers WHERE name = 'kohi'")
        row = cursor.fetchone()

        # Latest count should be stored
        assert row[0] == 15

        conn.close()


class TestGetAllEvents:
    """Test cases for get_all_events function."""

    def test_get_all_events_empty(self, temp_db):
        """Test getting events from empty database."""
        init_db(temp_db)

        events = get_all_events(temp_db)

        assert events == []

    def test_get_all_events_returns_all(self, temp_db):
        """Test getting all events."""
        init_db(temp_db)

        events_data = [
            {'id': 'e1', 'event_name': 'Event 1', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 'e2', 'event_name': 'Event 2', 'event_date': '2026-07-16',
             'event_time': '21:00', 'venue': 'Substage', 'link': 'https://substage.de/1',
             'scraper_source': 'substage'},
        ]
        upsert_events(events_data, temp_db)

        events = get_all_events(temp_db)

        assert len(events) == 2

        # Check structure
        for event in events:
            assert 'id' in event
            assert 'event_name' in event
            assert 'event_date' in event
            assert 'venue' in event

    def test_get_all_events_ordered_by_date(self, temp_db):
        """Test that events are ordered by date."""
        init_db(temp_db)

        events_data = [
            {'id': 'e3', 'event_name': 'Event 3', 'event_date': '2026-07-17',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/3',
             'scraper_source': 'kohi'},
            {'id': 'e1', 'event_name': 'Event 1', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 'e2', 'event_name': 'Event 2', 'event_date': '2026-07-16',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/2',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        events = get_all_events(temp_db)

        dates = [e['event_date'] for e in events]
        assert dates == sorted(dates)


class TestGetUpcomingEvents:
    """Test cases for get_upcoming_events function (filters past events)."""

    def test_get_upcoming_empty(self, temp_db):
        """Test getting upcoming events from empty database."""
        init_db(temp_db)

        from ka_events.database import get_upcoming_events
        events = get_upcoming_events(temp_db)

        assert events == []

    def test_get_upcoming_excludes_past(self, temp_db):
        """Test that get_upcoming_events excludes past events."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        # Mix of past, today, and future events
        events_data = [
            {'id': 'past1', 'event_name': 'Past Event 1',
             'event_date': (today - timedelta(days=30)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/past1',
             'scraper_source': 'kohi'},
            {'id': 'past2', 'event_name': 'Past Event 2',
             'event_date': (today - timedelta(days=60)).isoformat(),
             'event_time': '18:00', 'venue': 'KOHI', 'link': 'https://kohi.de/past2',
             'scraper_source': 'kohi'},
            {'id': 'today', 'event_name': 'Today Event',
             'event_date': today.isoformat(),
             'event_time': '19:00', 'venue': 'KOHI', 'link': 'https://kohi.de/today',
             'scraper_source': 'kohi'},
            {'id': 'future1', 'event_name': 'Future Event 1',
             'event_date': (today + timedelta(days=7)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/future1',
             'scraper_source': 'kohi'},
            {'id': 'future2', 'event_name': 'Future Event 2',
             'event_date': (today + timedelta(days=14)).isoformat(),
             'event_time': '21:00', 'venue': 'KOHI', 'link': 'https://kohi.de/future2',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        upcoming = get_upcoming_events(temp_db)

        # 5 total - 2 past = 3 upcoming (today + 2 future)
        assert len(upcoming) == 3

        # Verify no past dates
        for event in upcoming:
            event_date = datetime.fromisoformat(event['event_date']).date()
            assert event_date >= today

    def test_get_upcoming_preserves_order(self, temp_db):
        """Test that upcoming events are ordered by date."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'f2', 'event_name': 'Future 2',
             'event_date': (today + timedelta(days=14)).isoformat(),
             'event_time': '21:00', 'venue': 'KOHI', 'link': 'https://kohi.de/f2',
             'scraper_source': 'kohi'},
            {'id': 't', 'event_name': 'Today',
             'event_date': today.isoformat(),
             'event_time': '19:00', 'venue': 'KOHI', 'link': 'https://kohi.de/t',
             'scraper_source': 'kohi'},
            {'id': 'f1', 'event_name': 'Future 1',
             'event_date': (today + timedelta(days=7)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/f1',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        upcoming = get_upcoming_events(temp_db)

        # Should be ordered: today, future1, future2
        dates = [e['event_date'] for e in upcoming]
        assert dates == sorted(dates)


class TestGetUpcomingEventsScraperFilter:
    """Test cases for get_upcoming_events with a scraper_source (location) filter."""

    def test_filters_to_single_scraper(self, temp_db):
        """Test that passing scraper_source only returns events from that scraper."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'KOHI Event', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 's1', 'event_name': 'Substage Event', 'event_date': (today + timedelta(days=2)).isoformat(),
             'event_time': '20:00', 'venue': 'Substage - Halle', 'link': 'https://substage.de/1',
             'scraper_source': 'substage'},
        ]
        upsert_events(events_data, temp_db)

        filtered = get_upcoming_events(temp_db, scraper_source='kohi')

        assert len(filtered) == 1
        assert filtered[0]['scraper_source'] == 'kohi'

    def test_groups_multiple_venues_under_one_scraper(self, temp_db):
        """Test that different venue text under the same scraper is grouped together (e.g. KOHI @ Jubez)."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'Event at KOHI', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 'a2', 'event_name': 'Event at KOHI @ Jubez', 'event_date': (today + timedelta(days=2)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI @ Jubez', 'link': 'https://kohi.de/2',
             'scraper_source': 'kohi'},
            {'id': 'a3', 'event_name': 'Event at KOHI @ Querfunk', 'event_date': (today + timedelta(days=3)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI @ Querfunk', 'link': 'https://kohi.de/3',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        filtered = get_upcoming_events(temp_db, scraper_source='kohi')

        assert len(filtered) == 3
        assert {e['venue'] for e in filtered} == {'KOHI', 'KOHI @ Jubez', 'KOHI @ Querfunk'}

    def test_no_filter_returns_all(self, temp_db):
        """Test that omitting scraper_source returns events from all scrapers."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'KOHI Event', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 's1', 'event_name': 'Substage Event', 'event_date': (today + timedelta(days=2)).isoformat(),
             'event_time': '20:00', 'venue': 'Substage - Halle', 'link': 'https://substage.de/1',
             'scraper_source': 'substage'},
        ]
        upsert_events(events_data, temp_db)

        events = get_upcoming_events(temp_db)

        assert len(events) == 2

    def test_unknown_scraper_returns_empty(self, temp_db):
        """Test that a scraper_source with no matching events returns an empty list."""
        from datetime import timedelta
        from ka_events.database import get_upcoming_events

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'KOHI Event', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        events = get_upcoming_events(temp_db, scraper_source='nonexistent')

        assert events == []


class TestGetDistinctLocations:
    """Test cases for get_distinct_locations function."""

    def test_empty_database(self, temp_db):
        """Test that an empty database returns an empty list."""
        from ka_events.database import get_distinct_locations

        init_db(temp_db)

        assert get_distinct_locations(temp_db) == []

    def test_returns_sorted_unique_locations_with_display_labels(self, temp_db):
        """Test that locations are deduplicated by scraper_source, sorted by label."""
        from datetime import timedelta
        from ka_events.database import get_distinct_locations

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'Event 1', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'Substage - Halle', 'link': 'https://substage.de/1',
             'scraper_source': 'substage'},
            {'id': 'a2', 'event_name': 'Event 2', 'event_date': (today + timedelta(days=2)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
            {'id': 'a3', 'event_name': 'Event 3', 'event_date': (today + timedelta(days=3)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI @ Jubez', 'link': 'https://kohi.de/2',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        assert get_distinct_locations(temp_db) == [
            {'value': 'kohi', 'label': 'KOHI'},
            {'value': 'substage', 'label': 'Substage'},
        ]

    def test_excludes_past_only_locations(self, temp_db):
        """Test that a scraper whose only events are in the past is excluded."""
        from datetime import timedelta
        from ka_events.database import get_distinct_locations

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'past1', 'event_name': 'Past Event', 'event_date': (today - timedelta(days=5)).isoformat(),
             'event_time': '20:00', 'venue': 'Old Venue', 'link': 'https://old.de/1',
             'scraper_source': 'old_scraper'},
            {'id': 'future1', 'event_name': 'Future Event', 'event_date': (today + timedelta(days=5)).isoformat(),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
        ]
        upsert_events(events_data, temp_db)

        assert get_distinct_locations(temp_db) == [{'value': 'kohi', 'label': 'KOHI'}]

    def test_unmapped_scraper_falls_back_to_raw_source(self, temp_db):
        """Test that a scraper with no venue entry in config.yaml uses its raw key as the label."""
        from datetime import timedelta
        from ka_events.database import get_distinct_locations

        init_db(temp_db)
        today = datetime.now().date()

        events_data = [
            {'id': 'a1', 'event_name': 'Event 1', 'event_date': (today + timedelta(days=1)).isoformat(),
             'event_time': '20:00', 'venue': 'Some Venue', 'link': 'https://example.com/1',
             'scraper_source': 'brand_new_scraper'},
        ]
        upsert_events(events_data, temp_db)

        assert get_distinct_locations(temp_db) == [
            {'value': 'brand_new_scraper', 'label': 'brand_new_scraper'}
        ]


class TestGetScraperStatus:
    """Test cases for get_scraper_status function."""

    def test_get_scraper_status_empty(self, temp_db):
        """Test getting status when no scrapers have run."""
        init_db(temp_db)

        status_list = get_scraper_status(temp_db)

        assert status_list == []

    def test_get_scraper_status_returns_list(self, temp_db):
        """Test getting status returns list of all scrapers."""
        init_db(temp_db)

        update_scraper_status('kohi', 'success', 10, temp_db)
        update_scraper_status('substage', 'success', 25, temp_db)

        status_list = get_scraper_status(temp_db)

        assert len(status_list) == 2

        # Check structure of each
        for status in status_list:
            assert 'name' in status
            assert 'last_status' in status
            assert 'events_found' in status
            assert 'last_run' in status

    def test_get_scraper_status_fields(self, temp_db):
        """Test that all fields are returned."""
        init_db(temp_db)

        update_scraper_status('substage', 'success', 25, temp_db)

        status_list = get_scraper_status(temp_db)

        assert len(status_list) == 1
        status = status_list[0]

        expected_fields = ['name', 'last_run', 'last_status', 'events_found']
        for field in expected_fields:
            assert field in status
