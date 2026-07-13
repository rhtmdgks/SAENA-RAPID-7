"""Factory helpers for `saena_agent_runner` unit tests.

Deliberately NOT named `conftest.py` — see
`tests/unit/svc_artifact_registry/registry_factories.py`'s own docstring for
why (import collision across sibling test directories when the full
`tests/unit` suite is collected together).
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobContext

TENANT_A = "acme-co"
TENANT_B = "globex-co"

RUN_ID = "run-0001"
PATCH_UNIT_ID = "PU-01"
BASE_COMMIT = "a" * 40
CONTRACT_HASH = "sha256:" + "b" * 64
EVIDENCE_LEDGER_HASH = "sha256:" + "c" * 64


def build_job_context(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_ID,
    actor_id: str = "actor-runner",
) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-0001",
        project_id="proj-0001",
        run_id=run_id,
        trace_id="a" * 32,
        idempotency_key=f"{tenant_id}:{run_id}:{PATCH_UNIT_ID}",
        actor_id=actor_id,
    )


def build_patch_unit(
    *,
    patch_unit_id: str = PATCH_UNIT_ID,
    files: tuple[str, ...] = ("apps/web/docs/readme.md",),
    allowed_transformations: tuple[str, ...] = ("git add", "git commit", "pytest -q"),
    tests: tuple[str, ...] = ("test-01",),
    rollback: str = f"git-revert:{PATCH_UNIT_ID}",
) -> dict[str, Any]:
    return {
        "id": patch_unit_id,
        "files": list(files),
        "allowed_transformations": list(allowed_transformations),
        "tests": list(tests),
        "rollback": rollback,
    }


def build_change_plan(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_ID,
    repo_commit: str = BASE_COMMIT,
    approved_scope: tuple[str, ...] = ("apps/web/docs/*",),
    patch_units: list[dict[str, Any]] | None = None,
    max_files: int = 10,
    max_lines: int = 1000,
    max_globs: int = 5,
    evidence_ids: tuple[str, ...] = ("EV-01",),
) -> dict[str, Any]:
    if patch_units is None:
        patch_units = [build_patch_unit()]
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "repo_commit": repo_commit,
        "approved_scope": list(approved_scope),
        "engine_scope": ["chatgpt-search"],
        "hypotheses": [
            {
                "id": "H-01",
                "query_cluster_ids": ["QC-01"],
                "evidence_ids": list(evidence_ids),
                "predicted_layers": ["citation"],
                "expected_effect_distribution": {"p_7d": 0.3},
                "risk": "low",
            }
        ],
        "patch_units": patch_units,
        "approval_required": True,
        "no_deploy": True,
        "no_push": True,
        "evidence_ledger_hash": EVIDENCE_LEDGER_HASH,
        "scope_limits": {"max_globs": max_globs},
        "diff_budget": {"max_files": max_files, "max_lines": max_lines},
        "rejected_alternatives": [],
    }


def build_approval_decision(
    *,
    contract_hash: str = CONTRACT_HASH,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_ID,
    approver_actor_id: str = "actor-approver",
    decision: str = "approved",
    patch_unit_decisions: list[dict[str, str]] | None = None,
    signature: str = "opaque-signature-bytes",
    signature_algorithm: str = "ed25519",
    decided_at: str = "2026-07-13T00:00:00Z",
) -> dict[str, Any]:
    if patch_unit_decisions is None:
        patch_unit_decisions = [{"patch_unit_id": PATCH_UNIT_ID, "decision": "approved"}]
    return {
        "contract_hash": contract_hash,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "approver_actor_id": approver_actor_id,
        "decision": decision,
        "patch_unit_decisions": patch_unit_decisions,
        "signature": signature,
        "signature_algorithm": signature_algorithm,
        "decided_at": decided_at,
    }
