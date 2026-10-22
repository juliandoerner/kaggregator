"""
Scraper Registry for automatic discovery and loading of venue scrapers.
"""

import logging
import importlib
import pkgutil
from typing import List, Dict, Type

from ka_events import scrapers as scrapers_package
from ka_events.base import BaseScraper


logger = logging.getLogger(__name__)


class ScraperRegistry:
    """
    Discovers and manages all available venue scrapers.

    Scrapers are auto-discovered from the ka_events.scrapers package: any class
    subclassing BaseScraper and defining a `name` is registered. There is no
    manual list to keep in sync.
    """

    def __init__(self, package=None):
        self._package = package or scrapers_package
        self._scrapers: Dict[str, Type[BaseScraper]] = {}
        self._discover_scrapers()

    def _discover_scrapers(self):
        """Import every module in the scrapers package and register its scrapers.

        Walks the package rather than the filesystem, so discovery works
        identically from a source checkout or an installed wheel.
        """
        for module_info in pkgutil.iter_modules(self._package.__path__):
            if module_info.name.startswith('_'):
                continue

            module_name = f"{self._package.__name__}.{module_info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                # A broken scraper must not stop the others from loading, but
                # it has to be loud - a silently missing scraper looks exactly
                # like a venue with no events.
                logger.error("could not load scraper module %s: %s: %s",
                             module_name, type(exc).__name__, exc)
                continue

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BaseScraper)
                        and attr is not BaseScraper
                        and getattr(attr, 'name', None)):
                    self._scrapers[attr.name] = attr

    def get_scraper(self, name: str) -> BaseScraper:
        """Get a scraper instance by name."""
        if name not in self._scrapers:
            raise ValueError(f"Unknown scraper: {name}")
        return self._scrapers[name]()

    def get_all_scrapers(self) -> List[BaseScraper]:
        """Get all scraper instances."""
        return [scraper() for scraper in self._scrapers.values()]

    def get_enabled_scrapers(self, enabled_names: List[str]) -> List[BaseScraper]:
        """Get only enabled scrapers by name."""
        scrapers = []
        for name in enabled_names:
            if name in self._scrapers:
                scrapers.append(self._scrapers[name]())
            else:
                logger.warning("unknown scraper requested: %s", name)
        return scrapers

    @property
    def available_scrapers(self) -> List[str]:
        """List names of all available scrapers."""
        return list(self._scrapers.keys())
