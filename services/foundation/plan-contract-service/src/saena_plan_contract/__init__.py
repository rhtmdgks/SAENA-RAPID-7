"""saena_plan_contract — ChangePlan/ApprovalDecision lifecycle (w2-11).

ADR-0003 approval transition authority path: B signed approval -> Policy
Gate pre-verification (this service's `PolicyGateClient` port) -> only on
gate approval does `saena_domain.policy.transition()` run -> on APPROVED,
per-patch-unit leases are issued and `plan.contract.approved.v1` is recorded
to the transactional outbox as a notification-only event (never the
transition trigger itself, ADR-0003).

Public API:
    create_app            — FastAPI app factory (`app.py`)
    AuditTrailStore        — in-process audit descriptor buffer (`audit_trail.py`)
    compute_contract_hash  — ChangePlan content hash (`contract_hash.py`, OPEN
                              ITEM: interim canonicalization pending the JCS ADR)
    PolicyGateClient, GateDecision, GateCheckRequest, DecisionGateCheckRequest,
    HttpPolicyGateClient, FakeGateClient — local Policy Gate client port
                              (`gate_client.py`)
"""

from __future__ import annotations

from saena_plan_contract.app import create_app
from saena_plan_contract.audit_trail import AuditTrailStore
from saena_plan_contract.contract_hash import compute_contract_hash
from saena_plan_contract.gate_client import (
    DecisionGateCheckRequest,
    FakeGateClient,
    GateCheckRequest,
    GateDecision,
    HttpPolicyGateClient,
    PolicyGateClient,
)

__all__ = [
    "AuditTrailStore",
    "DecisionGateCheckRequest",
    "FakeGateClient",
    "GateCheckRequest",
    "GateDecision",
    "HttpPolicyGateClient",
    "PolicyGateClient",
    "compute_contract_hash",
    "create_app",
]

__version__ = "0.1.0"
