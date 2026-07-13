"""Unit tests: fingerprint parity with the in-memory reference (w5-10) — no DB.

The idempotency contract is only sound if the Postgres adapter's
`content_fingerprint` is byte-identical to the fingerprint the in-memory
reference (`saena_domain.measurement.ports._*_fingerprint`) computes for the
same record — otherwise the two backends could disagree on "same content", and
the shared conformance suite's byte-identity guarantee would be a lie. These
tests pin that parity against the reference's OWN private helpers.
"""

from __future__ import annotations

from saena_domain.measurement import ports as ref
from saena_experiment_attribution.persistence import fingerprint as fp


def test_confirmation_fingerprint_matches_reference() -> None:
    rec = ref.ConfirmationRecord(
        tenant_id="acme-co",
        confirmation_key="acme-co:run-1:cap-1",
        measurement_kind="citation_confirmation",
        payload={"b": 2, "a": {"nested": [3, 1, 2]}},
    )
    mine = fp.confirmation_fingerprint(
        tenant_id=rec.tenant_id,
        confirmation_key=rec.confirmation_key,
        measurement_kind=rec.measurement_kind,
        payload={"b": 2, "a": {"nested": [3, 1, 2]}},
    )
    assert mine == ref._confirmation_fingerprint(rec)


def test_window_fingerprint_matches_reference() -> None:
    w = ref.MeasurementWindow(
        tenant_id="acme-co",
        experiment_id="exp-1",
        starts_at="2026-07-14T00:00:00Z",
        ends_at=None,
        policy_version="1.0.0",
    )
    mine = fp.window_fingerprint(
        tenant_id=w.tenant_id,
        experiment_id=w.experiment_id,
        starts_at=w.starts_at,
        ends_at=w.ends_at,
        policy_version=w.policy_version,
    )
    assert mine == ref._window_fingerprint(w)


def test_decision_fingerprint_matches_reference() -> None:
    d = ref.OutcomeDecisionRecord(
        tenant_id="acme-co",
        decision_key=("exp-1", "primary"),
        outcome="lift_confirmed",
        evidence_bundle_ref="sha256:" + "e" * 64,
        policy_metadata={"z": 1, "a": 2},
    )
    mine = fp.decision_fingerprint(
        tenant_id=d.tenant_id,
        decision_key=d.decision_key,
        outcome=d.outcome,
        evidence_bundle_ref=d.evidence_bundle_ref,
        policy_metadata={"z": 1, "a": 2},
    )
    assert mine == ref._decision_fingerprint(d)


def test_bundle_fingerprint_matches_reference() -> None:
    b = ref.EvidenceBundle(tenant_id="acme-co", manifest={"artifacts": ["x"], "count": 1})
    mine = fp.bundle_fingerprint(tenant_id=b.tenant_id, manifest={"artifacts": ["x"], "count": 1})
    assert mine == ref._bundle_fingerprint(b)


def test_fingerprint_is_key_order_independent() -> None:
    # JCS sorts keys, so differently-ordered-but-equal payloads fingerprint equal.
    a = fp.confirmation_fingerprint(
        tenant_id="t", confirmation_key="k", measurement_kind="m", payload={"x": 1, "y": 2}
    )
    b = fp.confirmation_fingerprint(
        tenant_id="t", confirmation_key="k", measurement_kind="m", payload={"y": 2, "x": 1}
    )
    assert a == b


def test_fingerprint_distinguishes_different_content() -> None:
    a = fp.bundle_fingerprint(tenant_id="t", manifest={"v": 1})
    b = fp.bundle_fingerprint(tenant_id="t", manifest={"v": 2})
    assert a != b
