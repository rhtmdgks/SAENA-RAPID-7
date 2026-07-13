"""Record-invariant validation + error taxonomy (w5-09).

The frozen records reject partial/empty construction up front — this is what
makes "no partial state" a property of the API shape rather than a runtime
transaction. Also pins the `saena.<category>.<reason>` error-code taxonomy and
the log-safe `to_dict` shape every services-layer ProblemDetail mapper reuses.
"""

from __future__ import annotations

import pytest
from measurement_factories import TENANT_A, make_confirmation
from saena_domain.measurement.errors import (
    AppendOnlyViolationError,
    EvidenceHashMismatchError,
    IdempotencyConflictError,
    MeasurementError,
    NotFoundError,
    TenantIsolationError,
)
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    InMemoryConfirmationStore,
    MeasurementWindow,
    OutcomeDecisionRecord,
)


@pytest.mark.parametrize(
    ("field", "value"),
    [("tenant_id", ""), ("confirmation_key", ""), ("measurement_kind", "")],
)
def test_confirmation_record_rejects_empty_required_field(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        make_confirmation(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", ""),
        ("experiment_id", ""),
        ("starts_at", ""),
        ("policy_version", ""),
    ],
)
def test_measurement_window_rejects_empty_required_field(field: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "tenant_id": TENANT_A,
        "experiment_id": "exp-1",
        "starts_at": "2026-07-14T00:00:00Z",
        "ends_at": None,
        "policy_version": "1.0.0",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        MeasurementWindow(**kwargs)  # type: ignore[arg-type]


def test_measurement_window_allows_none_ends_at() -> None:
    # ends_at=None (still-open window) is valid; only the required fields are
    # non-empty-checked.
    w = MeasurementWindow(
        tenant_id=TENANT_A,
        experiment_id="exp-1",
        starts_at="2026-07-14T00:00:00Z",
        ends_at=None,
        policy_version="1.0.0",
    )
    assert w.ends_at is None


@pytest.mark.parametrize(
    "bad_key",
    [("only-one",), ("a", "b", "c"), ("", "primary"), ("exp", "")],
)
def test_decision_rejects_malformed_key(bad_key: object) -> None:
    with pytest.raises(ValueError):
        OutcomeDecisionRecord(
            tenant_id=TENANT_A,
            decision_key=bad_key,  # type: ignore[arg-type]
            outcome="lift_confirmed",
            evidence_bundle_ref="sha256:" + "a" * 64,
            policy_metadata={"policy_version": "1.0.0"},
        )


def test_decision_rejects_empty_tenant_and_outcome() -> None:
    with pytest.raises(ValueError):
        OutcomeDecisionRecord(
            tenant_id="",
            decision_key=("exp-1", "primary"),
            outcome="x",
            evidence_bundle_ref="sha256:" + "a" * 64,
            policy_metadata={"policy_version": "1.0.0"},
        )
    with pytest.raises(ValueError):
        OutcomeDecisionRecord(
            tenant_id=TENANT_A,
            decision_key=("exp-1", "primary"),
            outcome="",
            evidence_bundle_ref="sha256:" + "a" * 64,
            policy_metadata={"policy_version": "1.0.0"},
        )


def test_evidence_bundle_rejects_empty_tenant() -> None:
    with pytest.raises(ValueError):
        EvidenceBundle(tenant_id="", manifest={"x": 1})


def test_put_confirmation_rejects_empty_key() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    with pytest.raises(ValueError):
        store.put_confirmation(TENANT_A, "", rec)


def test_confirmation_payload_is_read_only_proxy() -> None:
    rec = ConfirmationRecord(
        tenant_id=TENANT_A,
        confirmation_key="k",
        measurement_kind="kind",
        payload={"a": 1},
    )
    with pytest.raises(TypeError):
        rec.payload["a"] = 2  # MappingProxyType is read-only


def test_deep_freeze_nested_dict_and_list_are_immutable() -> None:
    # Critic should-fix 1 (w5-09 review): the freeze must be DEEP — nested
    # dicts are MappingProxyType, nested lists are tuples, recursively.
    rec = ConfirmationRecord(
        tenant_id=TENANT_A,
        confirmation_key="k",
        measurement_kind="kind",
        payload={"nested": {"deep": {"x": 1}}, "items": [{"y": 2}], "n": 3},
    )
    with pytest.raises(TypeError):
        rec.payload["nested"]["deep"] = {}  # nested proxy is read-only
    with pytest.raises(TypeError):
        rec.payload["nested"]["deep"]["x"] = 9  # deepest proxy is read-only
    assert isinstance(rec.payload["items"], tuple)  # list frozen to tuple
    with pytest.raises(TypeError):
        rec.payload["items"][0]["y"] = 9  # dict inside list is frozen too


def test_mutating_returned_record_nested_state_leaves_store_unchanged() -> None:
    # Critic should-fix 1 (w5-09 review), store-level proof: after put/get, no
    # in-place mutation path — at ANY nesting depth — can corrupt the stored
    # record, and the caller's original input dict is severed from storage.
    store = InMemoryConfirmationStore()
    source_payload = {"nested": {"count": 1}, "tags": ["a"]}
    rec = make_confirmation(payload=source_payload)
    store.put_confirmation(TENANT_A, rec.confirmation_key, rec)

    got = store.get(TENANT_A, rec.confirmation_key)
    with pytest.raises(TypeError):
        got.payload["nested"]["count"] = 999  # returned record: immutable deep
    with pytest.raises(AttributeError):
        got.payload["tags"].append("b")  # frozen to tuple: no append

    # Mutating the CALLER's original source dict also cannot reach storage
    # (construction deep-copied while freezing).
    source_payload["nested"]["count"] = 999
    source_payload["tags"].append("b")

    stored = store.get(TENANT_A, rec.confirmation_key)
    assert stored.payload["nested"]["count"] == 1
    assert stored.payload["tags"] == ("a",)


@pytest.mark.parametrize(
    ("exc_cls", "expected_code"),
    [
        (MeasurementError, "saena.measurement.error"),
        (TenantIsolationError, "saena.measurement.tenant_isolation_violation"),
        (NotFoundError, "saena.measurement.not_found"),
        (IdempotencyConflictError, "saena.measurement.idempotency_conflict"),
        (AppendOnlyViolationError, "saena.measurement.append_only_violation"),
        (EvidenceHashMismatchError, "saena.measurement.evidence_hash_mismatch"),
    ],
)
def test_error_taxonomy_and_to_dict(exc_cls: type[MeasurementError], expected_code: str) -> None:
    exc = exc_cls("boom", context={"tenant_id": "acme-co"})
    assert exc.error_code == expected_code
    assert exc.to_dict() == {
        "error_code": expected_code,
        "message": "boom",
        "tenant_id": "acme-co",
    }


def test_error_context_defaults_to_empty_dict() -> None:
    exc = NotFoundError("gone")
    assert exc.context == {}
    assert exc.to_dict() == {"error_code": "saena.measurement.not_found", "message": "gone"}
