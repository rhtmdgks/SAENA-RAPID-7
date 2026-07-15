"""Unit tests: record<->row mapping + JSON round-trips + SF-4 re-verification.

No database: these drive the pure `mapping` module directly. The SF-4 tests
build a real `EvidenceBundleManifest`, serialize it the way the adapter would,
then TAMPER the serialized row and prove `row_to_evidence_bundle` raises rather
than handing back a corrupted-but-valid-looking bundle.
"""

from __future__ import annotations

import json

import pytest
from saena_domain.measurement import evidence
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    MeasurementWindow,
    OutcomeDecisionRecord,
)
from saena_experiment_attribution.persistence import fingerprint as fp
from saena_experiment_attribution.persistence import mapping

_HASH = "sha256:" + "e" * 64


# --- JSON serialization on frozen (deep-frozen) records ----------------------------


def test_to_jsonb_text_thaws_deep_frozen_payload() -> None:
    rec = ConfirmationRecord(
        tenant_id="t",
        confirmation_key="k",
        measurement_kind="m",
        payload={"nested": {"list": [1, 2]}, "flat": "v"},
    )
    # rec.payload is a MappingProxyType with nested tuples — json.dumps must
    # still serialize it via the thaw path.
    text = mapping.to_jsonb_text(rec.payload)
    assert json.loads(text) == {"nested": {"list": [1, 2]}, "flat": "v"}


def test_confirmation_row_round_trip() -> None:
    rec = ConfirmationRecord(
        tenant_id="t", confirmation_key="k", measurement_kind="m", payload={"a": 1}
    )
    bind = mapping.confirmation_to_bind("t", "k", rec, "fp")
    # Simulate the RETURNING/SELECT projection (payload::text) the adapter reads.
    row = {
        "tenant_id": bind["tenant_id"],
        "confirmation_key": bind["confirmation_key"],
        "measurement_kind": bind["measurement_kind"],
        "payload": bind["payload"],
    }
    assert mapping.row_to_confirmation(row) == rec


def test_window_row_round_trip_including_null_ends_at() -> None:
    w = MeasurementWindow(
        tenant_id="t",
        experiment_id="e",
        starts_at="2026-07-14T00:00:00Z",
        ends_at=None,
        policy_version="1.0.0",
    )
    bind = mapping.window_to_bind("t", w, "fp")
    row = {
        k: bind[k] for k in ("tenant_id", "experiment_id", "starts_at", "ends_at", "policy_version")
    }
    assert mapping.row_to_window(row) == w


def test_decision_row_round_trip() -> None:
    d = OutcomeDecisionRecord(
        tenant_id="t",
        decision_key=("exp-1", "primary"),
        outcome="lift_confirmed",
        evidence_bundle_ref=_HASH,
        policy_metadata={"policy_version": "1.0.0"},
    )
    bind = mapping.decision_to_bind("t", d, "fp")
    row = {
        "tenant_id": bind["tenant_id"],
        "experiment_id": bind["experiment_id"],
        "decision_slot": bind["decision_slot"],
        "outcome": bind["outcome"],
        "evidence_bundle_ref": bind["evidence_bundle_ref"],
        "policy_metadata": bind["policy_metadata"],
    }
    assert mapping.row_to_decision(row) == d


# --- evidence bundle: bare (chain-less) manifests pass through ----------------------


def test_bare_manifest_bundle_round_trips_without_verification() -> None:
    # A conformance-fixture-style manifest with no commitment chain has nothing
    # to verify and must round-trip cleanly.
    b = EvidenceBundle(tenant_id="t", manifest={"artifacts": ["x"], "count": 1})
    bind = mapping.evidence_to_bind("t", _HASH, b, "fp")
    row = {"tenant_id": "t", "manifest_hash": _HASH, "manifest": bind["manifest"]}
    assert mapping.row_to_evidence_bundle(row) == b


# --- SF-4: chain-bearing manifests are re-verified on read ------------------------


def _sealed_manifest() -> evidence.EvidenceBundleManifest:
    entry = evidence.EvidenceEntry(
        kind=evidence.EvidenceKind.REGISTRATION,
        ref=evidence.EvidenceRef(uri="artifact://reg-1", content_hash="sha256:" + "a" * 64),
    )
    entry2 = evidence.EvidenceEntry(
        kind=evidence.EvidenceKind.DID_OUTPUTS,
        ref=evidence.EvidenceRef(uri="artifact://did-1", content_hash="sha256:" + "b" * 64),
    )
    return evidence.EvidenceBundleManifest.seal(
        tenant_id="t", run_id="run-1", experiment_id="exp-1", entries=(entry, entry2)
    )


def _row_for(manifest_dict: dict) -> dict:
    return {
        "tenant_id": "t",
        "manifest_hash": _HASH,
        "manifest": json.dumps(manifest_dict, separators=(",", ":")),
    }


def test_intact_chain_manifest_reads_back_ok() -> None:
    manifest = _sealed_manifest()
    row = _row_for(manifest.model_dump(mode="json"))
    bundle = mapping.row_to_evidence_bundle(row)
    assert bundle.manifest["manifest_hash"] == manifest.manifest_hash


