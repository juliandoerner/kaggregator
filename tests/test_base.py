"""
Tests for base.py - Event class and BaseScraper.
"""

import pytest

from ka_events.base import Event, BaseScraper


class TestBaseScraperHttp:
    """The shared HTTP layer every scraper now goes through."""

    def test_session_sets_an_honest_user_agent(self):
        scraper = BaseScraper()
        ua = scraper.session.headers['User-Agent']

        assert 'KAEventsBot' in ua
        assert 'Mozilla' not in ua, "must not impersonate a browser"
        scraper.close()

    def test_session_is_reused_across_requests(self):
        """Connection reuse matters for Stadtmitte's twelve month pages."""
        scraper = BaseScraper()
        assert scraper.session is scraper.session
        scraper.close()

    def test_close_discards_the_session(self):
        scraper = BaseScraper()
        first = scraper.session
        scraper.close()
        assert scraper.session is not first
        scraper.close()

    def test_fetch_and_post_go_through_one_seam(self, monkeypatch):
        """Tests and the fixture recorder patch _request; both verbs must use it."""
        seen = []

        def fake_request(self, method, url, **kwargs):
            seen.append((method, url, kwargs.get('timeout')))
            return 'response'

        monkeypatch.setattr(BaseScraper, '_request', fake_request)
        scraper = BaseScraper()

        assert scraper.fetch('https://example.com/a') == 'response'
        assert scraper.post('https://example.com/b', data={'x': 1}) == 'response'
        assert [s[0] for s in seen] == ['GET', 'POST']

    def test_default_timeout_is_applied(self, monkeypatch):
        captured = {}

        class FakeSession:
            headers = {}

            def request(self, method, url, **kwargs):
                captured.update(kwargs)

                class R:
                    status_code = 200

                    def raise_for_status(self):
                        pass
                return R()

        scraper = BaseScraper()
        monkeypatch.setattr(BaseScraper, 'session', property(lambda self: FakeSession()))
        scraper.fetch('https://example.com')

        assert captured['timeout'] == BaseScraper.TIMEOUT

    def test_retries_are_configured_for_transient_failures(self):
        scraper = BaseScraper()
        adapter = scraper.session.get_adapter('https://example.com')
        retry = adapter.max_retries

        assert retry.total == BaseScraper.MAX_RETRIES
        assert 503 in retry.status_forcelist
        assert 404 not in retry.status_forcelist, "client errors must not be retried"
        scraper.close()


class TestEvent:
    """Test cases for the Event class."""

    def test_event_creation_minimal(self):
        """Test creating an event with minimal required fields."""
        event = Event(
            event_name="Summer Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/event"
        )

        assert event.event_name == "Summer Concert"
        assert event.event_date == "2026-07-15"
        assert event.venue == "KOHI"
        assert event.link == "https://example.com/event"
        assert event.event_time is None

    def test_event_creation_with_time(self):
        """Test creating an event with time specified."""
        event = Event(
            event_name="Jazz Night",
            event_date="2026-08-20",
            event_time="20:00",
            venue="Substage",
            link="https://substage.de/event"
        )

        assert event.event_name == "Jazz Night"
        assert event.event_date == "2026-08-20"
        assert event.event_time == "20:00"
        assert event.venue == "Substage"
        assert event.link == "https://substage.de/event"

    def test_event_generate_id_consistent(self):
        """Test that generate_id produces consistent results."""
        event1 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/123"
        )

        event2 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/123"
        )

        # Same data should produce same ID
        assert event1.generate_id() == event2.generate_id()

        # ID should be 16 characters (first 16 of MD5 hex)
        assert len(event1.generate_id()) == 16

    def test_event_generate_id_different(self):
        """Test that different data produces different IDs."""
        event1 = Event(
            event_name="Concert",
            event_date="2026-07-15",
            venue="KOHI",
            link="https://example.com/123"
        )

        event2 = Event(
            event_name="Concert",
            event_date="2026-07-16",  # Different date
            venue="KOHI",
            link="https://example.com/123"
        )

        assert event1.generate_id() != event2.generate_id()

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        event = Event(
            event_name="Poetry Slam",
            event_date="2026-09-01",
            event_time="19:30",
            venue="Tollhaus",
            link="https://tollhaus.de/slam"
        )

        result = event.to_dict()

        assert result == {
            'event_name': 'Poetry Slam',
            'event_date': '2026-09-01',
            'event_time': '19:30',
            'venue': 'Tollhaus',
            'link': 'https://tollhaus.de/slam',
            # Optional enrichment fields default to None
            'source_event_id': None,
            'description': None,
            'category': None,
            'image_url': None,
            'price': None,
        }

    def test_event_to_dict_without_time(self):
        """Test converting event to dictionary without time."""
        event = Event(
            event_name="All Day Festival",
            event_date="2026-10-05",
            venue="Z10",
            link="https://z10.info/festival"
        )

        result = event.to_dict()

        assert result == {
            'event_name': 'All Day Festival',
            'event_date': '2026-10-05',
            'event_time': None,
            'venue': 'Z10',
            'link': 'https://z10.info/festival',
            'source_event_id': None,
            'description': None,
            'category': None,
            'image_url': None,
            'price': None,
        }

    def test_event_special_characters(self):
        """Test event with special characters in name."""
        event = Event(
            event_name='Rock & Roll Night "Greatest Hits"',
            event_date="2026-11-11",
            venue="AKK",
            link="https://akk.org/rock"
        )

        assert event.event_name == 'Rock & Roll Night "Greatest Hits"'
        assert '"' in event.to_dict()['event_name']

    def test_event_unicode_characters(self):
        """Test event with unicode characters."""
        event = Event(
            event_name="München Konzert",
            event_date="2026-12-24",
            venue="Staatstheater",
            link="https://staatstheater.de/weihnachten"
        )

        assert event.event_name == "München Konzert"
        assert "ü" in event.to_dict()['event_name']


class TestBaseScraper:
    """Test cases for the BaseScraper class."""

    def test_base_scraper_name(self):
        """Test that base scraper has default name."""
        scraper = BaseScraper()
        assert scraper.name == "base"

    def test_base_scraper_fetch_events_raises(self):
        """Test that base scraper raises NotImplementedError."""
        scraper = BaseScraper()

        with pytest.raises(NotImplementedError) as exc_info:
            scraper.fetch_events()

        assert "Subclasses must implement fetch_events" in str(exc_info.value)

    def test_custom_scraper_inherits_base(self):
        """Test that custom scrapers properly inherit from BaseScraper."""
        class TestScraper(BaseScraper):
            name = "test"

            def fetch_events(self):
                return [
                    Event(
                        event_name="Test Event",
                        event_date="2026-01-01",
                        venue="Test Venue",
                        link="https://test.com"
                    )
                ]

        scraper = TestScraper()
        assert scraper.name == "test"
        events = scraper.fetch_events()

        assert len(events) == 1
        assert isinstance(events[0], Event)
        assert events[0].event_name == "Test Event"
