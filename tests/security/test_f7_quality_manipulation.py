"""F-7 Quality manipulation (k3s spec §10 row 7, failure-mode matrix `F-7`).

Fixture: an agent deletes a failing test so the build/test suite "passes".
k3s: "test deleted to pass build → diff-to-contract/critic rejects".

Wired against TWO real layers:

1. `saena_agent_runner.commands.guard_command` — a patch unit's own
   `allowed_transformations` never includes an unreviewed `rm`/delete
   command; deleting a test file via `Bash` is refused by the DEFAULT-DENY
   command allowlist before it can ever run (`CommandNotAllowlistedError`).
2. `saena_quality_eval.gates.gate_diff_rationality` — "diff-to-contract"
   literally: Algorithm §11.1 "every hunk → Action Contract patch unit
   연결". A diff hunk that deletes `tests/test_checkout.py` but carries NO
   `patch_unit_id` (or one the approved `ChangePlan` never named) is
   rejected — an agent cannot silently fold a test deletion into an
   unrelated/unlinked hunk and have the Release Gate wave it through.

`before_handoff.require_independent_critic` (hooks-runtime) is the third,
"critic rejects" layer — modeled directly: a self-review (not independent)
or a missing critic review both block handoff regardless of how green the
(possibly manipulated) quality matrix looks.
"""

from __future__ import annotations

import pytest
from factories import build_gate_input_bundle, build_quality_eval_request
from hooks_runtime_factories import RUN_ID, TENANT_ID, TRACE_ID, TS, make_budget
from runner_factories import build_change_plan
from saena_agent_runner.commands import guard_command
from saena_agent_runner.contract import get_patch_unit, parse_change_plan
from saena_agent_runner.errors import CommandNotAllowlistedError
from saena_hooks_runtime.hooks.before_handoff import (
    BeforeHandoffInput,
    CriticReview,
    QualityMatrixResult,
    RollbackManifest,
    before_handoff,
)
from saena_hooks_runtime.models import Decision, ReasonCode
from saena_quality_eval.engine import run_quality_evaluation
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import gate_diff_rationality
from saena_quality_eval.inputs import DiffHunk, PatchDiff

DELETED_TEST_PATH = "tests/unit/checkout/test_checkout.py"


def test_agent_runner_denies_unreviewed_test_deletion_command() -> None:
    contract = parse_change_plan(
        build_change_plan(
            patch_units=[
                {
                    "id": "PU-01",
                    "files": ["apps/web/routes/checkout.tsx"],
                    # No delete/rm command was ever reviewed/approved for
                    # this unit — only an edit transformation.
                    "allowed_transformations": ["git commit"],
                    "tests": [DELETED_TEST_PATH],
                    "rollback": "git-revert:PU-01",
                }
            ]
        )
    )
    patch_unit = get_patch_unit(contract, "PU-01")

    with pytest.raises(CommandNotAllowlistedError):
        guard_command(
            ("rm", DELETED_TEST_PATH), allowed_transformations=patch_unit.allowed_transformations
        )


def test_diff_rationality_gate_rejects_an_unlinked_test_deletion_hunk() -> None:
    """A hunk deleting the test file with NO `patch_unit_id` at all — the
    most direct "quietly delete a test" shape — fails `diff_rationality`."""
    outcome = gate_diff_rationality(
        PatchDiff(
            changed_files=(DELETED_TEST_PATH,),
            hunks=(DiffHunk(file_path=DELETED_TEST_PATH, hunk_id="H-del-1", patch_unit_id=None),),
        ),
        approved_patch_unit_ids=frozenset({"PU-01"}),
    )
    assert outcome.gate_id == GateId.DIFF_RATIONALITY
    assert outcome.passed is False
    assert outcome.failures[0].error_code == "saena.validation.unlinked_diff_hunk"


def test_diff_rationality_gate_rejects_a_test_deletion_linked_to_an_unapproved_unit() -> None:
    """A slightly more devious shape: the hunk NAMES a `patch_unit_id`, but
    one the approved `ChangePlan` never authorized — still rejected, an
    agent cannot forge linkage to a patch unit that was never approved."""
    outcome = gate_diff_rationality(
        PatchDiff(
            changed_files=(DELETED_TEST_PATH,),
            hunks=(
                DiffHunk(file_path=DELETED_TEST_PATH, hunk_id="H-del-2", patch_unit_id="PU-FORGED"),
            ),
        ),
        approved_patch_unit_ids=frozenset({"PU-01"}),
    )
    assert outcome.passed is False


def test_release_gate_forbids_promotion_when_test_suite_shrinks_via_unlinked_deletion() -> None:
    gate_inputs = build_gate_input_bundle(
        diff=PatchDiff(
            changed_files=("apps/web/page.tsx", DELETED_TEST_PATH),
            hunks=(
                DiffHunk(file_path="apps/web/page.tsx", hunk_id="H1", patch_unit_id="PU-01"),
                DiffHunk(file_path=DELETED_TEST_PATH, hunk_id="H2", patch_unit_id=None),
            ),
        )
    )
    request = build_quality_eval_request(
        gate_inputs=gate_inputs, approved_patch_unit_ids=frozenset({"PU-01"})
    )

    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    diff_rationality_result = outcome.gate_result_for(GateId.DIFF_RATIONALITY)
    assert diff_rationality_result["status"] == "failed"


def test_before_handoff_rejects_a_self_reviewed_quality_manipulation_attempt() -> None:
    """Critic layer: even if the (manipulated) quality matrix reports every
    gate green, a NON-independent (self) critic review still blocks
    handoff — "critic rejects" is structural, not a rubber stamp."""
    result = before_handoff(
        BeforeHandoffInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            quality_matrix=QualityMatrixResult(
                gates={"build": "PASS", "tests": "PASS", "lint": "PASS", "security": "PASS"}
            ),
            critic_review=CriticReview(
                reviewer_id="the-same-agent", independent=False, verdict="approve"
            ),
            rollback_manifest=RollbackManifest(
                patch_unit_id="PU-01", command="git revert <sha>", verified=True
            ),
            patch_commands=(),
            budget=make_budget("before_handoff"),
        )
    )
    assert result.decision == Decision.FAIL
    assert result.blocked is True
    assert result.reason_code == ReasonCode.MISSING_CRITIC_REVIEW
    assert any("not independent" in item for item in result.remediation)
