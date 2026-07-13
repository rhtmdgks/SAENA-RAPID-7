"""Test-only factory helpers for `tests/unit/svc_quality_eval` — mirrors
`tests/unit/svc_artifact_registry/registry_factories.py`'s role (a
uniquely-named module, never a second `conftest.py`; imported by
`conftest.py`'s own `sys.path` insertion).

Every builder returns a fully valid, contract-conformant default; every
builder accepts `**overrides`/explicit keyword args so a test can mutate
exactly the one field it needs to violate (e.g. `build_patch_artifact_manifest
(base_commit="f" * 40)` for the commit-coherence negative test).
"""

from __future__ import annotations

from typing import Any

from saena_quality_eval.engine import GateInputBundle, QualityEvalRequest
from saena_quality_eval.inputs import (
    AccessibilityOutcome,
    BoundaryOutcome,
    BuildOutcome,
    Claim,
    ContentFidelityOutcome,
    CoverageReport,
    CrawlabilityOutcome,
    DiffHunk,
    GeneratedCodeDriftOutcome,
    LinkRouteOutcome,
    LintOutcome,
    PatchDiff,
    PerformanceOutcome,
    SchemaContractOutcome,
    SecretScanOutcome,
    SecurityScanOutcome,
    StructuredDataOutcome,
    TestOutcome,
    TypecheckOutcome,
)

TENANT_A = "acme-co"
RUN_ID = "run-0001"
PATCH_UNIT_ID = "PU-01"
WORKTREE_COMMIT = "abc1234"
BASE_COMMIT = "a" * 40
CONTRACT_HASH = "sha256:" + "b" * 64
ARTIFACT_HASH = "sha256:" + "c" * 64
EVIDENCE_LEDGER_HASH = "sha256:" + "d" * 64
EVALUATED_AT = "2026-07-13T00:00:00Z"
APPROVED_SCOPE_GLOBS = ("apps/web/*",)
CHANGED_FILES = ("apps/web/page.tsx",)


def build_approved_change_plan(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": RUN_ID,
        "tenant_id": TENANT_A,
        "repo_commit": BASE_COMMIT,
        "approved_scope": list(APPROVED_SCOPE_GLOBS),
        "engine_scope": ["chatgpt-search"],
        "hypotheses": [
            {
                "id": "H-01",
                "query_cluster_ids": ["QC-01"],
                "evidence_ids": ["EV-01"],
                "predicted_layers": ["citation"],
                "expected_effect_distribution": {"p50": 0.1},
                "risk": "low",
            }
        ],
        "patch_units": [
            {
                "id": PATCH_UNIT_ID,
                "files": list(CHANGED_FILES),
                "allowed_transformations": ["edit"],
                "tests": ["apps/web/page.test.tsx"],
                "rollback": f"git-revert:{PATCH_UNIT_ID}",
            }
        ],
        "approval_required": True,
        "no_deploy": True,
        "no_push": True,
        "evidence_ledger_hash": EVIDENCE_LEDGER_HASH,
        "scope_limits": {"max_globs": 10},
        "diff_budget": {"max_files": 10, "max_lines": 500},
        "rejected_alternatives": [],
    }
    payload.update(overrides)
    return payload


def build_patch_artifact_manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "run_id": RUN_ID,
        "patch_unit_id": PATCH_UNIT_ID,
        "worktree_commit": WORKTREE_COMMIT,
        "base_commit": BASE_COMMIT,
        "artifact_uri": "artifact://diffs/PU-01",
        "artifact_hash": ARTIFACT_HASH,
        "manifest_uri": "artifact://manifests/PU-01",
        "changed_files": list(CHANGED_FILES),
        "quality_gate_ids": ["build", "tests"],
        "evidence_ids": ["EV-01"],
        "contract_hash": CONTRACT_HASH,
        "rollback_ref": f"git-revert:{PATCH_UNIT_ID}",
        "created_at": EVALUATED_AT,
    }
    payload.update(overrides)
    return payload


def build_gate_input_bundle(**overrides: Any) -> GateInputBundle:
    defaults: dict[str, Any] = dict(
        build=BuildOutcome(succeeded=True, command="make build", exit_code=0),
        unit_tests=TestOutcome(suite="unit", total=10, passed=10, failed=0),
        integration_tests=TestOutcome(suite="integration", total=5, passed=5, failed=0),
        lint=LintOutcome(tool="ruff", violation_count=0),
        typecheck=TypecheckOutcome(tool="mypy", error_count=0),
        schema_contract=SchemaContractOutcome(valid=True),
        security=SecurityScanOutcome(),
        boundary=BoundaryOutcome(
            changed_files=CHANGED_FILES, approved_scope_globs=APPROVED_SCOPE_GLOBS
        ),
        coverage=CoverageReport(changed_lines_total=100, changed_lines_covered=95),
        secret_scan=SecretScanOutcome(),
        generated_code_drift=GeneratedCodeDriftOutcome(),
        link_route=LinkRouteOutcome(),
        crawlability=CrawlabilityOutcome(),
        structured_data=StructuredDataOutcome(),
        content_fidelity=ContentFidelityOutcome(claims=(Claim("C-01", "EV-01"),)),
        accessibility=AccessibilityOutcome(),
        performance=PerformanceOutcome(
            metric_name="lcp",
            baseline_value=2.0,
            observed_value=2.05,
            regression_threshold_pct=10.0,
        ),
        diff=PatchDiff(
            changed_files=CHANGED_FILES,
            hunks=(
                DiffHunk(file_path=CHANGED_FILES[0], hunk_id="H1", patch_unit_id=PATCH_UNIT_ID),
            ),
        ),
    )
    defaults.update(overrides)
    return GateInputBundle(**defaults)


def build_quality_eval_request(
    *, gate_inputs: GateInputBundle | None = None, **overrides: Any
) -> QualityEvalRequest:
    defaults: dict[str, Any] = dict(
        tenant_id=TENANT_A,
        run_id=RUN_ID,
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit=WORKTREE_COMMIT,
        artifact_base_commit=BASE_COMMIT,
        approved_base_commit=BASE_COMMIT,
        approved_patch_unit_ids=frozenset({PATCH_UNIT_ID}),
        evaluated_at=EVALUATED_AT,
        gate_inputs=gate_inputs if gate_inputs is not None else build_gate_input_bundle(),
        report_uri="artifact://reports/PU-01",
    )
    defaults.update(overrides)
    return QualityEvalRequest(**defaults)


__all__ = [
    "APPROVED_SCOPE_GLOBS",
    "ARTIFACT_HASH",
    "BASE_COMMIT",
    "CHANGED_FILES",
    "CONTRACT_HASH",
    "EVALUATED_AT",
    "EVIDENCE_LEDGER_HASH",
    "PATCH_UNIT_ID",
    "RUN_ID",
    "TENANT_A",
    "WORKTREE_COMMIT",
    "build_approved_change_plan",
    "build_gate_input_bundle",
    "build_patch_artifact_manifest",
    "build_quality_eval_request",
]
