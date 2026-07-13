"""AsyncAPI channel composition instance proof (w1-11, approved plan §2
"asyncapi" gate + ADR-0013 appendix 3 instances vs their channels).

For each of the 16 channels (12 CONFIRMED-v1 + 4 Wave 4 NEW, w4-10
Contracts Steward): builds the channel's allOf-overlay
schema (envelope + event_type/context_type const pins + payload
substitution), resolves it (jsonschema + referencing.Registry, same
proven local-resolution pattern as test_envelope_fixtures.py /
_support.build_validator -- rev.3 landed 3-token event_type patterns so
some channel event_types are now satisfiable that previously were not),
and asserts:

  - at least one VALID instance per channel satisfies the full overlay.
  - a MUTANT (extra top-level property) instance is rejected per channel
    (envelope frozen-class unevaluatedProperties:false is the closing
    mechanism that catches this).
  - the quality.gate.passed/failed R4 pair: a passed instance without
    `failures` passes both channels' semantics correctly (passed-shaped
    accepted by quality.gate.passed, rejected by quality.gate.failed's
    required:[failures] overlay) and vice versa for a failed instance.
  - ADR-0013 appendix's 3 example instances validate against their
    documented channels (patch.unit.completed.v1 / adapter.config.updated.v1
    [envelope-only system channel, not one of the 16 -- validated against
    the bare envelope only] / strategy.card.eligible.v1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"
JSON_SCHEMA_DIR = CONTRACTS_DIR / "json-schema"
ASYNCAPI_PATH = CONTRACTS_DIR / "asyncapi" / "saena-events" / "v1" / "asyncapi.yaml"
ASYNCAPI_DIR = ASYNCAPI_PATH.parent
ENVELOPE_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "envelope" / "valid"

ENVELOPE_SCHEMA_PATH = (
    JSON_SCHEMA_DIR / "envelope" / "event-envelope" / "v1" / "event-envelope.schema.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_yaml_refs(node: Any, base_dir: Path, doc_root: Any = None) -> Any:
    """Recursively resolve every {'$ref': '<relative-path>[#<pointer>]'}
    node in a parsed AsyncAPI YAML fragment into its target JSON Schema
    document's content, inlining `#/$defs/...`-style fragments via a
    plain JSON Pointer walk. AsyncAPI's own internal refs
    ("#/channels/...") are left untouched (out of scope -- only the
    embedded JSON Schema $refs inside `payload.schema` need resolving
    for this module's purpose).

    `doc_root` tracks the root of whichever cross-file document is
    currently "active" (the most recently `$ref`-loaded external JSON
    Schema file) so that a bare same-document self-ref inside that
    document -- `{"$ref": "#"}` (root) or `{"$ref": "#/$defs/..."}`
    (pointer) -- resolves against THAT document's own root, not against
    whatever unrelated top-level object happens to currently be under
    construction. Needed for common/engine-id/v1's own
    `$defs.engine_required_payload.properties.engine_id` field, which is
    `{"$ref": "#"}` pointing back at engine-id.schema.json's OWN root
    (the closed string enum) -- when this fragment is pointer-walked out
    of engine-id.schema.json (only `$defs/engine_required_payload` is
    extracted, not the whole document), that root type:string+enum
    information is otherwise lost, and jsonschema would instead resolve
    the un-substituted "#" against the top of the WHOLE composed overlay
    schema (type:object) -- exactly backward. Verified via w4-10's
    citation-normalized/observation-captured/experiment-registered/
    experiment-anchored channels, the first real users of the
    engine_required_payload fragment in this catalog.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        is_asyncapi_internal_ref = isinstance(ref, str) and (
            ref.startswith("#/channels") or ref.startswith("#/components")
        )
        if isinstance(ref, str) and not is_asyncapi_internal_ref:
            path_part, _, fragment = ref.partition("#")
            if path_part:
                target_path = (base_dir / path_part).resolve()
                target_doc = _load_json(target_path)
                if fragment:
                    pointer_parts = [p for p in fragment.split("/") if p]
                    pointed: Any = target_doc
                    for part in pointer_parts:
                        pointed = pointed[part]
                    return _resolve_yaml_refs(pointed, target_path.parent, doc_root=target_doc)
                return _resolve_yaml_refs(target_doc, target_path.parent, doc_root=target_doc)
            if doc_root is not None:
                # Bare same-document self-ref ("#" or "#/$defs/...") --
                # resolve against the currently-active cross-file
                # document's own root, not leave it un-substituted.
                pointer_parts = [p for p in fragment.split("/") if p]
                pointed = doc_root
                for part in pointer_parts:
                    pointed = pointed[part]
                if not pointer_parts and isinstance(pointed, dict) and "$defs" in pointed:
                    # Bare "#" (whole-document root self-ref, e.g.
                    # common/engine-id/v1's own
                    # $defs.engine_required_payload.properties.engine_id
                    # pointing back at the enclosing document's root):
                    # drop "$defs" before recursing. $defs is a pure
                    # reference-target bag -- it contributes no validation
                    # constraint to the node itself -- and re-descending
                    # into it here would re-encounter the very same "#"
                    # self-ref inside $defs.engine_required_payload,
                    # producing unbounded structural recursion (a
                    # genuinely cyclic schema that eager physical inlining
                    # cannot fully expand; jsonschema's own lazy
                    # registry-based $ref resolution has no such problem,
                    # but this module's ad-hoc inliner does). Safe: no
                    # other branch of this recursion still needs to reach
                    # this document's $defs after this substitution.
                    pointed = {k: v for k, v in pointed.items() if k != "$defs"}
                return _resolve_yaml_refs(pointed, base_dir, doc_root=doc_root)
        return {k: _resolve_yaml_refs(v, base_dir, doc_root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_yaml_refs(item, base_dir, doc_root) for item in node]
    return node


def _channel_validator(channel_name: str) -> Draft202012Validator:
    """Build a Draft202012Validator for one AsyncAPI channel's message
    payload.schema (the allOf overlay), with all embedded JSON Schema
    $refs pre-resolved (inlined) via `_resolve_yaml_refs` and a
    referencing.Registry seeded with the envelope + common schemas the
    inlined content itself still $refs internally (e.g. envelope's own
    "../../../common/identifiers/..." references, which after inlining
    are relative to the ORIGINAL schema file's directory, not
    ASYNCAPI_DIR -- resolved by loading each referenced document by
    absolute $id into the registry, same as _support.build_validator).
    """
    document = _load_yaml(ASYNCAPI_PATH)
    channel = document["channels"][channel_name]
    (message,) = channel["messages"].values()
    raw_schema = message["payload"]["schema"]
    resolved_schema = _resolve_yaml_refs(raw_schema, ASYNCAPI_DIR)

    # The resolved (inlined) schema no longer has its own $id (envelope's
    # $id was stripped along with the rest of the document wrapper by the
    # allOf-branch inlining -- only the envelope's INTERNAL "#/$defs/..."
    # refs survive as literal "#/..." strings, which is fine since they
    # resolve against whichever branch object jsonschema is currently
    # inside). Registry only needs to carry the common/ files the
    # envelope's OWN properties still $ref by relative path -- but those
    # were already inlined too (recursive resolution), so no additional
    # registry entries are required for the top-level allOf; only for any
    # payload sub-schema $ref that itself points at common/ (e.g.
    # quality-gate-result's failures -> common/error-detail). Build an
    # empty-but-functional registry; `_resolve_yaml_refs` already inlined
    # every cross-file $ref recursively, so no external resolution is
    # needed at validate time.
    registry: Registry = Registry()
    return Draft202012Validator(resolved_schema, registry=registry)


ALL_CHANNEL_NAMES = [
    "repo.intaken.v1",
    "site.inventory.completed.v1",
    "demand.graph.versioned.v1",
    "observation.captured.v1",
    "citation.normalized.v1",
    "plan.contract.proposed.v1",
    "plan.contract.approved.v1",
    "patch.unit.completed.v1",
    "quality.gate.passed.v1",
    "quality.gate.failed.v1",
    "experiment.outcome.observed.v1",
    "strategy.card.eligible.v1",
    # Wave 4 NEW channels (w4-10 Contracts Steward).
    "entity.graph.versioned.v1",
    "claim.evidence.versioned.v1",
    "experiment.registered.v1",
    "experiment.anchored.v1",
    # Wave 5 NEW channel (w5-02 Contracts Steward, channel #17).
    "deployment.confirmed.v1",
]

TENANT_ENVELOPE_COMMON: dict[str, Any] = {
    "event_id": "018f3a1e-7c2b-7c3e-9b1a-4e2f1a9d3c7b",
    "context_type": "tenant",
    "tenant_id": "acme-corp",
    "run_id": "run-0001",
    "schema_version": "1.0.0",
    "producer": "test-producer",
    "occurred_at": "2026-07-12T09:14:32Z",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "idempotency_key": "acme-corp:run-0001:evt-0001",
}

AGGREGATE_ENVELOPE_COMMON: dict[str, Any] = {
    "event_id": "018f3a20-9e4d-7a1b-b3c5-2d6f8a1c4e9b",
    "context_type": "aggregate",
    "schema_version": "1.0.0",
    "producer": "test-producer",
    "occurred_at": "2026-07-12T11:47:03Z",
    "trace_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "idempotency_key": "strategy-card:aggregate-scope-014:2026-07-12",
    "aggregate_scope_id": "aggregate-scope-014",
    "cohort_size": 12,
    "privacy_threshold": 5,
    "de_identification_status": "k_anonymized",
    "lineage_audit_ref": "sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e",
}

# Per-channel: (envelope-common template, event_type, payload).
_CHANNEL_INSTANCE_SPECS: dict[str, tuple[dict[str, Any], str, dict[str, Any]]] = {
    "repo.intaken.v1": (
        TENANT_ENVELOPE_COMMON,
        "repo.intaken.v1",
        {
            "repo_commit": "cccccccccccccccccccccccccccccccccccccccc",
            "content_hash": "sha256:" + "a" * 64,
            "snapshot_uri": "s3://saena-snapshots/run-0001/snapshot.tar.gz",
        },
    ),
    "site.inventory.completed.v1": (
        TENANT_ENVELOPE_COMMON,
        "site.inventory.completed.v1",
        {"site_id": "site-0001", "inventory_version": "v1"},
    ),
    "demand.graph.versioned.v1": (
        TENANT_ENVELOPE_COMMON,
        "demand.graph.versioned.v1",
        {
            "project_id": "proj-0001",
            "graph_version": "v1",
            "cluster_count": 42,
            "provenance_ref": "sha256:" + "a" * 64,
        },
    ),
    "observation.captured.v1": (
        TENANT_ENVELOPE_COMMON,
        "observation.captured.v1",
        {
            "engine_id": "chatgpt-search",
            "observation_id": "obs-0001",
            "artifact_hash": "sha256:" + "e" * 64,
        },
    ),
    "citation.normalized.v1": (
        TENANT_ENVELOPE_COMMON,
        "citation.normalized.v1",
        {
            "engine_id": "chatgpt-search",
            "citation_id": "cite-0001",
            "normalized_uri": "https://example.com/product/widget",
            "content_hash": "sha256:" + "d" * 64,
        },
    ),
    "entity.graph.versioned.v1": (
        TENANT_ENVELOPE_COMMON,
        "entity.graph.versioned.v1",
        {
            "project_id": "proj-0001",
            "graph_version": "v1",
            "entity_count": 17,
            "provenance_ref": "sha256:" + "b" * 64,
        },
    ),
    "claim.evidence.versioned.v1": (
        TENANT_ENVELOPE_COMMON,
        "claim.evidence.versioned.v1",
        {
            "project_id": "proj-0001",
            "ledger_version": "v1",
            "claim_count": 8,
            "evidence_count": 21,
            "provenance_ref": "sha256:" + "c" * 64,
        },
    ),
    "experiment.registered.v1": (
        TENANT_ENVELOPE_COMMON,
        "experiment.registered.v1",
        {
            "engine_id": "chatgpt-search",
            "experiment_id": "exp-0001",
            "canonical_hash": "sha256:" + "f" * 64,
        },
    ),
    "experiment.anchored.v1": (
        TENANT_ENVELOPE_COMMON,
        "experiment.anchored.v1",
        {
            "engine_id": "chatgpt-search",
            "experiment_id": "exp-0001",
            "canonical_hash": "sha256:" + "f" * 64,
            "previous_hash": None,
        },
    ),
    "plan.contract.proposed.v1": (
        TENANT_ENVELOPE_COMMON,
        "plan.contract.proposed.v1",
        {
            "contract_uri": "s3://saena-plans/run-0001/plan.json",
            "contract_hash": "sha256:" + "a" * 64,
            "base_commit": "cccccccccccccccccccccccccccccccccccccccc",
        },
    ),
    "plan.contract.approved.v1": (
        TENANT_ENVELOPE_COMMON,
        "plan.contract.approved.v1",
        {"contract_hash": "sha256:" + "a" * 64, "decision": "approved"},
    ),
    "patch.unit.completed.v1": (
        TENANT_ENVELOPE_COMMON,
        "patch.unit.completed.v1",
        {"patch_unit_id": "PU-01", "worktree_commit": "cccffff"},
    ),
    "quality.gate.passed.v1": (
        TENANT_ENVELOPE_COMMON,
        "quality.gate.passed.v1",
        {"patch_unit_id": "PU-01", "gate_id": "gate-lint"},
    ),
    "quality.gate.failed.v1": (
        TENANT_ENVELOPE_COMMON,
        "quality.gate.failed.v1",
        {
            "patch_unit_id": "PU-01",
            "gate_id": "gate-test",
            "failures": [
                {
                    "error_code": "saena.validation.assertion_failed",
                    "retryable": False,
                    "summary": "assertion failed",
                }
            ],
        },
    ),
    "experiment.outcome.observed.v1": (
        TENANT_ENVELOPE_COMMON,
        "experiment.outcome.observed.v1",
        {
            "engine_id": "chatgpt-search",
            "experiment_id": "exp-0001",
            "registration_canonical_hash": "sha256:" + "f" * 64,
            "window": {
                "started_at": "2026-07-07T00:00:00Z",
                "ended_at": "2026-07-14T00:00:00Z",
                "clock_anchor": "deployment_confirmed",
            },
            "deployment_confirmation_ref": "dep-0001",
            "per_signal_results": [
                {
                    "outcome_layer": "citation",
                    "metric_id": "citation_share",
                    "evidence_basis_id": "basis-citation-1",
                    "treatment_raw_delta": 0.12,
                    "control_raw_delta": 0.02,
                    "net_of_control_lift": 0.10,
                    "sample_counts": {"treatment": 120, "control": 118},
                    "insufficient": False,
                },
                {
                    "outcome_layer": "prominence",
                    "metric_id": "answer_prominence",
                    "evidence_basis_id": "basis-prominence-1",
                    "treatment_raw_delta": 0.08,
                    "control_raw_delta": 0.01,
                    "net_of_control_lift": 0.07,
                    "sample_counts": {"treatment": 120, "control": 118},
                    "insufficient": False,
                },
            ],
            "b_verdict": "pass",
            "raw_view": {"citation_share_treatment": 0.42},
            "control_adjusted_view": {"citation_share_net": 0.10},
            "confidence": 0.86,
            "evidence_bundle_ref": {
                "manifest_hash": "sha256:" + "a" * 64,
                "artifact_ref": "https://evidence.example.com/bundles/exp-0001",
            },
            "grs_policy": {
                "version": "grs-v1",
                "hash": "sha256:" + "b" * 64,
                "provenance": "test_fixture",
            },
        },
    ),
    "strategy.card.eligible.v1": (
        AGGREGATE_ENVELOPE_COMMON,
        "strategy.card.eligible.v1",
        {
            "card_candidate_ref": "card-cand-0142",
            "source_outcome": {
                "b_verdict": "pass",
                "evidence_bundle_manifest_hash": "sha256:" + "a" * 64,
            },
        },
    ),
    "deployment.confirmed.v1": (
        TENANT_ENVELOPE_COMMON,
        "deployment.confirmed.v1",
        {
            "deployment_id": "dep-0001",
            "registration_ref": {
                "experiment_id": "exp-0001",
                "registration_canonical_hash": "sha256:" + "f" * 64,
            },
            "deployed_commit_sha": "abcdef0123456789abcdef0123456789abcdef01",
            "deployment_target": {"kind": "site", "identifier": "primary-site"},
            "confirmer": {"identity": "customer-ci-bot", "method": "ci_pipeline"},
            "confirmed_at": "2026-07-14T00:00:00Z",
        },
    ),
}


def _build_instance(channel_name: str) -> dict[str, Any]:
    envelope_common, event_type, payload = _CHANNEL_INSTANCE_SPECS[channel_name]
    instance = dict(envelope_common)
    instance["event_type"] = event_type
    instance["payload"] = payload
    return instance


@pytest.mark.parametrize("channel_name", ALL_CHANNEL_NAMES)
def test_valid_instance_satisfies_channel_overlay(channel_name: str) -> None:
    validator = _channel_validator(channel_name)
    instance = _build_instance(channel_name)
    errors = list(validator.iter_errors(instance))
    assert not errors, (
        f"{channel_name}: expected composed instance to satisfy the allOf overlay, got: "
        + "; ".join(e.message for e in errors)
    )


@pytest.mark.parametrize("channel_name", ALL_CHANNEL_NAMES)
def test_mutant_extra_top_level_property_rejected(channel_name: str) -> None:
    """Envelope's frozen-class unevaluatedProperties:false (per branch)
    must reject an undeclared top-level property even through the
    allOf-overlay composition.
    """
    validator = _channel_validator(channel_name)
    instance = _build_instance(channel_name)
    instance["mutant_extra_field"] = "not allowed"
    errors = list(validator.iter_errors(instance))
    assert errors, f"{channel_name}: expected the mutant extra-property instance to be rejected"


def test_quality_gate_passed_failed_r4_pair() -> None:
    """R4 (approved plan §1.1 ruling R4/R8): failed.v1 ⇒ failures required
    / passed.v1 ⇒ failures key absent, enforced at the channel/operation
    layer overlay -- prove both directions with a cross-channel swap.
    """
    passed_validator = _channel_validator("quality.gate.passed.v1")
    failed_validator = _channel_validator("quality.gate.failed.v1")

    passed_instance = _build_instance("quality.gate.passed.v1")
    failed_instance = _build_instance("quality.gate.failed.v1")

    # Direction 1: the canonical passed instance (no failures) satisfies
    # quality.gate.passed's overlay.
    assert not list(passed_validator.iter_errors(passed_instance))
    # Direction 2: the canonical failed instance (>=1 failures) satisfies
    # quality.gate.failed's overlay.
    assert not list(failed_validator.iter_errors(failed_instance))

    # Direction 3: a passed-shaped instance (no failures) does NOT satisfy
    # quality.gate.failed's overlay (which requires failures).
    swapped_event_type = dict(passed_instance)
    swapped_event_type["event_type"] = "quality.gate.failed.v1"
    assert list(failed_validator.iter_errors(swapped_event_type)), (
        "expected a failures-less instance to be REJECTED by quality.gate.failed's overlay"
    )

    # Direction 4: a failed-shaped instance (with failures) does NOT
    # satisfy quality.gate.passed's overlay (which forbids failures).
    swapped_event_type_2 = dict(failed_instance)
    swapped_event_type_2["event_type"] = "quality.gate.passed.v1"
    assert list(passed_validator.iter_errors(swapped_event_type_2)), (
        "expected a with-failures instance to be REJECTED by quality.gate.passed's overlay"
    )


# --------------------------------------------------------------------------
# ADR-0013 appendix 3 example instances vs their channels.
# --------------------------------------------------------------------------


def test_appendix_tenant_example_validates_against_patch_unit_completed_channel() -> None:
    validator = _channel_validator("patch.unit.completed.v1")
    fixture_path = ENVELOPE_FIXTURES_DIR / "tenant-patch-unit-completed-v1.json"
    instance = _load_json(fixture_path)
    errors = list(validator.iter_errors(instance))
    assert not errors, (
        "expected the ADR-0013 appendix TenantContext example to satisfy "
        f"patch.unit.completed.v1's channel overlay, got: {[e.message for e in errors]}"
    )


def test_appendix_aggregate_example_validates_against_strategy_card_eligible_channel() -> None:
    validator = _channel_validator("strategy.card.eligible.v1")
    fixture_path = ENVELOPE_FIXTURES_DIR / "aggregate-strategy-card-eligible-v1.json"
    instance = _load_json(fixture_path)
    errors = list(validator.iter_errors(instance))
    assert not errors, (
        "expected the ADR-0013 appendix AggregateContext example to satisfy "
        f"strategy.card.eligible.v1's channel overlay, got: {[e.message for e in errors]}"
    )


def test_appendix_system_example_validates_against_bare_envelope_only() -> None:
    """adapter.config.updated.v1 is the SystemContext appendix example but
    is NOT one of the 16 confirmed AsyncAPI channels (it predates the
    CONFIRMED v1 catalog) -- validated against the bare envelope schema
    only, not any channel overlay, documenting that distinction rather
    than silently assuming it has a channel.
    """
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    identifiers_path = JSON_SCHEMA_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
    engine_id_path = JSON_SCHEMA_DIR / "common" / "engine-id" / "v1" / "engine-id.schema.json"
    identifiers = _load_json(identifiers_path)
    engine_id = _load_json(engine_id_path)
    registry: Registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (identifiers["$id"], Resource.from_contents(identifiers)),
            (engine_id["$id"], Resource.from_contents(engine_id)),
        ]
    )
    validator = Draft202012Validator(schema, registry=registry)

    fixture_path = ENVELOPE_FIXTURES_DIR / "system-adapter-config-updated-v1.json"
    instance = _load_json(fixture_path)
    errors = list(validator.iter_errors(instance))
    assert not errors, (
        "expected the ADR-0013 appendix SystemContext example to satisfy the bare envelope, "
        f"got: {[e.message for e in errors]}"
    )
    assert "adapter.config.updated.v1" not in ALL_CHANNEL_NAMES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
