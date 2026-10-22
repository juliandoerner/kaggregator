"""
Characterization tests: replay recorded HTTP responses through each scraper and
assert the parsed output still matches what was recorded.

These run entirely offline. They exist so that refactoring can prove it did not
change scraper behaviour, and so CI can catch a parsing regression introduced by
a code change (as opposed to a venue changing its site).

Responses are replayed **in request order**, not matched by URL: Stadtmitte
builds a `?timestamp=` per month from the current date, so a recorded URL would
never be requested again.

Fixtures are refreshed with `python scripts/record_fixtures.py`. A changed
`expected.json` in the diff means the venue's site changed.
"""

import json
import os

import pytest
import requests

from ka_events.base import BaseScraper
from ka_events.registry import ScraperRegistry


FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

SCRAPERS = [
    'akk_liveschlonz', 'z10', 'substage', 'kohi',
    'tollhaus', 'pacht', 'jubez', 'stadtmitte',
]


class FakeResponse:
    """Stands in for requests.Response. Scrapers only use .text and
    .raise_for_status(), so this covers the whole surface they touch."""

    def __init__(self, body, status_code=200):
        self.text = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for fixture response")


def load_fixture(name):
    directory = os.path.join(FIXTURE_ROOT, name)
    with open(os.path.join(directory, 'manifest.json'), encoding='utf-8') as handle:
        manifest = json.load(handle)
    with open(os.path.join(directory, 'expected.json'), encoding='utf-8') as handle:
        expected = json.load(handle)

    responses = []
    for entry in manifest:
        with open(os.path.join(directory, entry['file']), encoding='utf-8') as handle:
            responses.append(FakeResponse(handle.read(), entry['status_code']))
    return responses, expected


@pytest.fixture
def replay(monkeypatch):
    """Serve recorded responses in order through BaseScraper's HTTP seam.

    Patching `BaseScraper._request` rather than the requests module means the
    fixture keeps working regardless of how the session is built underneath.
    """

    def _install(responses):
        pending = list(responses)

        def _serve(self, method, url, **kwargs):
            if not pending:
                raise AssertionError(
                    "scraper made more HTTP requests than the fixture recorded"
                )
            return pending.pop(0)

        monkeypatch.setattr(BaseScraper, '_request', _serve)
        return pending

    return _install


@pytest.mark.parametrize('scraper_name', SCRAPERS)
def test_scraper_output_matches_fixture(scraper_name, replay):
    """The parsed result must be byte-identical to what was recorded."""
    responses, expected = load_fixture(scraper_name)
    remaining = replay(responses)

    scraper = ScraperRegistry().get_scraper(scraper_name)
    events = scraper.fetch_events()

    actual = [
        {
            'event_name': e.event_name,
            'event_date': e.event_date,
            'event_time': e.event_time,
            'venue': e.venue,
            'link': e.link,
            'source_event_id': e.source_event_id,
            'category': e.category,
            'image_url': e.image_url,
            'price': e.price,
            # Descriptions are long and change wording often; pin only presence.
            'has_description': bool(e.description),
        }
        for e in events
    ]

    assert actual == expected
    assert not remaining, (
        f"scraper made fewer requests than recorded "
        f"({len(remaining)} fixture response(s) unused)"
    )


@pytest.mark.parametrize('scraper_name', SCRAPERS)
def test_distinct_events_never_share_an_id(scraper_name, replay):
    """Two *different* events must never collapse into one database row.

    Identical duplicates are tolerated: KOHI genuinely lists the same event
    twice on its page, and folding those together is correct. What must never
    happen is two different events hashing alike - Stadtmitte has two unrelated
    events on 2026-08-12, and before their per-event anchor was added to the
    link they would have overwritten each other.
    """
    responses, _ = load_fixture(scraper_name)
    replay(responses)

    events = ScraperRegistry().get_scraper(scraper_name).fetch_events()

    by_id = {}
    for event in events:
        signature = (event.event_name, event.event_date, event.event_time,
                     event.venue, event.link)
        event_id = event.generate_id()
        if event_id in by_id:
            assert by_id[event_id] == signature, (
                f"{scraper_name}: two different events share ID {event_id}: "
                f"{by_id[event_id]} vs {signature}"
            )
        by_id[event_id] = signature


@pytest.mark.parametrize('scraper_name', SCRAPERS)
def test_scraper_ids_are_stable_across_runs(scraper_name, replay):
    """Replaying identical input must produce identical IDs, otherwise orphan
    cleanup would delete and reinsert everything on every run."""
    responses, _ = load_fixture(scraper_name)
    replay(responses)
    first = [e.generate_id() for e in ScraperRegistry().get_scraper(scraper_name).fetch_events()]

    responses, _ = load_fixture(scraper_name)
    replay(responses)
    second = [e.generate_id() for e in ScraperRegistry().get_scraper(scraper_name).fetch_events()]

    assert first == second, f"{scraper_name} produced unstable event IDs"


@pytest.mark.parametrize('scraper_name', SCRAPERS)
def test_scraper_output_is_well_formed(scraper_name, replay):
    """Guards the invariants the health checks rely on."""
    responses, _ = load_fixture(scraper_name)
    replay(responses)

    events = ScraperRegistry().get_scraper(scraper_name).fetch_events()

    assert events, f"{scraper_name} parsed nothing from its fixture"
    for event in events:
        assert event.event_name.strip(), "empty event name"
        assert event.link.strip(), "empty link"
        assert len(event.event_date) == 10 and event.event_date[4] == '-', \
            f"date not YYYY-MM-DD: {event.event_date!r}"
        if event.event_time is not None:
            assert len(event.event_time) == 5 and event.event_time[2] == ':', \
                f"time not HH:MM: {event.event_time!r}"
