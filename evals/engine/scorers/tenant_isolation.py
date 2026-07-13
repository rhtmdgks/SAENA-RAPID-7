"""Axis 4 — tenant isolation: "cross-tenant read denied", scored over REAL
`saena_domain.identity` code (ADR-0014 tenant propagation).

`reconcile_tenant(header_value, env_value)` is the synchronous-HTTP tenant
reconciliation primitive every service-layer request path is built on: the
caller-claimed tenant (`X-Saena-Tenant-Id` header) must match the serving
pod's own scoped tenant (`SAENA_TENANT_ID` env var) or the request is
refused with `TenantMismatchError` — "mismatch를 조용히 무시하거나 200으로 처리하는
코드 경로 금지" (ADR-0014 Constraints).
"""

from __future__ import annotations

from saena_domain.identity import TenantMismatchError, reconcile_tenant

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def score(fixture: Fixture) -> ScoreResult:
    header_value = fixture.input.get("header_tenant_id")
    env_value = fixture.input.get("pod_tenant_id")
    expect_denied = fixture.input["expect_denied"]

    try:
        reconciled = reconcile_tenant(header_value, env_value)
    except TenantMismatchError as exc:
        if expect_denied:
            return ScoreResult(passed=True, score=1.0, reasons=())
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"cross-tenant read was denied ({exc}) but this fixture expected the "
                "same-tenant read to be ALLOWED",
            ),
        )

    if expect_denied:
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"reconcile_tenant returned {reconciled!r} (ALLOWED) but this fixture "
                "is a cross-tenant read that MUST be denied",
            ),
        )
    if reconciled != fixture.input.get("expected_tenant_id", reconciled):
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                f"reconciled tenant_id {reconciled!r} did not match the fixture's "
                "expected_tenant_id",
            ),
        )
    return ScoreResult(passed=True, score=1.0, reasons=())


__all__ = ["score"]
