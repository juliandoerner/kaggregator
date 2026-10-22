"""
P8 (p-acht.org) Scraper for KA Events.

Scrapes events from https://p-acht.org/, a self-managed DIY venue in Karlsruhe.
"""

import json
import re
from datetime import datetime
from typing import Optional

import pytz

from ka_events.base import BaseScraper, Event


BERLIN_TZ = pytz.timezone("Europe/Berlin")

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class PachtScraper(BaseScraper):
    """Scraper for P8 (p-acht.org) events."""

    name = "pacht"
    url = "https://p-acht.org/"

    def fetch_events(self) -> list[Event]:
        """Fetch events embedded in the homepage's Next.js data payload."""
        response = self.fetch(self.url)

        next_data = self._extract_next_data(response.text)
        if not next_data:
            return []

        event_list_data = (
            next_data.get('props', {})
            .get('pageProps', {})
            .get('eventListData', {})
        )

        events = []
        for location_events in event_list_data.values():
            for item in location_events:
                event = self._parse_event(item)
                if event:
                    events.append(event)

        return events

    def _extract_next_data(self, html: str) -> Optional[dict]:
        """Extract and parse the __NEXT_DATA__ JSON blob embedded in the page."""
        match = NEXT_DATA_PATTERN.search(html)
        if not match:
            return None

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _parse_event(self, item: dict) -> Optional[Event]:
        """Convert a single eventListData entry into an Event."""
        event_name = (item.get('name') or '').strip()
        date_from = item.get('dateFrom')
        slug = item.get('slug')

        if not event_name or not date_from or not slug:
            return None

        # dateFrom is UTC ISO8601, e.g. "2026-07-31T18:00:00.000Z"
        try:
            utc_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        except ValueError:
            return None

        local_dt = utc_dt.astimezone(BERLIN_TZ)

        venue = item.get('location', {}).get('name') or 'P8'

        return Event(
            event_name=event_name,
            event_date=local_dt.strftime('%Y-%m-%d'),
            event_time=local_dt.strftime('%H:%M'),
            venue=venue,
            link=f"{self.url}events/{slug}",
            # The CMS id is stable across renames; the slug is not.
            source_event_id=item.get('id') or slug,
        )
