"""AuditTrailStore — tenant-scoped, append-only, contract_hash-keyed buffer."""

from __future__ import annotations

from saena_domain.identity import TenantId
from saena_domain.policy import AuditReasonCode, AuditTrailRecord
from saena_plan_contract.audit_trail import AuditTrailStore

TENANT_A = TenantId("acme-corp")
TENANT_B = TenantId("globex-co")
CONTRACT_HASH = "sha256:" + "a" * 64


def _record(actor_id: str = "actor-proposer-0001") -> AuditTrailRecord:
    from saena_domain.policy import PlanState

    return AuditTrailRecord(
        contract_hash=CONTRACT_HASH,
        actor_id=actor_id,
        decided_at="2026-07-12T10:00:00Z",
        from_state=PlanState.PROPOSED,
        to_state=PlanState.WAITING_APPROVAL,
        reason_code=AuditReasonCode.SUBMITTED_FOR_APPROVAL,
    )


def test_append_and_list_for_plan() -> None:
    store = AuditTrailStore()
    store.append(TENANT_A, _record())
    records = store.list_for_plan(TENANT_A, CONTRACT_HASH)
    assert len(records) == 1
    assert records[0].reason_code == AuditReasonCode.SUBMITTED_FOR_APPROVAL


def test_list_for_plan_preserves_insertion_order() -> None:
    store = AuditTrailStore()
    store.append(TENANT_A, _record("actor-1"))
    store.append(TENANT_A, _record("actor-2"))
    records = store.list_for_plan(TENANT_A, CONTRACT_HASH)
    assert [r.actor_id for r in records] == ["actor-1", "actor-2"]


def test_tenant_isolation_separate_buffers() -> None:
    store = AuditTrailStore()
    store.append(TENANT_A, _record())
    assert store.list_for_plan(TENANT_B, CONTRACT_HASH) == ()


def test_unknown_plan_returns_empty_tuple() -> None:
    store = AuditTrailStore()
    assert store.list_for_plan(TENANT_A, "sha256:" + "f" * 64) == ()
