"""Unit tests: saena_domain.events._topics (AsyncAPI-derived topic catalog).

Reads the real, authoritative AsyncAPI file (read-only consumption — this
patch unit's exclusive write paths never include packages/contracts/**) plus
local fixtures: one adds a context_type=system channel not yet in the
CONFIRMED catalog, three others are deliberately malformed to exercise
`TopicCatalogError` (see tests/unit/domain_events/conftest.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_domain.events._topics import TopicCatalogError, load_topic_catalog

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_SYSTEM_CHANNEL_ASYNCAPI = _FIXTURES_DIR / "asyncapi_with_system_channel.yaml"
_MALFORMED_SUMMARY_ASYNCAPI = _FIXTURES_DIR / "asyncapi_malformed_summary.yaml"
_UNKNOWN_CHANNEL_REFERENCE_ASYNCAPI = _FIXTURES_DIR / "asyncapi_unknown_channel_reference.yaml"
_CHANNEL_WITHOUT_OPERATION_ASYNCAPI = _FIXTURES_DIR / "asyncapi_channel_without_operation.yaml"


def test_real_catalog_contains_patch_unit_completed() -> None:
    catalog = load_topic_catalog()
    info = catalog["patch.unit.completed.v1"]
    assert info.expected_producer == "agent-runner-service"


def test_real_catalog_has_twelve_channels() -> None:
    catalog = load_topic_catalog()
    assert len(catalog) == 12


def test_real_catalog_every_entry_has_a_producer() -> None:
    catalog = load_topic_catalog()
    assert all(info.expected_producer for info in catalog.values())


def test_fixture_catalog_adds_system_channel() -> None:
    catalog = load_topic_catalog(_SYSTEM_CHANNEL_ASYNCAPI)
    info = catalog["adapter.config.updated.v1"]
    assert info.expected_producer == "policy-gate"


def test_catalog_is_cached_between_calls() -> None:
    first = load_topic_catalog()
    second = load_topic_catalog()
    assert first is second


def test_malformed_summary_raises_topic_catalog_error() -> None:
    with pytest.raises(TopicCatalogError, match="does not match the"):
        load_topic_catalog(_MALFORMED_SUMMARY_ASYNCAPI)


def test_summary_referencing_unknown_channel_raises_topic_catalog_error() -> None:
    with pytest.raises(TopicCatalogError, match="unknown channel address"):
        load_topic_catalog(_UNKNOWN_CHANNEL_REFERENCE_ASYNCAPI)


def test_channel_without_matching_operation_raises_topic_catalog_error() -> None:
    with pytest.raises(TopicCatalogError, match="no matching operation"):
        load_topic_catalog(_CHANNEL_WITHOUT_OPERATION_ASYNCAPI)
