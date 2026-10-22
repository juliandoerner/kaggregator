"""
Tests for registry.py - ScraperRegistry class.
"""

import pytest
from ka_events.registry import ScraperRegistry


class TestScraperRegistry:
    """Test cases for ScraperRegistry."""

    def test_registry_creation(self):
        """Test that registry can be created."""
        registry = ScraperRegistry()
        assert registry is not None

    def test_registry_has_scrapers(self):
        """Test that registry has registered scrapers."""
        registry = ScraperRegistry()

        # Should have multiple scrapers registered
        assert len(registry.available_scrapers) > 0

    def test_get_scraper_substage(self):
        """Test getting Substage scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('substage')

        assert scraper is not None
        assert scraper.name == 'substage'

    def test_get_scraper_kohi(self):
        """Test getting KOHI scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('kohi')

        assert scraper is not None
        assert scraper.name == 'kohi'

    def test_get_scraper_tollhaus(self):
        """Test getting Tollhaus scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('tollhaus')

        assert scraper is not None
        assert scraper.name == 'tollhaus'

    def test_get_scraper_z10(self):
        """Test getting Z10 scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('z10')

        assert scraper is not None
        assert scraper.name == 'z10'

    def test_get_scraper_akk_liveschlonz(self):
        """Test getting AKK Liveschlonz scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('akk_liveschlonz')

        assert scraper is not None
        assert scraper.name == 'akk_liveschlonz'

    def test_get_scraper_pacht(self):
        """Test getting P8 (pacht) scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('pacht')

        assert scraper is not None
        assert scraper.name == 'pacht'

    def test_get_scraper_jubez(self):
        """Test getting jubez scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('jubez')

        assert scraper is not None
        assert scraper.name == 'jubez'

    def test_get_scraper_stadtmitte(self):
        """Test getting Die Stadtmitte scraper."""
        registry = ScraperRegistry()

        scraper = registry.get_scraper('stadtmitte')

        assert scraper is not None
        assert scraper.name == 'stadtmitte'

    def test_get_scraper_nonexistent_raises(self):
        """Test that getting non-existent scraper raises ValueError."""
        registry = ScraperRegistry()

        with pytest.raises(ValueError) as exc_info:
            registry.get_scraper('nonexistent_scraper')

        assert 'nonexistent_scraper' in str(exc_info.value)

    def test_available_scrapers(self):
        """Test listing all registered scrapers."""
        registry = ScraperRegistry()

        scraper_names = registry.available_scrapers

        assert isinstance(scraper_names, list)
        assert len(scraper_names) > 0

        # Check expected scrapers are present
        expected = [
            'substage', 'kohi', 'tollhaus', 'z10', 'akk_liveschlonz',
            'pacht', 'jubez', 'stadtmitte',
        ]
        for name in expected:
            assert name in scraper_names

    def test_all_scrapers_have_unique_names(self):
        """Test that all registered scrapers have unique names."""
        registry = ScraperRegistry()

        scraper_names = registry.available_scrapers

        # No duplicates
        assert len(scraper_names) == len(set(scraper_names))

    def test_get_all_scrapers(self):
        """Test getting all scraper instances."""
        registry = ScraperRegistry()

        all_scrapers = registry.get_all_scrapers()

        assert isinstance(all_scrapers, list)
        assert len(all_scrapers) > 0

        for scraper in all_scrapers:
            assert hasattr(scraper, 'name')
            assert hasattr(scraper, 'fetch_events')

    def test_get_enabled_scrapers(self):
        """Test getting only enabled scrapers."""
        registry = ScraperRegistry()

        enabled = ['substage', 'kohi']
        scrapers = registry.get_enabled_scrapers(enabled)

        assert len(scrapers) == 2
        names = [s.name for s in scrapers]
        assert 'substage' in names
        assert 'kohi' in names

    def test_get_enabled_scrapers_with_unknown(self):
        """Test getting enabled scrapers with unknown name (should print warning)."""
        registry = ScraperRegistry()

        enabled = ['substage', 'unknown_scraper']
        scrapers = registry.get_enabled_scrapers(enabled)

        # Should only return known scraper
        assert len(scrapers) == 1
        assert scrapers[0].name == 'substage'

    def test_all_scrapers_implement_fetch_events(self):
        """Test that all registered scrapers implement fetch_events."""
        registry = ScraperRegistry()

        for scraper_name in registry.available_scrapers:
            scraper = registry.get_scraper(scraper_name)

            # Should have fetch_events method
            assert hasattr(scraper, 'fetch_events')
            assert callable(getattr(scraper, 'fetch_events'))
