"""
Z10 Scraper for KA Events.

Scrapes music, theater, and performance events from https://z10.info/termineics
Filters out chess (Krümel), workshops, info sessions, and other non-music events.
"""

import re
import json
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ka_events.base import BaseScraper, Event


# Categories to keep (music, theater, performance)
KEEP_CATEGORIES = {
    'Konzert',      # Concerts
    'Party',        # Parties
    'Theater',      # Theater
    'Kabarett',     # Cabaret
    'Lesung',       # Readings
}


class Z10Scraper(BaseScraper):
    """Scraper for Z10 music and theater events."""

    name = "z10"
    url = "https://z10.info/"
    base_url = "https://z10.info"

    def fetch_events(self) -> list[Event]:
        """Fetch music/theater events from Z10 website."""
        response = self.fetch(self.url)

        soup = BeautifulSoup(response.text, 'lxml')
        events = []

        # Find all event containers
        for event_div in soup.find_all('div', class_='dates'):
            # Extract category from datecategory span
            category_elem = event_div.find('span', class_='datecategory')
            if not category_elem:
                continue

            # Extract category text (e.g., "(Konzert)" -> "Konzert")
            category_raw = category_elem.get_text(strip=True)
            category = category_raw.strip('()')

            # Skip if category is not in our keep list
            if category not in KEEP_CATEGORIES:
                continue

            # Extract JSON-LD data from script tag
            json_ld_script = event_div.find('script', type='application/ld+json')
            if not json_ld_script:
                continue

            try:
                json_data = json.loads(json_ld_script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            # Parse event data from JSON-LD
            event_name = json_data.get('name', '')
            if not event_name:
                continue

            # Parse startDate (format: "2026-07-17CEST22:00")
            start_date_str = json_data.get('startDate', '')
            event_date, event_time = self._parse_datetime(start_date_str)

            if not event_date:
                continue

            # Extract venue
            location = json_data.get('location', {})
            venue = location.get('name', 'Studentenzentrum Z10')

            # Extract link from URL field or build from event ID
            event_url = json_data.get('url', '')
            if not event_url:
                # Build URL from event name
                event_id = self._generate_event_id(event_name, event_date)
                event_url = f"{self.base_url}/#{event_id}"

            events.append(Event(
                event_name=event_name,
                event_date=event_date,
                event_time=event_time,
                venue=venue,
                link=event_url,
                # Already parsed above to decide whether to keep the event;
                # previously discarded.
                category=category,
                description=(json_data.get('description') or '').strip() or None,
            ))

        return events

    def _parse_datetime(self, datetime_str: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse Z10 datetime format: "2026-07-17CEST22:00" or "2026-07-17CEST22:00:00"

        Returns:
            Tuple of (date_str, time_str) or (None, None) if parsing fails
        """
        if not datetime_str:
            return None, None

        try:
            # Handle CEST/CET timezone prefix
            # Format: YYYY-MM-DDCESTHH:MM or YYYY-MM-DDCETHH:MM:SS
            match = re.match(r'(\d{4}-\d{2}-\d{2})(CEST|CET)?(\d{2}:\d{2})', datetime_str)
            if match:
                date_str = match.group(1)
                time_str = match.group(3)
                return date_str, time_str

            # Fallback: try standard ISO format
            dt = datetime.fromisoformat(datetime_str.replace('CEST', '+02:00').replace('CET', '+01:00'))
            return dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M')
        except Exception:
            return None, None

    def _generate_event_id(self, event_name: str, event_date: str) -> str:
        """Generate a deterministic event ID from name and date."""
        # Create slug from event name
        slug = re.sub(r'[^a-z0-9]+', '-', event_name.lower()).strip('-')
        # Add date for uniqueness
        date_suffix = event_date.replace('-', '')
        return f"z10_{slug}_{date_suffix}"
