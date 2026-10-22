"""KA Events - event aggregator for Karlsruhe.

One package with two entry points: `ka_events.scraper_main` (scheduled scraper)
and `ka_events.web.app` (Flask site). They share `ka_events.database`, which is
the single source of truth for the schema.
"""

__version__ = "1.0.0"
