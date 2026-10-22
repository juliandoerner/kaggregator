"""
KOHI Kulturraum Scraper

Scrapes events from https://kohi.de/

Venue: KOHI Kulturraum Karlsruhe e.V. - Werderstraße 47, 76137 Karlsruhe

Categories to keep: Konzert, Songslam, Literatur, Theater, Poetry-Slam, Open Mic
Categories to skip: Sonstiges, Querfunk (radio show), Gattung (other)
"""

from bs4 import BeautifulSoup
from datetime import datetime
import re

from ka_events.base import BaseScraper, Event


class KohiScraper(BaseScraper):
    name = "kohi"
    url = "https://kohi.de/"

    # Categories to include
    KEEP_CATEGORIES = {
        "Konzert",
        "Songslam",
        "Literatur",
        "Theater",
        "Poetry-Slam",
        "Open Mic",
    }

    # Categories to exclude
    SKIP_CATEGORIES = {
        "Sonstiges",
        "Querfunk",
        "Gattung",
    }

    def fetch_events(self) -> list[Event]:
        """Fetch events from KOHI website."""
        response = self.fetch(self.url)

        soup = BeautifulSoup(response.text, 'lxml')
        events = []

        # Find all event articles
        articles = soup.find_all('article', class_='event')

        for article in articles:
            try:
                event_data = self._parse_event_article(article)
                if event_data:
                    events.append(event_data)
            except Exception as e:
                print(f"Error parsing KOHI event: {e}")
                continue

        return events

    def _parse_event_article(self, article) -> Event | None:
        """Parse a single event article element."""

        # Extract datetime from <time datetime=""> attribute
        time_elem = article.find('time', datetime=True)
        if not time_elem:
            return None

        datetime_str = time_elem.get('datetime', '')
        if not datetime_str:
            return None

        # Parse ISO format datetime (e.g., "2026-07-06T20:00")
        try:
            dt = datetime.fromisoformat(datetime_str)
            event_date = dt.strftime('%Y-%m-%d')
            event_time = dt.strftime('%H:%M')
        except ValueError:
            return None

        # Extract event name from <h2> in flexbox__headline
        headline = article.find('div', class_='flexbox__headline')
        if not headline:
            return None

        h2 = headline.find('h2')
        if not h2:
            return None

        # Get event name, clean up whitespace
        event_name = h2.get_text(separator=' ', strip=True)
        # Remove origin info like "DE-Hildesheim" or "CA-Toronto" from name
        # Pattern: "ARTIST NAME DE-City" or "ARTIST + OTHER CA-City"
        event_name = re.sub(r'\s+DE-[^\s]+', '', event_name)
        event_name = re.sub(r'\s+CA-[^\s]+', '', event_name)
        event_name = re.sub(r'\s+/[A-Z]{2}-[^\s]+', '', event_name)  # Also handle /XX-City patterns
        # Clean up multiple spaces and slashes
        event_name = re.sub(r'\s*/\s*', ' ', event_name)
        event_name = re.sub(r'\s+', ' ', event_name)
        event_name = event_name.strip()

        if not event_name:
            return None

        # Extract category from <div class="gattung">
        gattung = article.find('div', class_='gattung')
        if not gattung:
            return None

        category = gattung.get_text(strip=True)

        # Filter by category
        if category in self.SKIP_CATEGORIES:
            return None

        if category not in self.KEEP_CATEGORIES:
            # If it's not explicitly in keep list but also not in skip, include it
            # This handles potential new categories
            pass

        # Build event link from page URL + anchor ID
        article_id = article.get('id', '')
        if article_id:
            event_link = f"{self.url}termin?event={article_id}"
        else:
            event_link = self.url

        # Determine venue - check for external locations
        venue = "KOHI"
        ort_elem = article.find('span', class_='eventOrt')
        if ort_elem:
            ort_text = ort_elem.get_text(strip=True).lower()
            if 'jubez' in ort_text:
                venue = "KOHI @ Jubez"
            elif 'tollhaus' in ort_text:
                venue = "KOHI @ Tollhaus"
            elif 'querfunk' in ort_text:
                venue = "KOHI @ Querfunk"
            elif 'werderplatz' in ort_text.lower():
                venue = "KOHI @ Werderplatz"

        return Event(
            event_name=event_name,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            link=event_link,
            # Parsed above for filtering; previously discarded.
            category=category,
        )
