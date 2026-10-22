"""
Staatstheater Karlsruhe Scraper.

Scrapes events from https://www.staatstheater-karlsruhe.de/spielplan/
The site uses a left sidebar navigation with individual month pages.
Events are structured in div rows with category, title, venue, and price info.
"""

import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ka_events.base import BaseScraper, Event


# Categories to keep (excludes: Kunst + Vermittlung, Extras)
KEEP_CATEGORIES = {
    'Oper',
    'Ballett',
    'Konzert',
    'Schauspiel',
    'Junges Staatstheater',
    'Digitaltheater',
}


class StaatstheaterScraper(BaseScraper):
    """Scraper for Badisches Staatstheater Karlsruhe."""

    name = "staatstheater"
    url = "https://www.staatstheater-karlsruhe.de/spielplan/"
    base_url = "https://www.staatstheater-karlsruhe.de"

    def fetch_events(self) -> list[Event]:
        """Fetch all events from the main Spielplan page and month sub-pages."""
        events = []
        seen_ids = set()

        # First, fetch the main page to get current day's events and month links
        response = self.fetch(self.url)

        soup = BeautifulSoup(response.text, 'lxml')

        # Parse events from main page (current day)
        for event in self._parse_events(soup):
            event_key = (event.event_name, event.event_date, event.event_time)
            if event_key not in seen_ids:
                seen_ids.add(event_key)
                events.append(event)

        # Find month navigation links in left sidebar
        month_links = self._extract_month_links(soup)

        # Fetch each month page and parse events
        for month_url in month_links:
            try:
                full_url = month_url if month_url.startswith('http') else f"{self.base_url}/{month_url}"
                response = self.fetch(full_url)
                response.raise_for_status()
                month_soup = BeautifulSoup(response.text, 'lxml')
                for event in self._parse_events(month_soup):
                    event_key = (event.event_name, event.event_date, event.event_time)
                    if event_key not in seen_ids:
                        seen_ids.add(event_key)
                        events.append(event)
            except Exception as e:
                print(f"Error fetching {month_url}: {e}")
                continue

        return events

    def _extract_month_links(self, soup: BeautifulSoup) -> list[str]:
        """Extract month navigation links from left sidebar."""
        month_links = []

        # Find nav links that match pattern spielplan/<month>/ or spielplan/<month>-<year>/
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            # Match patterns like "spielplan/september/", "spielplan/juli-26/"
            if re.search(r'spielplan/[a-zäöü]+(-\d+)?/', href, re.IGNORECASE):
                # Avoid duplicates and the main spielplan page itself
                if href != 'spielplan/' and href not in month_links:
                    month_links.append(href)

        return month_links

    def _parse_events(self, soup: BeautifulSoup) -> list[Event]:
        """Parse events from a page's HTML."""
        events = []
        current_date = None

        # Find all event rows
        for row in soup.find_all('div', class_='row row-divider'):
            event_id = row.get('id', '')
            if not event_id:
                continue

            # Check for date header before this event
            prev_sibling = row.find_previous_sibling(class_='row sticky-date')
            if prev_sibling:
                date_text = prev_sibling.get_text(strip=True)
                # Parse German date format: "Montag, 6.7." or "Samstag, 19.9."
                current_date = self._parse_date_header(date_text)

            if not current_date:
                continue

            # Extract event data from columns
            cols = row.find_all('div', class_=re.compile(r'col-(12|md-)'))
            if len(cols) < 3:
                continue

            # Column 1: Time and Category
            col1 = cols[0]
            time_elem = col1.find('b')
            event_time = None
            if time_elem:
                time_match = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', time_elem.get_text())
                if time_match:
                    event_time = time_match.group(1)
                else:
                    # Try single time format
                    time_match = re.search(r'(\d{1,2}:\d{2})', time_elem.get_text())
                    if time_match:
                        event_time = time_match.group(1)

            # Get category (text after time, usually in a <p> tag)
            category = None
            for p_tag in col1.find_all('p'):
                text = p_tag.get_text(strip=True)
                if text in KEEP_CATEGORIES:
                    category = text
                    break

            # Skip events without a matching category
            if not category:
                continue

            # Column 2: Title and description
            col2 = cols[1]
            title_link = col2.find('h3', class_=re.compile(r'h3')).find('a', href=True)
            if not title_link:
                continue

            event_name = title_link.get_text(strip=True)
            event_link = title_link.get('href', '')
            full_event_link = f"{self.base_url}/{event_link}" if event_link else ""

            # Column 3: Venue and ticket info
            col3 = cols[2]
            venue_link = col3.find('a', href=re.compile(r'spielorte'))
            if venue_link:
                venue_raw = venue_link.get_text(strip=True)
            else:
                # Try to find venue in p.sp_orte
                venue_elem = col3.find('p', class_='sp_orte')
                venue_raw = venue_elem.get_text(strip=True) if venue_elem else "Staatstheater Karlsruhe"

            # Add "Staatstheater - " prefix to venue
            venue = f"Staatstheater - {venue_raw}"

            events.append(Event(
                event_name=event_name,
                event_date=current_date,
                event_time=event_time,
                venue=venue,
                link=full_event_link
            ))

        return events

    def _parse_date_header(self, date_text: str) -> Optional[str]:
        """
        Parse German date header like "Montag, 6.7." or "Samstag, 19.9."

        Returns date in YYYY-MM-DD format or None if parsing fails.
        """
        # Extract day.month pattern
        match = re.search(r'(\d{1,2})\.(\d{1,2})\.', date_text)
        if not match:
            return None

        day = int(match.group(1))
        month = int(match.group(2))
        year = datetime.now().year

        # Handle year boundary (if month is in the past, it might be next year)
        current_month = datetime.now().month
        if month < current_month:
            year += 1

        try:
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return None
