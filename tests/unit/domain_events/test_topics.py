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


def test_real_catalog_has_seventeen_channels() -> None:
    # 12 CONFIRMED-v1 channels + 4 Wave 4 intelligence channels (w4-10:
    # entity.graph / claim.evidence / experiment.registered / experiment.
    # anchored) + 1 Wave 5 channel (w5-02: deployment.confirmed.v1, channel
    # #17). The other W4/W5 payload-add events — demand.graph, citation.
    # normalized, observation.captured, experiment.outcome.observed,
    # strategy.card.eligible — were already catalog names (only gained a
    # payload $ref, no channel-count change).
    catalog = load_topic_catalog()
    assert len(catalog) == 17


def test_real_catalog_every_entry_has_a_producer() -> None:
    catalog = load_topic_catalog()
    assert all(info.expected_producer for info in catalog.values())


def test_real_catalog_engine_id_required_flag_for_observation_citation_experiment() -> None:
    """ADR-0013: engine_id required for the observation/citation/experiment
    event families. The two Wave 4 experiment-registration events (w4-10)
    join that set — every experiment-family event must declare which engine
    it targets (chatgpt-search only in v1), so the engine-scope guard holds
    at the contract boundary. Demand/entity/claim-evidence graphs are
    first-party-derived (not engine-observed) and carry no engine_id flag.
    """
    catalog = load_topic_catalog()
    required = {event_type for event_type, info in catalog.items() if info.engine_id_required}
    assert required == {
        "observation.captured.v1",
        "citation.normalized.v1",
        "experiment.outcome.observed.v1",
        "experiment.registered.v1",
        "experiment.anchored.v1",
    }


def test_real_catalog_engine_id_not_required_for_patch_unit_completed() -> None:
    catalog = load_topic_catalog()
    assert catalog["patch.unit.completed.v1"].engine_id_required is False


def test_real_catalog_deployment_confirmed_producer_and_not_engine_required() -> None:
    """w5-02: deployment.confirmed.v1 (channel #17) is produced by the
    forge-console-api ingress gateway and is NOT engine-id-required (it is a
    customer/CI-CD deployment signal, not a ChatGPT-Search observation)."""
    catalog = load_topic_catalog()
    info = catalog["deployment.confirmed.v1"]
    assert info.expected_producer == "forge-console-api-service"
    assert info.engine_id_required is False


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
