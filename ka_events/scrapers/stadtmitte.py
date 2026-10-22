"""
Die Stadtmitte Scraper for KA Events.

Scrapes events from https://die-stadtmitte.de/programm.php, a club and
event venue at Baumeisterstraße 3 in Karlsruhe.
"""

import re
import time
from urllib.parse import urljoin
from datetime import datetime
from typing import Optional

import pytz
from bs4 import BeautifulSoup

from ka_events.base import BaseScraper, Event


BERLIN_TZ = pytz.timezone("Europe/Berlin")

# How many months ahead to crawl, starting with the current month. The venue
# publishes roughly 5 months out; 12 gives generous headroom so the full
# listing is always captured (a partial listing would make orphan cleanup
# delete the events it failed to see).
MONTHS_AHEAD = 12

# "01/08.2026" -> day 01, month 08, year 2026
DATE_PATTERN = re.compile(r'(\d{1,2})/(\d{1,2})\.(\d{4})')
# "Sa - 21:00 Uhr" -> 21:00
TIME_PATTERN = re.compile(r'(\d{1,2}:\d{2})')


class StadtmitteScraper(BaseScraper):
    """Scraper for Die Stadtmitte events."""

    name = "stadtmitte"
    url = "https://die-stadtmitte.de/programm.php"
    venue_name = "Die Stadtmitte"

    def fetch_events(self) -> list[Event]:
        """Fetch events from the current month plus the following months."""
        events = []
        seen_ids = set()

        for timestamp in self._month_timestamps():
            for event, event_id in self._fetch_month(timestamp):
                # Guard against a month page repeating an event we already have
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                events.append(event)

            # Be polite: this crawls a page per month
            time.sleep(0.5)

        return events

    def _month_timestamps(self) -> list[int]:
        """Build one timestamp per month to request.

        The site renders whichever month contains the `timestamp` query
        parameter. Its own "next month" arrow just adds 31 days to the current
        timestamp, which skips a month entirely whenever that lands past the
        end of the following month (e.g. Aug 31 + 31 days = Oct 1 drops
        September), so we compute the months ourselves instead of following
        those links. Mid-month noon is used because it sits safely inside every
        month regardless of month length or DST shifts.
        """
        now = datetime.now(BERLIN_TZ)
        timestamps = []

        for offset in range(MONTHS_AHEAD):
            month_index = now.month - 1 + offset
            year = now.year + month_index // 12
            month = month_index % 12 + 1
            local_noon = BERLIN_TZ.localize(datetime(year, month, 15, 12, 0))
            timestamps.append(int(local_noon.timestamp()))

        return timestamps

    def _fetch_month(self, timestamp: int) -> list[tuple[Event, str]]:
        """Fetch and parse a single month page. Returns (event, event_id) pairs."""
        response = self.fetch(self.url, params={'timestamp': timestamp})

        soup = BeautifulSoup(response.text, 'lxml')
        results = []

        # Every event is fully rendered server-side; the detail block is only
        # hidden with CSS, so no extra request per event is needed.
        for block in soup.select('div.overview-event'):
            parsed = self._parse_event(block)
            if parsed:
                results.append(parsed)

        return results

    def _parse_event(self, block) -> Optional[tuple[Event, str]]:
        """Convert a single .overview-event block into an (Event, event_id) pair."""
        name_link = block.select_one('.overview-name a')
        date_elem = block.select_one('.overview-day')

        if not name_link or not date_elem:
            return None

        event_name = name_link.get_text(strip=True)
        if not event_name:
            return None

        date_match = DATE_PATTERN.search(date_elem.get_text(strip=True))
        if not date_match:
            return None

        day, month, year = date_match.groups()
        event_date = f"{year}-{int(month):02d}-{int(day):02d}"

        event_time = None
        time_elem = block.select_one('.overview-day-time')
        if time_elem:
            time_match = TIME_PATTERN.search(time_elem.get_text(strip=True))
            if time_match:
                hour, minute = time_match.group(1).split(':')
                event_time = f"{int(hour):02d}:{minute}"

        # Events have no individual page - they expand inline via JS. The
        # per-event anchor id (e.g. "event_2113") is stable and unique, which
        # keeps two events on the same day distinct - that does happen.
        event_id = name_link.get('id') or f"{event_date}-{event_name}"
        link = f"{self.url}#{event_id}"

        # The detail panel is rendered inline and merely hidden with CSS, so the
        # description and image cost no extra request.
        description, image_url = None, None
        details = block.select_one('.overviewdetails-content')
        if details:
            paragraphs = [p.get_text(' ', strip=True) for p in details.select('p')]
            text = ' '.join(p for p in paragraphs if p)
            description = text[:1000] or None

            image = details.select_one('a.swipebox')
            if image and image.get('href'):
                image_url = urljoin(self.url, image['href'])

        return Event(
            event_name=event_name,
            event_date=event_date,
            event_time=event_time,
            venue=self.venue_name,
            link=link,
            source_event_id=event_id,
            description=description,
            image_url=image_url,
        ), event_id
