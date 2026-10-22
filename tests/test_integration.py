"""
Integration tests for the scraper service.

These tests verify that components work together correctly.
"""

import pytest
from datetime import datetime, timedelta
import os
import tempfile

from ka_events.base import Event
from ka_events.database import init_db, upsert_events, get_all_events, delete_orphaned_events


class TestOrphanedEventCleanup:
    """Test orphaned event cleanup workflow."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def _future(self, days):
        return (datetime.now().date() + timedelta(days=days)).isoformat()

    def test_orphan_cleanup_workflow(self, temp_db):
        """A previously-listed upcoming event that vanishes is cleaned up.

        Dates are relative to today: with literals, these rows eventually became
        past events, which are now archived rather than deleted, and the test
        would quietly stop testing cleanup at all.
        """
        init_db(temp_db)

        # A previous scrape stored two upcoming events
        old_events = [
            {'id': 'old-event-1', 'event_name': 'Old Event 1', 'event_date': self._future(10),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/old1',
             'scraper_source': 'kohi'},
            {'id': 'old-event-2', 'event_name': 'Old Event 2', 'event_date': self._future(11),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/old2',
             'scraper_source': 'kohi'},
        ]
        upsert_events(old_events, temp_db)
        assert len(get_all_events(temp_db)) == 2

        # The next scrape reports a different single event
        valid_ids = {'new-event-1'}
        new_events = [
            {'id': 'new-event-1', 'event_name': 'New Event', 'event_date': self._future(20),
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/new',
             'scraper_source': 'kohi'},
        ]
        upsert_events(new_events, temp_db)

        deleted = delete_orphaned_events('kohi', valid_ids, temp_db)

        assert deleted == 2

        stored = get_all_events(temp_db)
        assert len(stored) == 1
        assert stored[0]['event_name'] == 'New Event'


class TestMultiScraperIntegration:
    """Test multiple scrapers working together."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_multiple_scrapers_same_database(self, temp_db):
        """Test storing events from multiple scrapers in same database."""
        # Initialize database
        init_db(temp_db)

        # Insert events from different scrapers
        kohi_events = [
            {'id': 'k1', 'event_name': 'KOHI Event', 'event_date': '2026-07-15',
             'event_time': '20:00', 'venue': 'KOHI', 'link': 'https://kohi.de/1',
             'scraper_source': 'kohi'},
        ]
        tollhaus_events = [
            {'id': 't1', 'event_name': 'Tollhaus Event', 'event_date': '2026-07-16',
             'event_time': '20:00', 'venue': 'Tollhaus', 'link': 'https://tollhaus.de/1',
             'scraper_source': 'tollhaus'},
        ]

        upsert_events(kohi_events, temp_db)
        upsert_events(tollhaus_events, temp_db)

        # Verify both scrapers' events are in database
        stored = get_all_events(temp_db)
        assert len(stored) == 2

        sources = {e['scraper_source'] for e in stored}
        assert sources == {'kohi', 'tollhaus'}

        venues = {e['venue'] for e in stored}
        assert 'KOHI' in venues
        assert 'Tollhaus' in venues


class TestEventIdGeneration:
    """Test event ID generation consistency."""

    def test_same_event_same_id(self):
        """Test that same event data produces same ID."""
        event1 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://kohi.de/event"
        )

        event2 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://kohi.de/event"
        )

        assert event1.generate_id() == event2.generate_id()

    def test_different_venue_different_id(self):
        """Test that different venue produces different ID."""
        event1 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/event"
        )

        event2 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="Substage",
            link="https://example.com/event"
        )

        assert event1.generate_id() != event2.generate_id()

    def test_different_date_different_id(self):
        """Test that different date produces different ID."""
        event1 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/event"
        )

        event2 = Event(
            event_name="Concert",
            event_date="2026-07-16",
            venue="KOHI",
            link="https://example.com/event"
        )

        assert event1.generate_id() != event2.generate_id()
