"""The 9 eval axes (w3-10 mission) — `AXIS_SCORERS` is the single registry
every generic harness test (`tests/unit/evals_harness/test_all_axes.py`)
iterates: `axis name -> pure score(fixture) -> ScoreResult` function.

Axis -> primitive under evaluation:
  1. patch_correctness     -> saena_quality_eval (GateResult/GateId/verification)
  2. contract_compliance   -> packages/contracts/json-schema/** (jsonschema)
  3. approval_enforcement  -> saena_agent_runner.approval (ADR-0003)
  4. tenant_isolation      -> saena_domain.identity.http.reconcile_tenant (ADR-0014)
  5. failure_recovery      -> saena_domain.execution (JobError.retryable, JobStatus)
  6. reproducibility       -> saena_quality_eval.verification + saena_domain.audit.canonical
  7. evidence_integrity    -> evals.engine.evidence_registry (CLAUDE.md principle 11)
  8. forbidden_action      -> saena_hooks_runtime.rules.deploy_push + saena_schemas EngineId
  9. handoff_completeness  -> saena_hooks_runtime.hooks.before_handoff + saena_domain.audit chain
"""

from __future__ import annotations

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult
from evals.engine.runner import Scorer
from evals.engine.scorers.approval_enforcement import score as score_approval_enforcement
from evals.engine.scorers.contract_compliance import score as score_contract_compliance
from evals.engine.scorers.evidence_integrity import score as score_evidence_integrity
from evals.engine.scorers.failure_recovery import score as score_failure_recovery
from evals.engine.scorers.forbidden_action import score as score_forbidden_action
from evals.engine.scorers.handoff_completeness import score as score_handoff_completeness
from evals.engine.scorers.patch_correctness import score as score_patch_correctness
from evals.engine.scorers.reproducibility import score as score_reproducibility
from evals.engine.scorers.tenant_isolation import score as score_tenant_isolation

AXIS_SCORERS: dict[str, Scorer] = {
    "patch_correctness": score_patch_correctness,
    "contract_compliance": score_contract_compliance,
    "approval_enforcement": score_approval_enforcement,
    "tenant_isolation": score_tenant_isolation,
    "failure_recovery": score_failure_recovery,
    "reproducibility": score_reproducibility,
    "evidence_integrity": score_evidence_integrity,
    "forbidden_action": score_forbidden_action,
    "handoff_completeness": score_handoff_completeness,
}

#: The 9 mandatory axes (mission minimum) — every entry in `AXIS_SCORERS`
#: must be a member, checked by `tests/unit/evals_harness/test_all_axes.py`.
MANDATORY_AXES: frozenset[str] = frozenset(
    {
        "patch_correctness",
        "contract_compliance",
        "approval_enforcement",
        "tenant_isolation",
        "failure_recovery",
        "reproducibility",
        "evidence_integrity",
        "forbidden_action",
        "handoff_completeness",
    }
)

assert set(AXIS_SCORERS) == MANDATORY_AXES, (  # noqa: S101 - module-load invariant
    "AXIS_SCORERS drifted from the mission's 9 mandatory axes"
)

__all__ = ["AXIS_SCORERS", "MANDATORY_AXES", "Fixture", "ScoreResult"]
