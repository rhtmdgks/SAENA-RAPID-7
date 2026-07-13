"""Factory helpers for `tests/unit/domain_qeeg`.

Deliberately NOT named `conftest.py` — see
`tests/unit/svc_observer_discovery/observer_discovery_factories.py`'s
module docstring for why a second `conftest.py` in a sibling test
directory causes an import collision when the full `tests/unit` suite is
collected together.
"""

from __future__ import annotations

from saena_domain.qeeg.models import ClaimFact, EvidenceFact, QeegLinkStatus

TENANT_A = "acme-co"
TENANT_B = "globex-co"

PROJECT_A = "project-0001"


def build_claim_fact(
    *,
    tenant_id: str = TENANT_A,
    project_id: str = PROJECT_A,
    claim_id: str = "claim-0001",
    entity_id: str = "entity-0001",
    status: str = "active",
    publishable: bool = True,
    blocking_reasons: tuple[str, ...] = (),
    supporting_evidence_ids: tuple[str, ...] = ("evidence-0001",),
) -> ClaimFact:
    return ClaimFact(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
        entity_id=entity_id,
        status=status,
        publishable=publishable,
        blocking_reasons=blocking_reasons,
        supporting_evidence_ids=supporting_evidence_ids,
    )


def build_evidence_fact(
    *,
    tenant_id: str = TENANT_A,
    project_id: str = PROJECT_A,
    evidence_id: str = "evidence-0001",
    claim_id: str = "claim-0001",
    link_status: QeegLinkStatus = QeegLinkStatus.LINKED,
) -> EvidenceFact:
    return EvidenceFact(
        tenant_id=tenant_id,
        project_id=project_id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        link_status=link_status,
    )
