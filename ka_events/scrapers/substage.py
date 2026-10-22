"""
Substage Karlsruhe Scraper.

Scrapes live events from https://substage.de/programm/
The site uses AJAX to load events from a PHP endpoint.
We filter by type "live" to get only concerts.
"""

import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ka_events.base import BaseScraper, Event


class SubstageScraper(BaseScraper):
    """Scraper for Substage Karlsruhe live events."""

    name = "substage"
    url = "https://substage.de/programm/"
    base_url = "https://substage.de"
    api_url = "https://substage.de/includes/programm_uebersicht_load.php"

    def fetch_events(self) -> list[Event]:
        """Fetch all live events from Substage."""
        events = []

        # POST request to get events filtered by type "live"
        response = self.post(
            self.api_url,
            data={
                "von": 0,
                "anzahl": 50000,
                "zeitraum": "",
                "typ": "live",  # Filter for live events only
                "location": "",
                "id": 2
            },
        )

        soup = BeautifulSoup(response.text, 'lxml')

        # Find all event elements
        for event_div in soup.find_all('div', class_='mod_kalender_element'):
            event_data = self._parse_event(event_div)
            if event_data:
                events.append(event_data)

        return events

    def _parse_event(self, event_div: BeautifulSoup) -> Optional[Event]:
        """Parse a single event from its HTML element."""
        # Extract date column
        date_col = event_div.find('div', class_='mod_kalender_date')
        if not date_col:
            return None  # type: ignore

        # Get date string (e.g., "11.07.26")
        date_elem = date_col.find('h2', class_='mod_kalender_datum')
        if not date_elem:
            return None

        date_str = date_elem.get_text(strip=True)
        event_date = self._parse_date(date_str)
        if not event_date:
            return None

        # Extract time (e.g., "Beginn: 21:00 Uhr")
        event_time = None
        for div in date_col.find_all('div'):
            text = div.get_text(strip=True)
            if text.startswith('Beginn:'):
                # Parse "Beginn: 21:00 Uhr" -> "21:00"
                time_match = re.search(r'(\d{2}:\d{2})', text)
                if time_match:
                    event_time = time_match.group(1)
                break

        # Extract title from title column (h2 element)
        title_col = event_div.find('div', class_='mod_kalender_title_txt')
        if not title_col:
            return None

        h2 = title_col.find('h2')
        event_name = h2.get_text(strip=True) if h2 else "Unknown"

        # Extract links from entire event div
        # Prefer external ticket links (reservix.de), fallback to internal programm page
        all_links = event_div.find_all('a', href=True)
        full_link = ""
        for link in all_links:
            href = link.get('href', '')
            if href.startswith('http'):
                # External link (e.g., reservix ticket link) - prefer this
                full_link = href
                break

        # If no external link found, use internal programm page
        if not full_link:
            for link in all_links:
                href = link.get('href', '')
                if href.startswith('programm/'):
                    full_link = f"{self.base_url}/{href}"
                    break

        # Extract location (e.g., "Halle", "Minestrone")
        location = None
        for div in date_col.find_all('div'):
            text = div.get_text(strip=True)
            if text.startswith('Location:'):
                # Parse "Location: Halle" or "Location: Minestrone / "
                location = text.replace('Location:', '').strip().rstrip('/')
                break

        if not location:
            location = "Halle"  # Default location

        # Add "Substage - " prefix to venue
        venue = f"Substage - {location}"

        return Event(
            event_name=event_name,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            link=full_link,
            # The API is queried with typ="live", so everything returned is a
            # concert by construction.
            category="Live",
        )

    def _parse_date(self, date_str: str) -> Optional[str]:
        """
        Parse German date format DD.MM.YY to YYYY-MM-DD.

        Examples:
            "11.07.26" -> "2026-07-11"
            "01.08.26" -> "2026-08-01"
        """
        match = re.match(r'(\d{2})\.(\d{2})\.(\d{2})', date_str)
        if not match:
            return None

        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))

        # Assume 20xx for years (e.g., 26 -> 2026)
        year += 2000

        try:
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return None
