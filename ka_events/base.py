"""
Event model and the base class every venue scraper builds on.
"""

import hashlib
import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


class Event:
    """A single event.

    Dates and times are **local wall-clock time in Europe/Berlin**, the way the
    venue advertises them: `event_date` as YYYY-MM-DD, `event_time` as HH:MM or
    None. A scraper whose source publishes UTC (P8, jubez) converts before
    constructing an Event; this contract used to be implicit and undocumented.

    The optional fields are populated where the source provides them cheaply.
    They were previously parsed by several scrapers and then discarded.
    """

    def __init__(
        self,
        event_name: str,
        event_date: str,
        venue: str,
        link: str,
        event_time: Optional[str] = None,
        *,
        source_event_id: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        image_url: Optional[str] = None,
        price: Optional[str] = None,
    ):
        self.event_name = event_name          # e.g. "Summer Concert"
        self.event_date = event_date          # e.g. "2026-07-15"
        self.event_time = event_time          # e.g. "20:00"
        self.venue = venue
        self.link = link

        #: Stable identifier from the source site, when it has one (P8 slugs,
        #: jubez GraphQL ids, Stadtmitte anchors). Preferred for identity.
        self.source_event_id = source_event_id
        self.description = description
        self.category = category
        self.image_url = image_url
        self.price = price

    def generate_id(self, scraper_source: Optional[str] = None) -> str:
        """Stable primary key for this event.

        Prefers the source's own identifier, namespaced by scraper. That is far
        more durable than the previous scheme, which hashed date|venue|link:
        it outsourced uniqueness to `link` (two Stadtmitte events on one day
        share a page, and only an added anchor fragment kept them apart) and
        changed every ID whenever a venue restructured its URLs.

        Falls back to the old hash for sources that expose no id of their own.
        """
        if self.source_event_id:
            key = f"{scraper_source or self.venue}|{self.source_event_id}"
        else:
            key = f"{self.event_date}|{self.venue}|{self.link}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            'event_name': self.event_name,
            'event_date': self.event_date,
            'event_time': self.event_time,
            'venue': self.venue,
            'link': self.link,
            'source_event_id': self.source_event_id,
            'description': self.description,
            'category': self.category,
            'image_url': self.image_url,
            'price': self.price,
        }


class BaseScraper:
    """Base class for all scrapers.

    Subclasses implement `fetch_events()` and use `self.fetch()` / `self.post()`
    for HTTP, which gives every scraper the same User-Agent, timeout, retry
    policy and connection reuse. Previously each scraper called `requests.get`
    directly with a repeated literal timeout, and only two of eight sent a
    User-Agent at all - both of them impersonating Chrome, which was never
    necessary (both sites serve an honest bot UA fine).
    """

    name: str = "base"

    #: Identifies the crawler honestly, so venue operators can see who we are.
    USER_AGENT = "KAEventsBot/1.0 (Karlsruhe event aggregator; contact via site operator)"
    TIMEOUT = 30
    #: Retries apply to connection errors and 5xx, not to 4xx.
    MAX_RETRIES = 2
    BACKOFF_FACTOR = 0.5

    def __init__(self):
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        """Lazily built session, reused across a scraper's requests.

        Matters most for Stadtmitte, which fetches twelve month pages per run.
        """
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({'User-Agent': self.USER_AGENT})

        retry = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.BACKOFF_FACTOR,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({'GET', 'POST'}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Single seam for all scraper HTTP.

        Tests and `scripts/record_fixtures.py` patch this one method rather
        than the requests module.
        """
        kwargs.setdefault('timeout', self.TIMEOUT)
        logger.debug("[%s] %s %s", self.name, method, url)
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def fetch(self, url: str, **kwargs) -> requests.Response:
        """GET a URL, raising on HTTP errors."""
        return self._request('GET', url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST to a URL, raising on HTTP errors."""
        return self._request('POST', url, **kwargs)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def fetch_events(self) -> list[Event]:
        """Fetch events from the source. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement fetch_events")
