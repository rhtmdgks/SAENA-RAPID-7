"""Wave-4 intelligence: no-outcome / no-PII / no-secret event boundary,
plus the `outcome-field-gap` open-class policy-gate expectation (w4-16).

`docs/architecture/wave4-plan.md` "Existing vs new events" (Experiment
ledger row), verbatim: "**NO outcome/DiD/causal/lift** (Wave 5)." and
"**Forbidden in W4**: absorption-analysis(P1), digital-twin,
portfolio-optimizer, strategy-skill-bank, causal/lift/DiD/KPI-weight,
outcome analysis, strategy-card-eligible, production customer observation,
prod deploy." `docs/architecture/implementation-waves.md`/CLAUDE.md
"no PII, secrets... in event payloads" (envelope hard constraint).

**Adversarial finding this module documents and pins (`outcome-field-gap`
open-class policy-gate expectation)**: every Wave-4 event PAYLOAD schema
this suite has access to (`observation.captured.v1`, `citation.
normalized.v1`, `claim.evidence.versioned.v1`, `demand.graph.versioned.v1`,
`entity.graph.versioned.v1`) is explicitly OPEN class (ADR-0012 — no
`additionalProperties: false` anywhere in the payload schema or the
`engine_required_payload` activation fragment it composes; verified
directly against the checked-in schema JSON by
`test_open_class_event_payload_schemas_have_no_additional_properties_lock`
below). This means `saena_domain.events.factory.EnvelopeFactory`'s dual
jsonschema+pydantic validation CANNOT, by itself, reject a hand-crafted
payload carrying a stray `outcome`/`lift`/`kpi_weight`/PII-shaped field —
`test_envelope_factory_alone_does_not_reject_a_hand_crafted_outcome_or_pii_field`
proves this empirically (it is a documented GAP this suite surfaces, not a
silently-accepted risk): the ACTUAL enforcement of "no outcome/PII in this
event" is that every real Wave-4 service builder function never
constructs such a payload in the first place. The tests below are the
"builder discipline" half of that two-part guard; a dedicated payload-
level policy gate (mirroring `gate_content_fidelity`/`gate_secret_scan`'s
own Release-Gate shape) that would catch this at the SCHEMA layer does not
exist yet in this repo (confirmed by repo-wide search, same "missing
owner" discipline as F-9's `measurement_fraud.py` note) — a future service
owner should close this gap, not silently duplicate this suite's builder-
level proof as the only defense.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from saena_chatgpt_observer.platform_observation_record import (
    build_observation_captured_envelope,
    build_platform_observation_record,
)
from saena_citation_intelligence.service import normalize_citation
from saena_claim_evidence.events import build_claim_evidence_versioned_event
from saena_claim_evidence.ledger import DEFAULT_FRESHNESS_POLICY, append_claim, append_evidence
from saena_demand_graph.builder import build_demand_graph
from saena_demand_graph.events import build_demand_graph_versioned_payload
from saena_demand_graph.records import FirstPartyMaterial, MaterialSourceKind
from saena_domain.events import EnvelopeFactory
from saena_entity_resolution.canonicalize import AliasGroup, EntityType, resolve_entities
from saena_entity_resolution.events import build_entity_graph_versioned_payload
from saena_entity_resolution.graph import EntityGraph
from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim
from saena_schemas.domain.extracted_claim_v1 import Status as ClaimStatus

TENANT_ID = "acme-co"
RUN_ID = "run-0001"
PROJECT_ID = "proj-alpha"
NOW_ISO = "2026-07-13T12:00:00Z"

#: Wave-5-forbidden field names this module asserts are absent everywhere
#: (wave4-plan.md "Forbidden in W4" + "NO outcome/DiD/causal/lift").
FORBIDDEN_OUTCOME_FIELDS = frozenset(
    {
        "outcome",
        "did",
        "causal_lift",
        "lift",
        "kpi_weight",
        "absorption_rate",
        "absorption_score",
        "strategy_card",
        "strategy_card_eligible",
        "treatment_effect",
        "control_delta",
    }
)

#: PII/secret-SHAPED field names — never a claim about a specific value,
#: just the field-name surface this module checks is never present as a
#: KEY in any emitted payload (mirrors F-6's own "location/rule_id only,
#: never raw secret value" discipline, applied at the field-name level
#: here since these builders never accept such a value to begin with).
PII_SECRET_SHAPED_FIELDS = frozenset(
    {
        "email",
        "phone",
        "ssn",
        "password",
        "api_key",
        "secret",
        "access_token",
        "credit_card",
        "ip_address",
        "full_name",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _assert_no_forbidden_fields(payload: dict) -> None:
    keys = set(payload.keys())
    leaked_outcome = keys & FORBIDDEN_OUTCOME_FIELDS
    leaked_pii = keys & PII_SECRET_SHAPED_FIELDS
    assert not leaked_outcome, f"outcome/DiD/causal/lift field(s) leaked: {leaked_outcome}"
    assert not leaked_pii, f"PII/secret-shaped field(s) leaked: {leaked_pii}"


def _assert_no_email_shaped_value_anywhere(obj: object) -> None:
    serialized = json.dumps(obj, default=str)
    assert not _EMAIL_RE.search(serialized), f"email-shaped value leaked into: {serialized!r}"


# --- Builder-discipline proofs: every real Wave-4 payload builder this ---
# --- suite has access to never emits an outcome/PII/secret field. ---


def test_observation_captured_payload_carries_no_outcome_or_pii_fields() -> None:
    """Pins `build_observation_captured_envelope`'s exact 3-field payload
    (`engine_id`, `observation_id`, `artifact_hash`) — fails if a future
    change widened this payload to include, e.g., a citation-outcome or
    actor-identifying field."""
    envelope = build_observation_captured_envelope(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        engine_id="chatgpt-search",
        observation_id="obs-0001",
        artifact_hash=f"sha256:{'a' * 64}",
        idempotency_key=f"{TENANT_ID}:{RUN_ID}:obs-0001",
    )
    _assert_no_forbidden_fields(envelope["payload"])
    _assert_no_email_shaped_value_anywhere(envelope)


def test_platform_observation_record_carries_no_outcome_or_pii_fields() -> None:
    """Pins `build_platform_observation_record`'s exact 8-field record
    shape — the formal `PlatformObservation` domain contract, which is
    itself `extra="forbid"` (closed class) at the pydantic layer, unlike
    the event payloads this module otherwise focuses on; this test proves
    the SAME discipline holds at the domain-record layer too."""
    record = build_platform_observation_record(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        engine_id="chatgpt-search",
        observation_id="obs-0001",
        raw_object_ref=f"artifact://{TENANT_ID}/{'a' * 64}",
        artifact_hash=f"sha256:{'a' * 64}",
        citation_refs=(),
        captured_at=NOW_ISO,
    )
    _assert_no_forbidden_fields(record)
    _assert_no_email_shaped_value_anywhere(record)


def test_citation_normalized_envelope_carries_no_outcome_or_pii_fields() -> None:
    """Pins `normalize_citation`'s built `citation.normalized.v1` payload
    (`engine_id`, `citation_id`, `normalized_uri`, `content_hash`) — no
    prominence/absorption/contribution scoring field (module docstring:
    "no answer-absorption analysis, no contribution/prominence scoring
    beyond the ownership classification itself, no outcome/DiD/causal/lift
    computation")."""
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id="cite-0001",
        raw_url="https://example.com/page?utm_source=chatgpt",
        engine_id="chatgpt-search",
        clock=lambda: NOW_ISO,
    )
    _assert_no_forbidden_fields(result.envelope["payload"])
    _assert_no_email_shaped_value_anywhere(result.envelope)


