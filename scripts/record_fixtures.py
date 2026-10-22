#!/usr/bin/env python3
"""
Record scraper HTTP fixtures and their expected parse output.

Runs each enabled scraper against the live sites once, capturing every HTTP
response in order, then stores the parsed result alongside them. The test suite
replays these offline, so a parsing regression is caught by CI without touching
the network.

Responses are replayed **in request order** rather than matched by URL, because
some scrapers build URLs from the current date (Stadtmitte derives a timestamp
per month), which would never match a recorded URL again.

Usage:
    python scripts/record_fixtures.py              # all scrapers
    python scripts/record_fixtures.py z10 kohi     # just these

Re-run this when a venue changes its site and you have updated the scraper, so
the fixture reflects the new reality.
"""

import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from ka_events.base import BaseScraper
from ka_events.registry import ScraperRegistry

FIXTURE_ROOT = os.path.join(PROJECT_ROOT, 'tests', 'fixtures')

# Scrapers worth recording: the enabled ones. `dummy` needs no fixture (it is
# static) and `staatstheater` is disabled and infers the year from the current
# month, so its parsed output is not stable enough to pin.
SCRAPERS = [
    'akk_liveschlonz', 'z10', 'substage', 'kohi',
    'tollhaus', 'pacht', 'jubez', 'stadtmitte',
]


class Recorder:
    """Wraps BaseScraper._request to record responses in request order.

    This is the same seam the replay tests patch, so what gets recorded is
    exactly what gets replayed.
    """

    def __init__(self):
        self.calls = []
        self._original = BaseScraper._request

    def __enter__(self):
        original = self._original
        calls = self.calls

        def wrapper(scraper_self, method, url, **kwargs):
            response = original(scraper_self, method, url, **kwargs)
            calls.append({
                'method': method,
                'url': url,
                'status_code': response.status_code,
                'body': response.text,
            })
            return response

        BaseScraper._request = wrapper
        return self

    def __exit__(self, *exc):
        BaseScraper._request = self._original


def record(name, scraper):
    target = os.path.join(FIXTURE_ROOT, name)
    os.makedirs(target, exist_ok=True)

    with Recorder() as recorder:
        events = scraper.fetch_events()

    manifest = []
    for index, call in enumerate(recorder.calls, start=1):
        filename = f"{index:03d}.txt"
        with open(os.path.join(target, filename), 'w', encoding='utf-8') as handle:
            handle.write(call['body'])
        manifest.append({
            'file': filename,
            'method': call['method'],
            'url': call['url'],
            'status_code': call['status_code'],
        })

    with open(os.path.join(target, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)

    expected = [
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
            'has_description': bool(e.description),
        }
        for e in events
    ]
    with open(os.path.join(target, 'expected.json'), 'w', encoding='utf-8') as handle:
        json.dump(expected, handle, indent=2, ensure_ascii=False)

    size = sum(len(c['body']) for c in recorder.calls) / 1024
    print(f"  {name:18} {len(recorder.calls):>2} response(s), "
          f"{len(events):>3} events, {size:>7.0f} KB")


def main():
    requested = sys.argv[1:] or SCRAPERS
    registry = ScraperRegistry()

    print(f"Recording fixtures into {os.path.relpath(FIXTURE_ROOT, PROJECT_ROOT)}/\n")
    for name in requested:
        try:
            record(name, registry.get_scraper(name))
        except Exception as exc:
            print(f"  {name:18} FAILED: {type(exc).__name__}: {exc}")
            return 1
    print("\nDone. Review the diff before committing - a changed expected.json "
          "means the venue site changed.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
