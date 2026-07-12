"""Tests for `saena_domain.bus._envelope_check`'s topic-catalog parsing —
specifically the SHOULD-FIX `missing_producer` post-parse check (critic
w2-18 review, mirroring `saena_domain.events._topics._parse`'s own check)."""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_domain.bus._envelope_check import TopicCatalogError, _parse_catalog

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_CHANNEL_WITHOUT_OPERATION = _FIXTURES_DIR / "asyncapi_channel_without_operation.yaml"


def test_channel_without_matching_operation_raises_topic_catalog_error() -> None:
    """A channel declared under `channels:` with no matching `operations:`
    entry must fail loudly (`TopicCatalogError`) rather than silently keep
    an empty `expected_producer` — the empty-producer catalog entry would
    otherwise open a topic-discipline bypass window at drain time (any
    `producer` value on that `event_type` would be treated as a genuine
    mismatch only if it happened to differ from `""`, not caught as an
    authoring bug)."""
    with pytest.raises(TopicCatalogError, match="no matching operation"):
        _parse_catalog(_CHANNEL_WITHOUT_OPERATION)
