"""
Application configuration.

`config.yaml` is the single source of truth for which scrapers run and how each
venue is labelled. It used to be documentation only - the real list lived in
ENABLED_SCRAPERS in the scraper entry point and the display names in a dict in
database.py, so one concept had three homes that were synchronised by hand.

Environment variables still win for deployment-specific values (paths,
intervals, credentials); the YAML file owns the domain configuration.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


logger = logging.getLogger(__name__)

DEFAULT_CONFIG_FILENAME = "config.yaml"


def _default_config_path() -> str:
    """Locate config.yaml: explicit env var, else the repo/working directory.
    """
    explicit = os.environ.get("CONFIG_PATH")
    if explicit:
        return explicit

    if os.path.exists(DEFAULT_CONFIG_FILENAME):
        return DEFAULT_CONFIG_FILENAME

    # Fall back to the repo root relative to this file (source checkouts)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, DEFAULT_CONFIG_FILENAME)


@dataclass
class Venue:
    """Venue metadata, used for the UI's location filter."""

    key: str
    name: str
    url: Optional[str] = None
    address: Optional[str] = None


@dataclass
class Config:
    enabled_scrapers: List[str] = field(default_factory=list)
    venues: Dict[str, Venue] = field(default_factory=dict)
    scrape_interval: int = 21600
    database_path: str = "./data/events.db"

    def display_name(self, scraper_key: str) -> str:
        """Human-readable label for a scraper, falling back to its key."""
        venue = self.venues.get(scraper_key)
        return venue.name if venue else scraper_key

    def validate(self, available_scrapers) -> None:
        """Fail loudly at startup rather than warning mid-run."""
        unknown = [n for n in self.enabled_scrapers if n not in available_scrapers]
        if unknown:
            raise ValueError(
                f"config.yaml enables scrapers that do not exist: {unknown}. "
                f"Available: {sorted(available_scrapers)}"
            )

        undocumented = [n for n in self.enabled_scrapers if n not in self.venues]
        if undocumented:
            # Not fatal: the UI just falls back to the raw key.
            logger.warning(
                "enabled scrapers with no venue metadata in config.yaml: %s",
                undocumented,
            )


def load_config(path: Optional[str] = None) -> Config:
    """Read config.yaml and layer environment overrides on top."""
    resolved = path or _default_config_path()

    raw = {}
    if os.path.exists(resolved):
        with open(resolved, encoding='utf-8') as handle:
            raw = yaml.safe_load(handle) or {}
    else:
        logger.warning("config file not found at %s; using defaults", resolved)

    scrapers_section = raw.get('scrapers') or {}
    venues_section = raw.get('venues') or {}

    venues = {
        key: Venue(
            key=key,
            name=(value or {}).get('name', key),
            url=(value or {}).get('url'),
            address=(value or {}).get('address'),
        )
        for key, value in venues_section.items()
    }

    # Environment wins for deployment-specific values.
    interval = os.environ.get('SCRAPE_INTERVAL')
    database_path = os.environ.get('DATABASE_PATH')

    return Config(
        enabled_scrapers=list(scrapers_section.get('enabled') or []),
        venues=venues,
        scrape_interval=int(interval) if interval else 21600,
        database_path=database_path or './data/events.db',
    )


_cached: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Process-wide config, loaded once."""
    global _cached
    if _cached is None or reload:
        _cached = load_config()
    return _cached
