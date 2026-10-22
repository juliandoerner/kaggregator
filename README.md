# KA Events - Karlsruhe Event Aggregator

A plain HTML event aggregator for Karlsruhe and surrounding areas. Built with Python, Flask, and SQLite.

> **AI-assisted project:** Generative AI was used during the design,
> implementation, refactoring, testing, and documentation of this project.

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│   Scraper Service   │────▶│      SQLite DB      │
│   (Python + APS)    │     │    (shared file)    │
└─────────────────────┘     └──────────┬──────────┘
                                       │
                                       ▼
                              ┌─────────────────────┐
                              │    Web Service      │
                              │      (Flask)        │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   Plain HTML/CSS    │
                              │    (no JS needed)   │
                              └─────────────────────┘
```

## Quick Start

### Development (Local)

```bash
# Run the development script (creates venv, installs deps, starts services)
./scripts/dev.sh

# Or manually:
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export DATABASE_PATH=./data/events.db

# Start scraper service (terminal 1)
ka-events-scraper

# Start web service (terminal 2)
python -m flask --app ka_events.web.app run --port 5000
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| web-service | 5000 | Flask web application |
| scraper-service | - | Background scraper (runs every 6 hours) |

## Project Structure

```
ka-events/
├── pyproject.toml          # Package + dependency definition (one install covers both services)
├── config.yaml             # Enabled scrapers + venue metadata
├── .env                    # Environment variables (gitignored; see .env.example)
├── data/                   # SQLite database (gitignored)
│
├── ka_events/              # The application, one importable package
│   ├── database.py         # Schema + all DB access (single source of truth)
│   ├── base.py             # Event model, BaseScraper
│   ├── registry.py         # Scraper auto-discovery
│   ├── health.py           # Judges each run before storing/deleting
│   ├── notifications.py    # SMTP alert mail (stdlib only)
│   ├── scraper_main.py     # Scraper entry point (`ka-events-scraper`)
│   ├── scrapers/
│   │   ├── SCRAPER_DECISIONS.md   # Per-venue technique + filtering notes
│   │   ├── akk.py, jubez.py, kohi.py, pacht.py,
│   │   ├── stadtmitte.py, substage.py, tollhaus.py, z10.py
│   │   ├── staatstheater.py       # Disabled
│   │   └── dummy.py               # Test scraper
│   └── web/
│       ├── app.py          # Flask application
│       ├── templates/index.html
│       └── static/style.css
│
├── scripts/
│   ├── dev.sh                    # Local dev setup + run both services
│   ├── cleanup_past_events.py    # Delete past events (--dry-run, --vacuum)
│   ├── record_fixtures.py        # Refresh scraper test fixtures
│   └── test_alert_email.py       # Verify SMTP alert settings work
│
└── tests/
    ├── fixtures/           # Recorded HTTP responses + expected parse output
    ├── test_base.py        # Event model, BaseScraper
    ├── test_config.py      # Configuration validation
    ├── test_database.py    # Database operations
    ├── test_health.py      # Breakage detection, anti-data-loss guard
    ├── test_integration.py # Multi-scraper workflows
    ├── test_registry.py    # Scraper discovery
    ├── test_scrapers.py    # Parsing logic (offline)
    ├── test_scraper_fixtures.py  # Replay fixtures, assert output unchanged
    └── test_web_service.py # Flask routes and API
```

## Adding a New Scraper

1. Create a new file in `ka_events/scrapers/`:

```python
from ka_events.base import BaseScraper, Event

class MyVenueScraper(BaseScraper):
    name = "myvenue"

    def fetch_events(self) -> list[Event]:
        # Implement scraping logic here
        return [Event(
            event_name="Sample Event",
            event_date="2026-07-20",   # YYYY-MM-DD
            event_time="20:00",        # HH:MM, optional
            venue="My Venue Karlsruhe",
            link="https://myvenue.example.com/events/sample"
        )]
```

2. Add the scraper's `name` to `scrapers.enabled` in `config.yaml`, and a `venues.<name>` entry giving the label shown in the site's location filter. `config.yaml` is authoritative — there is no second list in code.

3. Document the scraping technique and any category filtering decisions in `ka_events/scrapers/SCRAPER_DECISIONS.md`.

