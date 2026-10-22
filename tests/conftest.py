"""
Pytest configuration and shared fixtures.

Note what is *absent*: this file used to insert two directories onto sys.path
and force sys.modules['database'] to point at the scraper service's module, so
that both services resolved `import database` to the same file. That trick made
imports depend on the working directory and prevented reliable application
startup. Now there is one installed package
(`ka_events`) and ordinary imports just work.
"""

import os
import tempfile

import pytest


# Point the whole test session at a throwaway database *before* any test module
# imports the application. `ka_events.web.app` calls init_db() at import time
# (correct for a gunicorn worker), which without this would create and migrate
# the developer's real ./data/events.db just by running the suite.
_TEST_DB = os.path.join(tempfile.gettempdir(), 'ka_events_test_session.db')
os.environ.setdefault('DATABASE_PATH', _TEST_DB)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def app_config():
    """Return test configuration for Flask app."""
    return {
        'DATABASE_PATH': ':memory:',
        'TESTING': True,
    }