def test_claim_evidence_versioned_payload_carries_no_outcome_or_pii_fields() -> None:
    """Pins `build_claim_evidence_versioned_event`'s exact 5-field payload
    (`project_id`, `ledger_version`, `claim_count`, `evidence_count`,
    `provenance_ref`) — counts and a hash only, never claim/evidence TEXT
    (which could itself carry PII) and never an outcome-shaped field."""
    claim = ExtractedClaim(
        tenant_id=TENANT_ID,  # type: ignore[arg-type]
        project_id=PROJECT_ID,  # type: ignore[arg-type]
        claim_id="claim-0001",
        entity_id="entity-0001",
        claim_text="The product supports SSO via SAML 2.0.",
        status=ClaimStatus.active,
        effective_from=NOW_ISO,  # type: ignore[arg-type]
        created_at=NOW_ISO,  # type: ignore[arg-type]
    )
    evidence = EvidenceRecord(
        tenant_id=TENANT_ID,  # type: ignore[arg-type]
        project_id=PROJECT_ID,  # type: ignore[arg-type]
        evidence_id="evidence-0001",
        claim_id="claim-0001",
        source_uri="https://docs.example.com/security/sso",  # type: ignore[arg-type]
        excerpt="SAML 2.0 SSO is supported on the Enterprise plan.",
        freshness_checked_at=NOW_ISO,  # type: ignore[arg-type]
        content_hash=f"sha256:{'a' * 64}",  # type: ignore[arg-type]
    )
    state, _entry = append_claim((), claim)
    state, _entry = append_evidence(
        state,
        evidence,
        link_statuses={},
        policy=DEFAULT_FRESHNESS_POLICY,
        now=datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC),
    )

    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        project_id=PROJECT_ID,
        ledger_version="v1",
        ledger_state=state,
        provenance_ref=f"sha256:{'b' * 64}",
        idempotency_key=f"{TENANT_ID}:{RUN_ID}:v1",
    )
    _assert_no_forbidden_fields(envelope["payload"])
    assert "claim_text" not in envelope["payload"]
    assert "excerpt" not in envelope["payload"]
    _assert_no_email_shaped_value_anywhere(envelope)


