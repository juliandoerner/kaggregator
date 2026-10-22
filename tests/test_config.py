"""
Tests for configuration validation.
"""

import pytest
import os
import yaml


class TestConfigFile:
    """Test cases for config.yaml validation."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory (PricingModels)."""
        # Tests are in tests/, so go up 1 level to get to PricingModels
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_config_file_exists(self, project_root):
        """Test that config.yaml exists."""
        config_path = os.path.join(project_root, 'config.yaml')
        assert os.path.exists(config_path), f"config.yaml not found at {config_path}"

    def test_config_file_is_valid_yaml(self, project_root):
        """Test that config.yaml is valid YAML."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config is not None
        assert isinstance(config, dict)

    def test_config_has_scrapers_section(self, project_root):
        """Test that config has scrapers section."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert 'scrapers' in config
        assert isinstance(config['scrapers'], dict)

    def test_config_has_enabled_scrapers_list(self, project_root):
        """Test that config has enabled scrapers list."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert 'enabled' in config['scrapers']
        assert isinstance(config['scrapers']['enabled'], list)
        assert len(config['scrapers']['enabled']) > 0

    def test_config_enabled_scrapers_are_strings(self, project_root):
        """Test that all enabled scrapers are strings."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        for scraper in config['scrapers']['enabled']:
            assert isinstance(scraper, str), f"Scraper name '{scraper}' is not a string"

    def test_config_has_no_deployment_settings(self, project_root):
        """Deployment values belong to the environment, not config.yaml.

        The file used to carry `database.path: ${DATABASE_PATH:-...}` and an
        equivalent interval entry. Nothing ever interpolated those - they only
        looked configurable. Paths and intervals now come from env vars.
        """
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert 'database' not in config
        assert 'interval' not in config.get('scrapers', {})


    def test_config_has_venues_section(self, project_root):
        """Test that config has venues section."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert 'venues' in config
        assert isinstance(config['venues'], dict)

    def test_config_venue_entries_have_required_fields(self, project_root):
        """Test that venue entries have required fields."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        required_fields = ['name', 'url']

        for venue_name, venue_data in config['venues'].items():
            for field in required_fields:
                assert field in venue_data, f"Venue '{venue_name}' missing required field '{field}'"

    def test_config_enabled_scrapers_have_venue_entries(self, project_root):
        """Test that all enabled scrapers have corresponding venue entries."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        enabled = config['scrapers']['enabled']
        venues = config['venues']

        for scraper in enabled:
            # Some scrapers might use different names (e.g., akk_liveschlonz vs akk)
            # Check if scraper name or a mapped version exists in venues
            venue_key = scraper.replace('_liveschlonz', '')
            assert venue_key in venues or scraper in venues, \
                f"Enabled scraper '{scraper}' has no corresponding venue entry"

    def test_config_venue_urls_are_valid(self, project_root):
        """Test that venue URLs start with http:// or https://."""
        config_path = os.path.join(project_root, 'config.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        for venue_name, venue_data in config['venues'].items():
            url = venue_data.get('url', '')
            assert url.startswith(('http://', 'https://')), \
                f"Venue '{venue_name}' URL '{url}' is not valid"


class TestConfigModule:
    """ka_events.config is what the application actually reads."""

    def test_loads_enabled_scrapers_from_yaml(self, tmp_path):
        from ka_events.config import load_config

        path = tmp_path / 'config.yaml'
        path.write_text(
            "scrapers:\n  enabled:\n    - alpha\n    - beta\n"
            "venues:\n  alpha:\n    name: Alpha Hall\n"
        )

        config = load_config(str(path))

        assert config.enabled_scrapers == ['alpha', 'beta']
        assert config.display_name('alpha') == 'Alpha Hall'

    def test_display_name_falls_back_to_key(self, tmp_path):
        """A new scraper without venue metadata must not break the UI."""
        from ka_events.config import load_config

        path = tmp_path / 'config.yaml'
        path.write_text("scrapers:\n  enabled:\n    - newvenue\nvenues: {}\n")

        assert load_config(str(path)).display_name('newvenue') == 'newvenue'

    def test_validate_rejects_unknown_scraper(self, tmp_path):
        """Startup must fail loudly, not warn once per run forever."""
        from ka_events.config import load_config

        path = tmp_path / 'config.yaml'
        path.write_text("scrapers:\n  enabled:\n    - does_not_exist\nvenues: {}\n")
        config = load_config(str(path))

        with pytest.raises(ValueError, match='do not exist'):
            config.validate(['kohi', 'z10'])

    def test_validate_accepts_known_scrapers(self, tmp_path):
        from ka_events.config import load_config

        path = tmp_path / 'config.yaml'
        path.write_text(
            "scrapers:\n  enabled:\n    - kohi\nvenues:\n  kohi:\n    name: KOHI\n")

        load_config(str(path)).validate(['kohi', 'z10'])  # must not raise

    def test_environment_overrides_deployment_values(self, tmp_path, monkeypatch):
        from ka_events.config import load_config

        path = tmp_path / 'config.yaml'
        path.write_text("scrapers:\n  enabled: []\nvenues: {}\n")

        monkeypatch.setenv('DATABASE_PATH', '/custom/events.db')
        monkeypatch.setenv('SCRAPE_INTERVAL', '900')
        config = load_config(str(path))

        assert config.database_path == '/custom/events.db'
        assert config.scrape_interval == 900

    def test_real_config_is_consistent_with_the_registry(self):
        """The actual shipped config must name only real scrapers."""
        from ka_events.config import get_config
        from ka_events.registry import ScraperRegistry

        get_config(reload=True).validate(ScraperRegistry().available_scrapers)


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    def test_default_scrape_interval(self):
        """Test default scrape interval value."""
        # When SCRAPE_INTERVAL is not set, default should be 21600 (6 hours)
        interval = int(os.environ.get("SCRAPE_INTERVAL", 21600))
        assert interval == 21600

    def test_custom_scrape_interval(self):
        """Test custom scrape interval from environment."""
        os.environ["SCRAPE_INTERVAL"] = "3600"  # 1 hour

        interval = int(os.environ.get("SCRAPE_INTERVAL", 21600))
        assert interval == 3600

        # Clean up
        del os.environ["SCRAPE_INTERVAL"]

    def test_custom_database_path(self):
        """Test custom database path from environment."""
        os.environ["DATABASE_PATH"] = "/tmp/test.db"

        db_path = os.environ.get("DATABASE_PATH", "./data/events.db")
        assert db_path == "/tmp/test.db"

        # Clean up
        del os.environ["DATABASE_PATH"]


class TestScraperModuleImports:
    """Test that all configured scrapers can be imported."""

    def test_import_substage(self):
        """Test importing Substage scraper."""
        from ka_events.scrapers.substage import SubstageScraper
        assert SubstageScraper.name == 'substage'

    def test_import_kohi(self):
        """Test importing KOHI scraper."""
        from ka_events.scrapers.kohi import KohiScraper
        assert KohiScraper.name == 'kohi'

    def test_import_tollhaus(self):
        """Test importing Tollhaus scraper."""
        from ka_events.scrapers.tollhaus import TollhausScraper
        assert TollhausScraper.name == 'tollhaus'

    def test_import_z10(self):
        """Test importing Z10 scraper."""
        from ka_events.scrapers.z10 import Z10Scraper
        assert Z10Scraper.name == 'z10'

    def test_import_akk(self):
        """Test importing AKK scraper."""
        from ka_events.scrapers.akk import AkkLiveschlonzScraper
        assert AkkLiveschlonzScraper.name == 'akk_liveschlonz'


class TestScrapersPackage:
    """The scrapers package is discovered at runtime, not re-exported.

    These used to assert that `scrapers/__init__.py` re-exported every scraper
    class. That list was a second source of truth alongside the registry, and
    it had already drifted - four scrapers were missing from it. The real
    contract is that the registry finds them.
    """

    def test_package_is_importable(self):
        import ka_events.scrapers
        assert ka_events.scrapers.__path__

    def test_registry_discovers_every_scraper_module(self):
        """Every non-private module in the package must yield a usable scraper."""
        import pkgutil
        import ka_events.scrapers
        from ka_events.registry import ScraperRegistry

        modules = {
            info.name for info in pkgutil.iter_modules(ka_events.scrapers.__path__)
            if not info.name.startswith('_')
        }
        assert modules, "no scraper modules found"

        discovered = ScraperRegistry().available_scrapers
        # One module can define one scraper here, so counts should line up.
        assert len(discovered) == len(modules)

    def test_configured_scrapers_are_all_discoverable(self):
        """Anything listed in config.yaml must actually exist."""
        import yaml
        from ka_events.registry import ScraperRegistry

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(project_root, 'config.yaml')) as handle:
            enabled = yaml.safe_load(handle)['scrapers']['enabled']

        available = ScraperRegistry().available_scrapers
        missing = [name for name in enabled if name not in available]
        assert not missing, f"config.yaml enables unknown scrapers: {missing}"
