"""
AKK Liveschlonz Scraper for KA Events.

Scrapes only "Liveschlonz" events from https://www.akk.org/chronologie.php
"""

from bs4 import BeautifulSoup
from ka_events.base import BaseScraper, Event


class AkkLiveschlonzScraper(BaseScraper):
    """Scraper for AKK Liveschlonz events."""

    name = "akk_liveschlonz"
    url = "https://www.akk.org/chronologie.php"
    base_url = "https://www.akk.org"

    def fetch_events(self) -> list[Event]:
        """Fetch Liveschlonz events from AKK website."""
        response = self.fetch(self.url)

        soup = BeautifulSoup(response.text, 'lxml')
        events = []

        # Find all table rows with class "liveschlonz"
        for row in soup.find_all('tr', class_='liveschlonz'):
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            # Extract date and time from datetime attribute
            time_elem = cells[0].find('time')
            if not time_elem:
                continue

            datetime_str = time_elem.get('datetime', '')
            if not datetime_str:
                continue

            # Parse datetime: "2026-04-23T18:00"
            event_date = datetime_str.split('T')[0]
            event_time = datetime_str.split('T')[1] if 'T' in datetime_str else None

            # Extract event name from 3rd column link
            name_link = cells[2].find('a')
            if not name_link:
                continue

            full_name = name_link.get_text(strip=True)
            # Strip "Liveschlonz:" prefix if present
            event_name = full_name.replace('Liveschlonz:', '').strip()

            # Build link URL
            href = name_link.get('href', '')
            if href.startswith('/'):
                link = self.base_url + href
            else:
                link = href

            # Extract venue from 4th column
            venue_link = cells[3].find('a')
            venue_raw = venue_link.get_text(strip=True) if venue_link else "Unknown"

            # Use "AKK - Altes Stadion" for Altes Stadion, otherwise use raw value
            if venue_raw == "Altes Stadion":
                venue = "AKK - Altes Stadion"
            else:
                venue = venue_raw

            events.append(Event(
                event_name=event_name,
                event_date=event_date,
                event_time=event_time,
                venue=venue,
                link=link
            ))

        return events
