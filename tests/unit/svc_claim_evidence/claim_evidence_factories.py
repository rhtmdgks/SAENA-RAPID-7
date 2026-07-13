"""Factory helpers for `tests/unit/svc_claim_evidence`.

Deliberately NOT named `conftest.py` — see
`tests/unit/svc_observer_discovery/observer_discovery_factories.py`'s
module docstring for why a second `conftest.py` in a sibling test
directory causes an import collision when the full `tests/unit` suite is
collected together. Imported by its own unique dotted name
(`claim_evidence_factories`), inserted onto `sys.path` by this directory's
`conftest.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim
from saena_schemas.domain.extracted_claim_v1 import Status as ClaimStatus

TENANT_A = "acme-co"
TENANT_B = "globex-co"

PROJECT_A = "project-0001"

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_claim(
    *,
    tenant_id: str = TENANT_A,
    project_id: str = PROJECT_A,
    claim_id: str = "claim-0001",
    entity_id: str = "entity-0001",
    claim_text: str = "The product supports SSO via SAML 2.0.",
    status: ClaimStatus = ClaimStatus.active,
    effective_from: datetime = NOW,
    created_at: datetime = NOW,
) -> ExtractedClaim:
    return ExtractedClaim(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=project_id,  # type: ignore[arg-type]
        claim_id=claim_id,
        entity_id=entity_id,
        claim_text=claim_text,
        status=status,
        effective_from=_iso(effective_from),  # type: ignore[arg-type]
        created_at=_iso(created_at),  # type: ignore[arg-type]
    )


def build_evidence(
    *,
    tenant_id: str = TENANT_A,
    project_id: str = PROJECT_A,
    evidence_id: str = "evidence-0001",
    claim_id: str = "claim-0001",
    source_uri: str = "https://docs.example.com/security/sso",
    excerpt: str = "SAML 2.0 SSO is supported on the Enterprise plan.",
    freshness_checked_at: datetime = NOW,
    content_hash: str = "sha256:" + "a" * 64,
) -> EvidenceRecord:
    return EvidenceRecord(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=project_id,  # type: ignore[arg-type]
        evidence_id=evidence_id,
        claim_id=claim_id,
        source_uri=source_uri,  # type: ignore[arg-type]
        excerpt=excerpt,
        freshness_checked_at=_iso(freshness_checked_at),  # type: ignore[arg-type]
        content_hash=content_hash,  # type: ignore[arg-type]
    )


def stale_timestamp(*, older_than: timedelta) -> datetime:
    return NOW - older_than
