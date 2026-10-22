"""
Dummy scraper for testing KA Events.
Returns sample events with minimal data: Date, Time, Event Name, Venue, Link.
"""

from ka_events.base import BaseScraper, Event


class DummyScraper(BaseScraper):
    """Dummy scraper that returns sample events."""

    name = "dummy"

    def fetch_events(self) -> list[Event]:
        """Return sample events."""
        return [
            Event(
                event_name="Summer Rock Night",
                event_date="2026-07-10",
                event_time="20:00",
                venue="Substage Karlsruhe",
                link="https://substage.de/event1"
            ),
            Event(
                event_name="Jazz Evening",
                event_date="2026-07-12",
                event_time="19:30",
                venue="Tollhaus Karlsruhe",
                link="https://tollhaus.de/event2"
            ),
            Event(
                event_name="Open Air Festival",
                event_date="2026-07-15",
                event_time="21:00",
                venue="Stadtmitte Karlsruhe",
                link="https://stadtmitte-ka.de/event3"
            ),
            Event(
                event_name="Indie Concert",
                event_date="2026-07-18",
                event_time="20:00",
                venue="Kulturzentrum Tempelherrenhaus",
                link="https://tempelherrenhaus.de/event4"
            ),
            Event(
                event_name="Pool Party",
                event_date="2026-07-20",
                event_time="19:00",
                venue="Das Bad am Beck",
                link="https://dasbad-ambeck.de/event5"
            )
        ]