4. Restart the local services:
```bash
./scripts/dev.sh
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main HTML page |
| `/api/events` | GET | Upcoming events as JSON (today and future) |
| `/api/events/all` | GET | All events as JSON (including past) |
| `/api/status` | GET | Scraper status |
| `/health` | GET | Service health check (503 if the DB is unreadable) |

## Configuration

Environment variables (via `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `./data/events.db` | Path to SQLite database |
| `SCRAPE_INTERVAL` | `21600` | Seconds between scraper runs |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CONFIG_PATH` | `./config.yaml` | Location of config.yaml |
| `FLASK_ENV` | `production` | Flask environment |
| `SMTP_HOST` | *(empty)* | SMTP server for alerts. Empty disables mail |
| `SMTP_PORT` | `587` | SMTP port (`465` switches to implicit SSL) |
| `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | SMTP credentials |
| `SMTP_USE_TLS` | `true` | STARTTLS on non-465 ports |
| `ALERT_EMAIL_TO` | *(empty)* | Alert recipient |
| `ALERT_EMAIL_FROM` | `SMTP_USER` | Alert sender |
| `ALERT_AFTER_FAILURES` | `2` | Consecutive bad runs before mailing |
| `SCRAPER_CONCURRENCY` | `4` | Venues fetched in parallel (never parallel within one venue) |

## Design Philosophy

- **Plain HTML**: No JavaScript required, works everywhere
- **Minimal CSS**: Fast loading, brutalist design
- **Separation of Concerns**: Scraper and web service are independent
- **Shared Database Module**: `ka_events/database.py` is the source of truth
- **Simple Storage**: SQLite with a normalized event schema
- **Past events are archived**: cleanup only prunes upcoming events, so `/api/events/all` is a real history

## Scraper Health Monitoring

Venue websites change, and the usual result is a *silent* break: selectors stop
matching, `fetch_events()` returns an empty list, and nothing raises. Left
unguarded that is worse than a crash, because orphan cleanup reads "scraped
nothing" as "the site removed everything" and deletes the venue's events.

Every run is therefore judged before anything is written or deleted
(`ka_events/health.py`):

| Verdict | Meaning | Effect |
|---------|---------|--------|
| `healthy` | Looks normal | Stored, orphan cleanup runs |
| `suspicious` | Scraped 0 while events are stored, or would delete >50% of them | Events kept, **cleanup skipped** |
| `failed` | Data itself is malformed, or the scraper raised | Nothing written |

Checks are generic, so they need no per-scraper tuning: empty names or links,
unparseable or absurd dates, malformed times, and "every event landed on the
same date" (a collapsed date parse).

Alerts are sent on health **transitions**, not on every run — a scraper that
stays broken mails once, plus once more when it recovers. `ALERT_AFTER_FAILURES`
(default 2) rides out transient site outages.

If SMTP is unconfigured the guard still works; problems are just logged. Verify
your mail settings without waiting for a real breakage:

```bash
set -a && source .env && set +a && python scripts/test_alert_email.py
```

Current health is visible at `/api/status` (`last_status`,
`consecutive_failures`, `alerted`), and per-run history is kept in the
`scraper_runs` table.

> **Note:** a run scraping 0 events is not always a break — jubez legitimately
> had a 3-month empty stretch. That is why zero results park the data rather
> than delete it: if the emptiness is real, the stale events are all in the past
> and `/` hides them anyway.

## Maintenance

Delete past events from the database (useful for keeping it small over time):

```bash
python scripts/cleanup_past_events.py --dry-run   # preview what would be deleted
python scripts/cleanup_past_events.py --vacuum    # delete and reclaim disk space
```

## Testing

Run all tests (from the repo root; pytest config lives in `pyproject.toml`):

```bash
pytest tests/ -v
```

Test coverage by category:
- **Base Tests** (`test_base.py`): Event model, BaseScraper interface
- **Config Tests** (`test_config.py`): YAML validation, environment variables
- **Database Tests** (`test_database.py`): CRUD operations, orphan cleanup
- **Integration Tests** (`test_integration.py`): Multi-scraper workflows
- **Registry Tests** (`test_registry.py`): Scraper discovery and imports
- **Scraper Tests** (`test_scrapers.py`): Date/time parsing and month iteration (no network)
- **Health Tests** (`test_health.py`): Breakage detection, the anti-data-loss guard, alert formatting
- **Web Service Tests** (`test_web_service.py`): Flask routes and API endpoints

## License

MIT
