"""`_PlanFacts` — module-private, per-app bookkeeping (`app.py`).

Accessed directly (not merely through the HTTP surface) because
`facts.get()` raising `PlanNotFoundError` for a `contract_hash` that was
never `put` (e.g. a plan seeded directly into `PlanRepository` bypassing
`propose_plan`, rather than proposed through this service's own endpoint) is
a real, reachable branch that a black-box HTTP test cannot construct without
its own repo-seeding workaround — unit-testing the class directly is the
more direct proof.
"""

from __future__ import annotations

import pytest
from saena_domain.identity import TenantId
from saena_plan_contract.app import _PlanFacts
from saena_plan_contract.errors import PlanNotFoundError

TENANT = TenantId("acme-corp")
CONTRACT_HASH = "sha256:" + "a" * 64


def test_put_then_get_round_trips() -> None:
    facts = _PlanFacts()
    facts.put(
        TENANT,
        CONTRACT_HASH,
        proposer_actor_id="actor-proposer-0001",
        high_risk=True,
        patch_unit_ids=("PU-01", "PU-02"),
        run_id="run-0001",
    )
    result = facts.get(TENANT, CONTRACT_HASH)
    assert result["proposer_actor_id"] == "actor-proposer-0001"
    assert result["high_risk"] is True
    assert result["patch_unit_ids"] == ("PU-01", "PU-02")
    assert result["run_id"] == "run-0001"


def test_get_unknown_contract_hash_raises_not_found() -> None:
    facts = _PlanFacts()
    with pytest.raises(PlanNotFoundError):
        facts.get(TENANT, CONTRACT_HASH)
