"""`saena_citation_intelligence.service.normalize_citation` — event emission
validity, engine_id enforcement, and edge/failure branches (w4-05).

`normalize_citation` builds its `citation.normalized.v1` envelope via the
REAL `saena_domain.events.EnvelopeFactory` (never a hand-built dict) — every
test here exercises that real factory, including its dual jsonschema +
pydantic envelope validation. `payload.engine_id` MUST be `chatgpt-search`
(this event family requires it, ADR-0013 observation/citation/experiment
families, `x-saena-engine-id-required: true` on this channel in
`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml` — verified by
`test_engine_id_channel_requires_engine_id_per_asyncapi_catalog` below,
which reads that catalog flag directly rather than assuming it).

Shape note: as of this worktree's current `packages/contracts`/
`packages/schemas` state, the `citation.normalized.v1` AsyncAPI channel is
CONFIRMED (topic/producer/`x-saena-engine-id-required` all resolve) but is
still envelope-only (no `payload.$ref` to a dedicated
`citation-normalized.schema.json` wired into THIS worktree's copy of the
catalog yet — that payload contract is a separate, single-owner
`packages/contracts`/`packages/schemas` change, w4-10, out of this unit's
exclusive write paths per CLAUDE.md §7 "단일 owner"). `EnvelopeFactory`
already fully validates topic/producer/engine_id-required/engine_id-value
and the generic envelope shape either way (`_check_engine_id`,
`_resolve_topic`, `_dual_validate` in `saena_domain.events.factory` do not
depend on a payload-specific `$ref` being wired) — this module's own output
payload shape (`engine_id`, `citation_id`, `normalized_uri`, `content_hash`)
is fixed to exactly the 4 fields the landed
`citation-normalized.schema.json` payload contract requires (confirmed by
direct inspection), so this suite's assertions on the envelope's `payload`
dict double as a contract-shape check independent of which exact schema
file happens to be wired into this particular checkout at test-run time.
"""

from __future__ import annotations

import pytest
from citation_intelligence_factories import (
    CITATION_ID,
    COMPETITOR_DOMAINS,
    RUN_ID,
    TENANT_ID,
    TENANT_OWNED_DOMAINS,
    fixed_clock,
)
from saena_citation_intelligence.errors import (
    EngineNotPermittedError,
    OwnershipClassificationError,
    UrlNormalizationError,
)
from saena_citation_intelligence.ownership import OwnershipClass
from saena_citation_intelligence.service import (
    ALLOWED_ENGINE_IDS,
    normalize_citation,
)
from saena_domain.events._topics import load_topic_catalog
from saena_domain.events.errors import EnvelopeValidationError


def test_allowed_engine_ids_is_the_v1_closed_enum() -> None:
    assert frozenset({"chatgpt-search"}) == ALLOWED_ENGINE_IDS


def test_engine_id_channel_requires_engine_id_per_asyncapi_catalog() -> None:
    """Read the REAL AsyncAPI catalog directly (not assumed) — confirms
    `citation.normalized.v1` is one of the channels that require
    `payload.engine_id` (ADR-0013 observation/citation/experiment
    families)."""
    catalog = load_topic_catalog()
    topic = catalog["citation.normalized.v1"]
    assert topic.engine_id_required is True
    assert topic.expected_producer == "citation-intelligence-service"


def test_chatgpt_search_engine_id_succeeds() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.envelope["payload"]["engine_id"] == "chatgpt-search"


@pytest.mark.parametrize(
    "disallowed_engine_id",
    ["google-ai-overviews", "google-aio", "google-ai-mode", "gemini", "bing-chat", ""],
)
def test_non_chatgpt_search_engine_id_rejected_before_normalization(
    disallowed_engine_id: str,
) -> None:
    """The engine guard fires BEFORE URL normalization — an obviously
    malformed `raw_url` combined with a disallowed engine_id still raises
    `EngineNotPermittedError` (the engine check, not a URL error)."""
    with pytest.raises(EngineNotPermittedError) as exc_info:
        normalize_citation(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            citation_id=CITATION_ID,
            raw_url="not a url at all",
            engine_id=disallowed_engine_id,
            clock=fixed_clock,
        )
    assert disallowed_engine_id in str(exc_info.value) or disallowed_engine_id == ""