def test_demand_graph_versioned_payload_carries_no_outcome_or_pii_fields() -> None:
    """Pins `build_demand_graph_versioned_payload`'s exact 4-field payload
    — never the raw `FirstPartyMaterial.text` (mission: "NO PII, secrets,
    or raw customer source in event payloads")."""
    material = FirstPartyMaterial(
        material_id="m1",
        source_kind=MaterialSourceKind.SALES_TRANSCRIPT,
        text="contact me at attacker@example.com about pricing",
        locale="en-US",
        provenance_ref="doc://sales/call-1",
    )
    graph = build_demand_graph(tenant_id=TENANT_ID, project_id=PROJECT_ID, materials=(material,))
    payload = build_demand_graph_versioned_payload(graph)

    _assert_no_forbidden_fields(payload)
    assert "text" not in payload
    assert "paraphrases" not in payload
    _assert_no_email_shaped_value_anywhere(payload)


def test_entity_graph_versioned_payload_carries_no_outcome_or_pii_fields() -> None:
    """Pins `build_entity_graph_versioned_payload`'s exact 4-field payload
    (`project_id`, `graph_version`, `entity_count`, `provenance_ref`)."""
    result = resolve_entities(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        alias_groups=(
            AliasGroup(
                entity_id="entity-0001",
                entity_type=EntityType.product,
                canonical_name="Acme Widget",
                aliases=("acme widget",),
                is_owned=True,
            ),
        ),
        clock=lambda: NOW_ISO,
    )
    graph = EntityGraph(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        graph_version=result.graph_version,
        provenance_ref=f"sha256:{'c' * 64}",
        entities=result.entities,
    )
    payload = build_entity_graph_versioned_payload(graph)

    _assert_no_forbidden_fields(payload)
    assert "entities" not in payload
    _assert_no_email_shaped_value_anywhere(payload)


# --- Documented open-class gap: schema/EnvelopeFactory alone do NOT ---
# --- reject a hand-crafted outcome/PII field (the `outcome-field-gap`). ---


def test_open_class_event_payload_schemas_have_no_additional_properties_lock() -> None:
    """Verifies, directly against the checked-in schema JSON, that none of
    the 5 Wave-4 event payload schemas this suite exercises declare
    `additionalProperties: false` (open-class by design, ADR-0012) — this
    is the STRUCTURAL reason a schema-only defense cannot enforce the
    no-outcome/no-PII boundary; see this module's own docstring
    `outcome-field-gap` note. If a future ADR closes these schemas
    (`additionalProperties: false` added), this test's own assertion
    would need updating too — it is pinned here specifically so that
    change is a deliberate, visible one, not a silent drift this suite's
    other (builder-discipline) tests would mask.
    """
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    schema_paths = [
        "packages/contracts/json-schema/event/observation-captured/v1/observation-captured.schema.json",
        "packages/contracts/json-schema/event/citation-normalized/v1/citation-normalized.schema.json",
        "packages/contracts/json-schema/event/claim-evidence-versioned/v1/claim-evidence-versioned.schema.json",
        "packages/contracts/json-schema/event/demand-graph-versioned/v1/demand-graph-versioned.schema.json",
        "packages/contracts/json-schema/event/entity-graph-versioned/v1/entity-graph-versioned.schema.json",
    ]
    for relative_path in schema_paths:
        schema = json.loads((repo_root / relative_path).read_text())
        assert schema.get("additionalProperties") is not False, (
            f"{relative_path} unexpectedly locked additionalProperties=false; "
            "the outcome-field-gap note in this module's docstring is stale"
        )


def test_envelope_factory_alone_does_not_reject_a_hand_crafted_outcome_or_pii_field() -> None:
    """ADVERSARIAL: proves the gap this module documents is REAL, not
    theoretical — a hand-crafted `citation.normalized.v1` payload carrying
    `outcome`/`lift`/`kpi_weight`/`email` alongside the 4 legitimate fields
    is accepted by `EnvelopeFactory.build_tenant_envelope`'s dual
    jsonschema+pydantic validation UNCHANGED (open-class payload,
    `EventPayloadModel`'s own `extra="allow"`). This test is intentionally
    an assertion that the envelope BUILDS (not that it is rejected) —
    if a future patch unit closes the schema (adds
    `additionalProperties: false`), this specific assertion would start
    failing, which is the correct, visible signal that the
    `outcome-field-gap` note above needs to be retired, not silently
    broken.
    """
    hand_crafted_payload = {
        "engine_id": "chatgpt-search",
        "citation_id": "cite-0001",
        "normalized_uri": "https://example.com/page",
        "content_hash": f"sha256:{'a' * 64}",
        # Wave-5-forbidden + PII-shaped fields a compromised/buggy caller
        # might try to smuggle in — NONE of the 5 real builder functions
        # above ever construct a payload like this; only a direct,
        # bypass-the-builder call can.
        "outcome": "won",
        "lift": 0.42,
        "kpi_weight": 1.0,
        "email": "attacker@example.com",
    }

    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="citation-intelligence-service",
        event_type="citation.normalized.v1",
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        idempotency_key=f"{TENANT_ID}:{RUN_ID}:cite-0001",
        payload=hand_crafted_payload,
    )

    # The gap, demonstrated: every forbidden field survived, unrejected.
    assert envelope["payload"]["outcome"] == "won"
    assert envelope["payload"]["lift"] == 0.42
    assert envelope["payload"]["kpi_weight"] == 1.0
    assert envelope["payload"]["email"] == "attacker@example.com"