def test_tampered_entry_manifest_read_raises_integrity_error() -> None:
    manifest = _sealed_manifest()
    tampered = manifest.model_dump(mode="json")
    # Tamper an entry's content WITHOUT recomputing the sealed commitment chain
    # — exactly a malicious/corrupt DB row.
    tampered["entries"][0]["ref"]["uri"] = "artifact://SWAPPED"
    with pytest.raises(mapping.EvidenceIntegrityError):
        mapping.row_to_evidence_bundle(_row_for(tampered))


def test_reordered_entries_manifest_read_raises_integrity_error() -> None:
    manifest = _sealed_manifest()
    reordered = manifest.model_dump(mode="json")
    reordered["entries"] = list(reversed(reordered["entries"]))
    # entry_commitments/manifest_hash left as sealed for the original order.
    with pytest.raises(mapping.EvidenceIntegrityError):
        mapping.row_to_evidence_bundle(_row_for(reordered))


def test_tampered_head_hash_read_raises_integrity_error() -> None:
    manifest = _sealed_manifest()
    forged = manifest.model_dump(mode="json")
    forged["manifest_hash"] = "sha256:" + "f" * 64
    with pytest.raises(mapping.EvidenceIntegrityError):
        mapping.row_to_evidence_bundle(_row_for(forged))


def test_chain_declaring_but_malformed_manifest_raises_integrity_error() -> None:
    # Declares a chain (manifest_hash present) but is otherwise unparseable as a
    # manifest — fail closed, never pass through unverified.
    row = _row_for({"manifest_hash": "sha256:" + "0" * 64, "entries": "not-a-list"})
    with pytest.raises(mapping.EvidenceIntegrityError):
        mapping.row_to_evidence_bundle(row)


def test_explicit_verify_manifest_call_fires_independent_of_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SF-2 (w5-10 critic): prove the EXPLICIT `verify_manifest` check in
    `_reverify_manifest` fires on its own — not merely as a shadow of
    `EvidenceBundleManifest.model_validate`'s constructor-time chain validator.

    `model_validate` re-runs `_check_commitment_chain`, so a chain-broken
    manifest structurally cannot come OUT of it — on every ordinary path the
    constructor raises first and the explicit post-validate check never sees a
    broken object. That is exactly the gap the explicit call exists to close:
    a reconstruction path that SKIPS validation (`model_construct`, a future
    cached/msgpack/ORM hydration, a pydantic behavior change). Simulate such a
    path by monkeypatching `model_validate` to return a `model_construct`-forged
    object whose sealed chain does not match its entries, and assert the
    explicit check (mapping.py's `if not intact: raise`) catches it with the
    re-verification error (divergence_index present), NOT the
    reconstruct-failure error.
    """
    genuine = _sealed_manifest()
    # Forge WITHOUT running validators: entries reversed, sealed chain kept for
    # the ORIGINAL order — verify_manifest must report (False, 0).
    forged = evidence.EvidenceBundleManifest.model_construct(
        tenant_id=genuine.tenant_id,
        run_id=genuine.run_id,
        experiment_id=genuine.experiment_id,
        entries=tuple(reversed(genuine.entries)),
        entry_commitments=genuine.entry_commitments,
        manifest_hash=genuine.manifest_hash,
    )
    intact, index = evidence.verify_manifest(forged)
    assert intact is False and index == 0  # the forgery IS chain-broken

    monkeypatch.setattr(
        evidence.EvidenceBundleManifest,
        "model_validate",
        classmethod(lambda cls, _data, **_kw: forged),
    )
    with pytest.raises(mapping.EvidenceIntegrityError) as excinfo:
        mapping.row_to_evidence_bundle(_row_for(genuine.model_dump(mode="json")))
    # The RE-VERIFICATION branch fired (it alone carries divergence_index),
    # not the try/except reconstruct-failure branch.
    assert excinfo.value.context["divergence_index"] == 0
    assert "re-verification" in str(excinfo.value)


def test_integrity_error_is_log_safe() -> None:
    manifest = _sealed_manifest()
    tampered = manifest.model_dump(mode="json")
    tampered["entries"][0]["ref"]["uri"] = "artifact://SWAPPED"
    try:
        mapping.row_to_evidence_bundle(_row_for(tampered))
    except mapping.EvidenceIntegrityError as exc:
        payload = exc.to_dict()
        assert payload["tenant_id"] == "t"
        assert payload["manifest_hash"] == _HASH
        # No raw manifest content leaked into the error payload.
        assert "SWAPPED" not in json.dumps(payload)
    else:  # pragma: no cover
        pytest.fail("expected EvidenceIntegrityError")


def test_evidence_bind_fingerprint_matches_module_helper() -> None:
    # The bind fingerprint the adapter would store equals the pure helper's
    # output for the thawed manifest.
    b = EvidenceBundle(tenant_id="t", manifest={"k": "v"})
    expected = fp.bundle_fingerprint(tenant_id="t", manifest={"k": "v"})
    bind = mapping.evidence_to_bind("t", _HASH, b, expected)
    assert bind["content_fingerprint"] == expected
