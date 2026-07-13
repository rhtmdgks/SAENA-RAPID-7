"""`PlanApprovalHarness` + shared constants for `tests/e2e/execution`.

Deliberately NOT named `conftest.py` (a SECOND `conftest.py` under this
directory would still be fine for pytest's own fixture discovery, but this
class needs to be `import`-able BY NAME from the sibling test module too —
`tests/integration/persistence_postgres/conftest.py`'s own docstring
documents exactly why a plain `from conftest import ...` breaks once
multiple directories' `conftest.py` modules are all collected under
pytest's default `prepend` import mode: every `conftest.py` in the
collected tree shares the same bare top-level module name `conftest`, and
`from conftest import X` resolves to WHICHEVER one Python's import cache
already holds — often a different directory's entirely (confirmed
empirically here: adding `tests/e2e/execution/__init__.py` made this
directory's own test module resolve `conftest` to `tests/unit/
svc_repository_intake/conftest.py` instead, since that directory is also on
`sys.path` per this package's own `conftest.py`). A uniquely-named module
sidesteps the collision entirely, same precedent as `approval_harness.py`/
`intake_factories.py`/`postgres_factories.py` etc.
"""

from __future__ import annotations

from approval_harness import AuditChainRelay, PlanContractHttpGateAdapter
from fastapi.testclient import TestClient
from saena_audit_ledger import create_app as create_audit_ledger_app
from saena_domain.persistence import (
    InMemoryAuditLedger,
    InMemoryOutbox,
    InMemoryPlanRepository,
)
from saena_domain.persistence.memory import InMemoryDecisionRecordStore
from saena_plan_contract import create_app as create_plan_contract_app
from saena_plan_contract.audit_trail import AuditTrailStore
from saena_policy_gate.app import create_app as create_policy_gate_app
from saena_policy_gate.app import get_decision_store, get_engine
from saena_policy_gate.engine import PolicyEngine
from saena_policy_gate.rules import default_engine_rules

TENANT_1 = "e2e-tenant-one"
TENANT_2 = "e2e-tenant-two"
RUN_ID = "run-e2e-0001"
PATCH_UNIT_ID = "PU-01"
PROPOSER = "actor-proposer-e2e"
APPROVER_1 = "actor-approver-e2e-1"


class PlanApprovalHarness:
    """Just the plan-contract-service / policy-gate-service /
    audit-ledger-service trio (reused from `approval_harness.build_harness`,
    minus forge-console-api — this E2E's 14-step mission never names
    forge-console-api, unlike `tests/e2e/approval`)."""

    def __init__(self, *, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.plans = InMemoryPlanRepository()
        self.outbox = InMemoryOutbox()
        self.plan_audit_trail = AuditTrailStore()
        self.ledger = InMemoryAuditLedger()

        engine = PolicyEngine(default_engine_rules())
        policy_gate_app = create_policy_gate_app()
        decision_store = InMemoryDecisionRecordStore()
        policy_gate_app.dependency_overrides[get_decision_store] = lambda: decision_store
        policy_gate_app.dependency_overrides[get_engine] = lambda: engine
        self.policy_gate_client = TestClient(policy_gate_app)
        self.gate_adapter = PlanContractHttpGateAdapter(self.policy_gate_client)

        self.plan_contract_app = create_plan_contract_app(
            plans=self.plans,
            outbox=self.outbox,
            gate=self.gate_adapter,
            audit_trail=self.plan_audit_trail,
            tenant_env_value=tenant_id,
        )
        self.plan_contract_client = TestClient(self.plan_contract_app)

        self.audit_ledger_app = create_audit_ledger_app(self.ledger)
        self.audit_ledger_client = TestClient(self.audit_ledger_app)
        self.audit_relay = AuditChainRelay(audit_client=self.audit_ledger_client)

    def close(self) -> None:
        self.policy_gate_client.close()
        self.plan_contract_client.close()
        self.audit_ledger_client.close()


__all__ = [
    "APPROVER_1",
    "PATCH_UNIT_ID",
    "PROPOSER",
    "RUN_ID",
    "TENANT_1",
    "TENANT_2",
    "PlanApprovalHarness",
]
