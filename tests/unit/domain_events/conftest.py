"""pytest fixtures for tests/unit/domain_events (w2-02-envelope).

Resets `saena_domain.events._topics`'s module-level AsyncAPI cache before
each test so tests that pass a custom `asyncapi_path=` (or rely on the real
catalog) never observe another test's cached parse result.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_domain.events import _topics

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SYSTEM_CHANNEL_ASYNCAPI = FIXTURES_DIR / "asyncapi_with_system_channel.yaml"


@pytest.fixture(autouse=True)
def _reset_topic_catalog_cache() -> None:
    _topics._reset_cache_for_tests()
    yield
    _topics._reset_cache_for_tests()
