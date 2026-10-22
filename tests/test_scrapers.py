"""
Tests for scraper parsing logic that can be exercised without network access.
"""

from datetime import datetime

import pytz
from bs4 import BeautifulSoup

from ka_events.scrapers.stadtmitte import StadtmitteScraper, MONTHS_AHEAD


BERLIN_TZ = pytz.timezone("Europe/Berlin")


def _block(html: str):
    """Parse an .overview-event fragment the way the scraper sees it."""
    return BeautifulSoup(html, 'lxml').select_one('div.overview-event')


class TestStadtmitteMonthTimestamps:
    """The site's own 'next month' link adds 31 days, which silently skips a
    month (Aug 31 + 31 days = Oct 1). These guard the scraper against that."""

    def test_returns_one_timestamp_per_month(self):
        assert len(StadtmitteScraper()._month_timestamps()) == MONTHS_AHEAD

    def test_months_are_consecutive_and_distinct(self):
        timestamps = StadtmitteScraper()._month_timestamps()

        months = [
            (lambda d: (d.year, d.month))(datetime.fromtimestamp(ts, BERLIN_TZ))
            for ts in timestamps
        ]

        assert len(set(months)) == len(months), "a month was repeated or skipped"

        for (year, month), (next_year, next_month) in zip(months, months[1:]):
            expected = (year + 1, 1) if month == 12 else (year, month + 1)
            assert (next_year, next_month) == expected

    def test_starts_at_current_month(self):
        first = StadtmitteScraper()._month_timestamps()[0]
        now = datetime.now(BERLIN_TZ)
        resolved = datetime.fromtimestamp(first, BERLIN_TZ)

        assert (resolved.year, resolved.month) == (now.year, now.month)


class TestStadtmitteParseEvent:
    """Parsing of a single .overview-event block."""

    def test_parses_date_time_and_link(self):
        block = _block("""
            <div class='overview-event'>
                <div class='overview-day-time'>Sa - 21:00 Uhr</div>
                <div class='overview-day'>01/08.2026</div>
                <div class='overview-name'><a href='#' id='event_2113'>Forever Young</a></div>
            </div>
        """)

        event, event_id = StadtmitteScraper()._parse_event(block)

        assert event.event_name == 'Forever Young'
        assert event.event_date == '2026-08-01'   # DD/MM.YYYY -> ISO
        assert event.event_time == '21:00'
        assert event.venue == 'Die Stadtmitte'
        assert event_id == 'event_2113'
        assert event.link.endswith('#event_2113')

    def test_same_day_events_get_distinct_ids(self):
        """Two events on one day is a real case (2026-08-12); they must not
        collapse into a single database row."""
        scraper = StadtmitteScraper()

        first, _ = scraper._parse_event(_block("""
            <div class='overview-event'>
                <div class='overview-day-time'>Mi - 19:00 Uhr</div>
                <div class='overview-day'>12/08.2026</div>
                <div class='overview-name'><a href='#' id='event_2063'>Heavy//Hitter</a></div>
            </div>
        """))
        second, _ = scraper._parse_event(_block("""
            <div class='overview-event'>
                <div class='overview-day-time'>Mi - 18:00 Uhr</div>
                <div class='overview-day'>12/08.2026</div>
                <div class='overview-name'><a href='#' id='event_2115'>Karls Afterwork</a></div>
            </div>
        """))

        assert first.event_date == second.event_date
        assert first.generate_id() != second.generate_id()

    def test_missing_date_is_skipped(self):
        block = _block("""
            <div class='overview-event'>
                <div class='overview-day-time'>Sa - 21:00 Uhr</div>
                <div class='overview-day'>kein Datum</div>
                <div class='overview-name'><a href='#' id='event_1'>Broken</a></div>
            </div>
        """)

        assert StadtmitteScraper()._parse_event(block) is None

    def test_missing_time_still_yields_event(self):
        block = _block("""
            <div class='overview-event'>
                <div class='overview-day'>03/10.2026</div>
                <div class='overview-name'><a href='#' id='event_9'>Ohne Uhrzeit</a></div>
            </div>
        """)

        event, _ = StadtmitteScraper()._parse_event(block)

        assert event.event_date == '2026-10-03'
        assert event.event_time is None
