"""
jubez Scraper for KA Events.

Scrapes events from https://jubez.de/, a youth arts and culture center at
Kronenplatz in Karlsruhe.
"""

import json
import re
from typing import Any, Optional


from ka_events.base import BaseScraper, Event


NUXT_DATA_PATTERN = re.compile(
    r'<script type="application/json" id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class JubezScraper(BaseScraper):
    """Scraper for jubez events."""

    name = "jubez"
    url = "https://jubez.de/"

    def fetch_events(self) -> list[Event]:
        """Fetch events embedded in the homepage's Nuxt data payload."""
        response = self.fetch(self.url)

        payload = self._extract_nuxt_payload(response.text)
        if not payload:
            return []

        events_connection = self._find_events_connection(payload)
        if not events_connection:
            return []

        events = []
        for edge in events_connection.get('edges', []):
            event = self._parse_event(edge.get('node', {}))
            if event:
                events.append(event)

        return events

    def _extract_nuxt_payload(self, html: str) -> Optional[Any]:
        """Extract and resolve the __NUXT_DATA__ JSON payload embedded in the page.

        Nuxt serializes this as a flat JSON array where every value (object,
        array, or primitive) gets its own slot, and any reference to it from a
        parent object/array is just that slot's integer index. Resolving it is
        a matter of recursively dereferencing those indices from the root (slot 0).
        """
        match = NUXT_DATA_PATTERN.search(html)
        if not match:
            return None

        try:
            flat = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        cache: dict = {}

        def resolve(idx):
            if idx in cache:
                return cache[idx]
            val = flat[idx]
            if isinstance(val, dict):
                result: dict = {}
                cache[idx] = result
                for k, v in val.items():
                    result[k] = resolve(v) if isinstance(v, int) else v
                return result
            elif isinstance(val, list):
                result_list: list = []
                cache[idx] = result_list
                for v in val:
                    result_list.append(resolve(v) if isinstance(v, int) else v)
                return result_list
            else:
                cache[idx] = val
                return val

        return resolve(0)

    def _find_events_connection(self, payload: Any) -> Optional[dict]:
        """Locate the events GraphQL connection ({edges, pageInfo}) within the
        resolved payload. Its parent key is a random per-build hash, so we
        search by shape instead of by name."""
        try:
            data = payload[1]['data']
        except (KeyError, IndexError, TypeError):
            return None

        for value in data.values():
            if isinstance(value, dict):
                events = value.get('events')
                if isinstance(events, dict) and 'edges' in events:
                    return events

        return None

    def _parse_event(self, node: dict) -> Optional[Event]:
        """Convert a single GraphQL Event node into an Event."""
        event_settings = node.get('eventSettings') or {}

        # Events past their cancellation are still returned by the "upcoming"
        # filter (cancellation doesn't change the date), so they must be
        # skipped explicitly rather than relying on the date filter.
        if event_settings.get('cancelled'):
            return None

        title = (node.get('title') or '').strip()
        date_start = (event_settings.get('date') or {}).get('start')
        uri = node.get('uri')

        if not title or not date_start or not uri:
            return None

        # date.start is already in local (Europe/Berlin) time: "YYYY-MM-DD HH:MM:SS"
        date_part, _, time_part = date_start.partition(' ')
        event_time = time_part[:5] if time_part else None

        location = event_settings.get('location')
        venue = location['title'] if location else 'jubez'

        excerpt = (event_settings.get('excerpt') or '').strip() or None

        image_url = None
        featured = (node.get('featuredImage') or {}).get('node') or {}
        if featured.get('sourceUrl'):
            image_url = featured['sourceUrl']

        return Event(
            event_name=title,
            event_date=date_part,
            event_time=event_time,
            venue=venue,
            link=f"https://jubez.de{uri}",
            source_event_id=node.get('id'),
            description=excerpt,
            image_url=image_url,
        )