def test_envelope_context_type_is_tenant() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.envelope["context_type"] == "tenant"
    assert result.envelope["tenant_id"] == TENANT_ID
    assert result.envelope["run_id"] == RUN_ID


def test_envelope_event_type_and_producer() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.envelope["event_type"] == "citation.normalized.v1"
    assert result.envelope["producer"] == "citation-intelligence-service"


def test_envelope_payload_has_exactly_the_contract_fields() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product?utm_source=x",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    payload = result.envelope["payload"]
    assert set(payload) == {"engine_id", "citation_id", "normalized_uri", "content_hash"}
    assert payload["citation_id"] == CITATION_ID
    assert payload["normalized_uri"] == "https://example.com/product"
    assert payload["content_hash"] == result.record.content_hash
    assert payload["content_hash"].startswith("sha256:")


def test_envelope_payload_never_reprojects_tenant_id_or_run_id() -> None:
    """ADR-0024(e)-1: payload must not duplicate envelope-level
    tenant_id/run_id — enforced by the real `EnvelopeFactory`, this test
    just confirms this module never even attempts to pass them in payload
    (would raise `PayloadDuplicatesEnvelopeFieldError` if it did)."""
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert "tenant_id" not in result.envelope["payload"]
    assert "run_id" not in result.envelope["payload"]


def test_default_idempotency_key_is_tenant_run_citation() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.envelope["idempotency_key"] == f"{TENANT_ID}:{RUN_ID}:{CITATION_ID}"


def test_caller_supplied_idempotency_key_overrides_default() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        idempotency_key="custom-key",
        clock=fixed_clock,
    )
    assert result.envelope["idempotency_key"] == "custom-key"


def test_record_and_envelope_normalized_uri_match() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="HTTPS://Example.COM:443/Product/",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.record.normalized_uri == result.envelope["payload"]["normalized_uri"]
    assert result.record.normalized_uri == "https://example.com/Product"


def test_owned_domain_flows_through_to_record_ownership_class() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://acme.com/product",
        engine_id="chatgpt-search",
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
        clock=fixed_clock,
    )
    assert result.record.ownership_class == OwnershipClass.OWNED


def test_competitor_domain_flows_through_and_is_never_owned() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://rival.com/product",
        engine_id="chatgpt-search",
        tenant_owned_domains=TENANT_OWNED_DOMAINS,
        competitor_domains=COMPETITOR_DOMAINS,
        clock=fixed_clock,
    )
    assert result.record.ownership_class == OwnershipClass.COMPETITOR
    assert result.record.ownership_class != OwnershipClass.OWNED


def test_invalid_raw_url_raises_url_normalization_error() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_citation(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            citation_id=CITATION_ID,
            raw_url="mailto:someone@example.com",
            engine_id="chatgpt-search",
            clock=fixed_clock,
        )


def test_malformed_ownership_domain_input_raises() -> None:
    with pytest.raises(OwnershipClassificationError):
        normalize_citation(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            citation_id=CITATION_ID,
            raw_url="https://example.com/product",
            engine_id="chatgpt-search",
            tenant_owned_domains=frozenset({""}),
            clock=fixed_clock,
        )


def test_invalid_tenant_id_raises_via_envelope_or_record_validation() -> None:
    """An invalid `tenant_id` is rejected somewhere along this function's
    fail-closed chain (either `CitationRecord.__post_init__` or the real
    `EnvelopeFactory`'s own tenant_id contract check) — never silently
    accepted."""
    with pytest.raises((UrlNormalizationError, EnvelopeValidationError)):
        normalize_citation(
            tenant_id="Not_Valid!",
            run_id=RUN_ID,
            citation_id=CITATION_ID,
            raw_url="https://example.com/product",
            engine_id="chatgpt-search",
            clock=fixed_clock,
        )


def test_result_is_frozen_dataclass() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    with pytest.raises(AttributeError):
        result.record = result.record  # type: ignore[misc]


def test_clock_is_injected_not_real_wall_clock() -> None:
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
        clock=fixed_clock,
    )
    assert result.record.observed_at == fixed_clock()


def test_default_clock_produces_timestamp_utc_shaped_string() -> None:
    import re

    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id=CITATION_ID,
        raw_url="https://example.com/product",
        engine_id="chatgpt-search",
    )
    assert re.match(
        r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", result.record.observed_at
    )
