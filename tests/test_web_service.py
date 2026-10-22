"""
Tests for the web service - Flask application routes and API endpoints.
"""

import pytest
import json
import os
import tempfile

import ka_events.web.app as web_app
from ka_events.database import init_db


@pytest.fixture
def client():
    """Create a test client with temporary database."""
    # Create temporary database
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    # Initialize database directly
    init_db(db_path)

    # Create app instance with test config
    web_app.DATABASE_PATH = db_path
    web_app.app.config['DATABASE_PATH'] = db_path
    web_app.app.config['TESTING'] = True

    with web_app.app.test_client() as client:
        yield client

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def client_with_events():
    """Create test client with sample events in database."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    init_db(db_path)

    # Insert sample events using direct SQL
    import sqlite3
    from datetime import datetime, timedelta

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    today = datetime.now().date()

    events = [
        # Past event
        ('past_1', (today - timedelta(days=30)).isoformat(), '20:00', 'Past Event', 'Venue A', 'https://example.com/past', 'venue_a'),
        # Today's event
        ('today_1', today.isoformat(), '19:00', 'Today Event', 'Venue B', 'https://example.com/today', 'venue_b'),
        # Future events
        ('future_1', (today + timedelta(days=7)).isoformat(), '20:00', 'Future Event 1', 'Venue C', 'https://example.com/future1', 'venue_c'),
        ('future_2', (today + timedelta(days=14)).isoformat(), '21:00', 'Future Event 2', 'Venue D', 'https://example.com/future2', 'venue_d'),
    ]

    cursor.executemany("""
        INSERT OR REPLACE INTO events (id, event_date, event_time, event_name, venue, link, scraper_source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, events)

    conn.commit()
    conn.close()

    web_app.DATABASE_PATH = db_path
    web_app.app.config['DATABASE_PATH'] = db_path
    web_app.app.config['TESTING'] = True

    with web_app.app.test_client() as client:
        yield client

    if os.path.exists(db_path):
        os.remove(db_path)


class TestIndexRoute:
    """Test main page route."""

    def test_index_returns_html(self, client):
        """Test that index returns HTML content."""
        response = client.get('/')

        assert response.status_code == 200
        assert b'<!DOCTYPE html>' in response.data or b'<html' in response.data or b'<div' in response.data

    def test_index_venue_filter(self, client_with_events):
        """Test that filtering by scraper_source only shows that location's events."""
        response = client_with_events.get('/?venue=venue_c')

        assert response.status_code == 200
        assert b'Future Event 1' in response.data
        assert b'Today Event' not in response.data
        assert b'Future Event 2' not in response.data

    def test_index_no_filter_shows_all_upcoming(self, client_with_events):
        """Test that without a venue filter, all upcoming events are shown."""
        response = client_with_events.get('/')

        assert response.status_code == 200
        assert b'Today Event' in response.data
        assert b'Future Event 1' in response.data
        assert b'Future Event 2' in response.data

    def test_index_unknown_venue_shows_no_events(self, client_with_events):
        """Test that a venue with no events shows the empty state."""
        response = client_with_events.get('/?venue=Nonexistent')

        assert response.status_code == 200
        assert b'No upcoming events found.' in response.data


class TestApiEvents:
    """Test /api/events endpoint - upcoming events only."""

    def test_api_events_empty(self, client):
        """Test API returns empty list when no events."""
        response = client.get('/api/events')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_api_events_excludes_past(self, client_with_events):
        """Test API excludes past events."""
        response = client_with_events.get('/api/events')

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have 3 events (today + 2 future), not the past one
        assert len(data) == 3

        # Verify no past dates
        for event in data:
            assert 'event_name' in event
            assert 'event_date' in event
            assert 'venue' in event
            assert 'link' in event

    def test_api_events_ordered_by_date(self, client_with_events):
        """Test that API returns events ordered by date."""
        response = client_with_events.get('/api/events')

        data = json.loads(response.data)

        dates = [e['event_date'] for e in data]
        assert dates == sorted(dates)

    def test_api_events_filters_by_venue(self, client_with_events):
        """Test that the venue query param filters results by scraper_source."""
        response = client_with_events.get('/api/events?venue=venue_c')

        assert response.status_code == 200
        data = json.loads(response.data)

        assert len(data) == 1
        assert data[0]['venue'] == 'Venue C'
        assert data[0]['scraper_source'] == 'venue_c'


class TestApiEventsAll:
    """Test /api/events/all endpoint - all events including past."""

    def test_api_all_events_empty(self, client):
        """Test API all returns empty list when no events."""
        response = client.get('/api/events/all')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_api_all_events_includes_past(self, client_with_events):
        """Test API all includes past events."""
        response = client_with_events.get('/api/events/all')

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have all 4 events (past + today + 2 future)
        assert len(data) == 4


class TestHealthEndpoint:
    """Reports whether the web service can read its database."""

    def test_health_reports_ok_and_event_count(self, client_with_events):
        response = client_with_events.get('/health')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
        assert data['upcoming_events'] == 3

    def test_health_is_ok_on_an_empty_database(self, client):
        response = client.get('/health')

        assert response.status_code == 200
        assert json.loads(response.data)['upcoming_events'] == 0

    def test_health_reports_503_when_the_database_is_unreadable(self, client, monkeypatch):
        """A process that is up but cannot read its data is not healthy."""
        import ka_events.web.app as module

        def boom(*args, **kwargs):
            raise RuntimeError("database is gone")

        monkeypatch.setattr(module, 'get_upcoming_events', boom)
        response = client.get('/health')

        assert response.status_code == 503
        assert json.loads(response.data)['status'] == 'error'


class TestApiStatus:
    """Test /api/status endpoint - scraper status."""

    def test_api_status_structure(self, client):
        """Test API status returns correct structure."""
        response = client.get('/api/status')

        assert response.status_code == 200
        data = json.loads(response.data)

        assert 'status' in data
        assert data['status'] == 'ok'
        assert 'scrapers' in data
        assert isinstance(data['scrapers'], list)
