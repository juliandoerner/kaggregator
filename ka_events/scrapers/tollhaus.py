"""
Tollhaus Karlsruhe Scraper

Scrapes events from https://www.tollhaus.de/

Venue: Kulturzentrum Tollhaus Karlsruhe - Rintheimer Straße 22b, 76131 Karlsruhe

Note: The ticket system (tickets.tollhaus.de) is a SPA that returns HTTP 204 without JS rendering.
We scrape the main site which lists events with links to the ticket system.
"""

from bs4 import BeautifulSoup
from datetime import datetime
import re

from ka_events.base import BaseScraper, Event


class TollhausScraper(BaseScraper):
    name = "tollhaus"
    url = "https://www.tollhaus.de/"

    # Categories to include (based on user confirmation)
    KEEP_CATEGORIES = {
        "Konzert",
        "Kabarett",
        "Comedy",
        "Theater",
        "Party",
    }

    def fetch_events(self) -> list[Event]:
        """Fetch events from Tollhaus website."""
        response = self.fetch(self.url)

        soup = BeautifulSoup(response.text, 'lxml')
        events = []

        # Find all links to ticket system
        # Pattern: https://tickets.tollhaus.de/catalog/tickets/{id}-tickets-{slug}
        links = soup.find_all('a', href=True)

        seen_links = set()

        for link in links:
            href = link.get('href', '')

            # Only consider ticket links
            if 'tickets.tollhaus.de/catalog/tickets/' not in href:
                continue

            # Skip duplicates
            if href in seen_links:
                continue
            seen_links.add(href)

            # Skip gift certificates
            if 'gutschein' in href.lower():
                continue

            try:
                event_data = self._parse_ticket_link(link, href)
                if event_data:
                    events.append(event_data)
            except Exception as e:
                print(f"Error parsing Tollhaus event: {e}")
                continue

        return events

    def _parse_ticket_link(self, link_elem, href: str) -> Event | None:
        """Parse event from ticket link."""

        # Get link text which contains event info
        link_text = link_elem.get_text(strip=True)

        # Skip generic text like "Programm" or "Infos & Tickets"
        if not link_text or len(link_text) < 10:
            return None

        if any(x in link_text.lower() for x in ['programm', 'infos & tickets', 'gutscheine', 'bequem hier']):
            return None

        # Parse date and name from link text
        # Format: "07.07.26 // JAN GARBAREK GROUP" or "13.09.2026 // SYBILLE BULLATSCHEK"
        event_date = None
        event_time = "20:00"  # Default time, not available in link text
        event_name = link_text

        # Try to extract date pattern (DD.MM.YY or DD.MM.YYYY)
        date_match = re.match(r'^(\d{1,2})\.(\d{2})\.(\d{2,4})\s*//\s*(.+)$', link_text)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year_str = date_match.group(3)
            event_name = date_match.group(4).strip()

            # Convert 2-digit year to 4-digit
            if len(year_str) == 2:
                year = int('20' + year_str) if int(year_str) < 50 else int('19' + year_str)
            else:
                year = int(year_str)

            try:
                dt = datetime(year, month, day)
                event_date = dt.strftime('%Y-%m-%d')
            except ValueError:
                pass

        # If no date found in text, try to extract from URL
        if not event_date:
            # URL pattern: /catalog/tickets/{id}-tickets-{slug}-{date}
            url_date_match = re.search(r'am-(\d{2})-(\d{2})-(\d{4})', href)
            if url_date_match:
                day = int(url_date_match.group(1))
                month = int(url_date_match.group(2))
                year = int(url_date_match.group(3))
                try:
                    dt = datetime(year, month, day)
                    event_date = dt.strftime('%Y-%m-%d')
                except ValueError:
                    pass

        if not event_date:
            return None

        # Clean up event name
        # Remove "AUSVERKAUFT" suffix
        event_name = re.sub(r'\s*–\s*AUSVERKAUFT$', '', event_name, flags=re.IGNORECASE)
        event_name = event_name.strip()

        # Extract venue from URL context (some events at Zeltival)
        venue = "Tollhaus"
        if 'zeltival' in href.lower() or 'zeltival' in event_name.lower():
            venue = "Tollhaus @ Zeltival"

        # Ticket URLs look like /catalog/tickets/12345-tickets-<slug>; the
        # numeric id is stable even when the slug or date changes.
        ticket_id = re.search(r'/catalog/tickets/(\d+)', href)

        return Event(
            event_name=event_name,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            link=href,
            source_event_id=ticket_id.group(1) if ticket_id else None,
        )
