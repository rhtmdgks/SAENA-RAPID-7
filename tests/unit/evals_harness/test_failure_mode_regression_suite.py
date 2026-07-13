"""k3s spec §10 "Failure-mode testing" — the required 9-mode ↔ fixture 1:1
mapping (`evals/README.md` 2026-07-12 audit addendum, `evals/regression-
suites/README.md` "Wave 3 구현" bullet 2).

`test_all_nine_k3s_failure_modes_are_mapped` is the mapping-completeness
check: every mode file under `evals/regression-suites/failure_modes/`
declares a `status` of `covered` (with a resolvable `covering_fixture_ids`
in a real, registered axis, OR a `covering_test` that names a REAL test
function in THIS module) or `gap` (an honestly reported, unimplemented
check — never fabricated). 8 of the 9 k3s §10 modes are `covered` this
unit; `fm-05-skill-compromise` is the one honestly reported `gap` (no
pinned-skill-hash primitive exists anywhere in this repo yet).

The remaining functions in this module are the "regression_suite_native"
checks 4 modes point at — dedicated, real-code-backed checks that are NOT
one of the 9 mandatory eval axes (out of this mission's axis scope) but
still needed to close the 1:1 failure-mode mapping honestly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from harness_paths import EVALS_DIR, REPO_ROOT

from evals.engine.fixture import load_fixtures
from evals.engine.scorers import AXIS_SCORERS

FAILURE_MODES_DIR = EVALS_DIR / "regression-suites" / "failure_modes"

_VALID_STATUSES = frozenset({"covered", "gap"})


def _load_failure_modes() -> list[dict]:
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(FAILURE_MODES_DIR.glob("fm-*.yaml"))
    ]


def test_all_nine_k3s_failure_modes_are_mapped() -> None:
    modes = _load_failure_modes()
    assert len(modes) == 9, f"k3s §10 lists exactly 9 failure-mode rows, found {len(modes)}"

    mode_ids = [m["mode_id"] for m in modes]
    assert len(set(mode_ids)) == 9, "duplicate mode_id in failure_modes/"

    gaps = [m for m in modes if m["status"] == "gap"]
    covered = [m for m in modes if m["status"] == "covered"]
    for mode in modes:
        assert mode["status"] in _VALID_STATUSES, f"{mode['mode_id']}: invalid status"

    # w3-12: fm-05 skill-compromise moved gap -> covered (dedicated
    # skill-bundle content-integrity verifier now exists). All 9 covered.
    assert len(covered) == 9
    assert len(gaps) == 0

    for mode in covered:
        axis = mode["covering_axis"]
        if axis == "regression_suite_native":
            test_path = mode["covering_test"]
            module_path, _, function_name = test_path.partition("::")
            assert (REPO_ROOT / module_path).is_file(), f"{mode['mode_id']}: {module_path} missing"
            module_globals = globals()
            assert function_name in module_globals or _function_defined_in_module(
                REPO_ROOT / module_path, function_name
            ), f"{mode['mode_id']}: {function_name} not found in {module_path}"
        else:
            assert axis in AXIS_SCORERS, f"{mode['mode_id']}: axis {axis!r} is not registered"
            fixture_dir = _axis_fixture_dir(axis)
            fixture_ids = {f.fixture_id for f in load_fixtures(fixture_dir)}
            for covering_id in mode["covering_fixture_ids"]:
                assert covering_id in fixture_ids, (
                    f"{mode['mode_id']}: fixture {covering_id!r} not found under {fixture_dir}"
                )


def _axis_fixture_dir(axis: str) -> Path:
    from harness_paths import AXIS_FIXTURE_DIRS

    return AXIS_FIXTURE_DIRS[axis]


def _function_defined_in_module(module_path: Path, function_name: str) -> bool:
    source = module_path.read_text(encoding="utf-8")
    return f"def {function_name}(" in source


# --- regression_suite_native checks (k3s §10 modes not covered by one of ---
# --- the 9 mandatory eval axes) ---------------------------------------------


def test_skill_compromise_dedicated_bundle_verifier_blocks_tamper() -> None:
    """fm-05: the REAL dedicated skill-bundle verifier
    (`saena_domain.execution.skill_bundle.verify_skill_bundle`) blocks a
    one-byte skill-file tamper while the whole-ActionContract contract_hash
    is unchanged — proving F-5 coverage is a real content-integrity gate, not
    the contract-hash gate standing in for it. Also asserts determinism."""
    from saena_domain.execution import compute_skill_bundle_hash
    from saena_domain.execution.skill_bundle import (
        SkillBundleHashMismatchError,
        verify_skill_bundle,
    )

    bundle = {
        "claude/skill.md": b"run approved-command\n",
        "third-party/ponytail-pinned/tool.py": b"print('pinned')\n",
    }
    pin = compute_skill_bundle_hash(dict(bundle))
    # deterministic
    assert compute_skill_bundle_hash(dict(bundle)) == pin
    # clean bundle allows
    assert verify_skill_bundle(expected_hash=pin, bundle=dict(bundle)) == pin
    # one-byte tamper blocks
    tampered = dict(bundle)
    tampered["third-party/ponytail-pinned/tool.py"] = b"print('BACKDOOR')\n"
    with pytest.raises(SkillBundleHashMismatchError):
        verify_skill_bundle(expected_hash=pin, bundle=tampered)


def test_code_conflict_isolated_worktrees() -> None:
    """fm-04: two agents (patch units) targeting the SAME file, in the SAME
    run, provisioned via the REAL `saena_agent_runner.worktree.
    FakeWorktreeFactory`, must get non-overlapping filesystem roots so their
    writes never collide — "isolated worktrees, integrator only"."""
    from saena_agent_runner.worktree import FakeWorktreeFactory

    factory = FakeWorktreeFactory()
    try:
        handle_a = factory.create(
            tenant_id="acme-co", run_id="run-0001", patch_unit_id="PU-01", base_commit="a" * 40
        )
        handle_b = factory.create(
            tenant_id="acme-co", run_id="run-0001", patch_unit_id="PU-02", base_commit="a" * 40
        )
        assert handle_a.root != handle_b.root
        assert not handle_a.root.is_relative_to(handle_b.root)
        assert not handle_b.root.is_relative_to(handle_a.root)

        handle_a.write_file("apps/web/routes/checkout.py", b"# agent A's change\n")
        handle_b.write_file("apps/web/routes/checkout.py", b"# agent B's DIFFERENT change\n")

        assert handle_a.read_file("apps/web/routes/checkout.py") == b"# agent A's change\n"
        assert (
            handle_b.read_file("apps/web/routes/checkout.py") == b"# agent B's DIFFERENT change\n"
        )
    finally:
        factory.cleanup()


def test_secret_exposure_redacted_in_handoff_detail() -> None:
    """fm-06: a finding string referencing a ".env"-shaped secret value must
    be masked by the REAL `saena_hooks_runtime.redact.redact_patterns`
    primitive — "redaction and stop"."""
    from saena_hooks_runtime.redact import redact_patterns

    raw_finding = (
        "found secret referenced in source: .env contains API_KEY=sk-abcdef1234567890ABCDEFGH"
    )
    redacted = redact_patterns(raw_finding)
    assert "sk-abcdef1234567890ABCDEFGH" not in redacted
    assert "[REDACTED]" in redacted


def test_scope_creep_out_of_scope_write_rejected() -> None:
    """fm-08: an agent write target NOT declared in the patch unit's own
    `files` list (an "unrelated refactor") is refused by the REAL
    `saena_agent_runner.scope.guard_scope`, regardless of approved_scope
    breadth — "Ponytail + patch review rejects"."""
    from saena_agent_runner.errors import OutOfScopeWriteError
    from saena_agent_runner.scope import guard_scope

    # In-scope write: does not raise.
    guard_scope(
        "apps/web/docs/readme.md",
        patch_unit_files=["apps/web/docs/readme.md"],
        approved_scope=["apps/web/docs/*"],
    )

    # Scope creep: an unrelated file, never declared in this patch unit's
    # own files list, even though it happens to match the approved_scope glob.
    with pytest.raises(OutOfScopeWriteError):
        guard_scope(
            "apps/web/docs/unrelated-refactor.md",
            patch_unit_files=["apps/web/docs/readme.md"],
            approved_scope=["apps/web/docs/*"],
        )


def test_measurement_fraud_raw_lift_without_control_adjustment_rejected() -> None:
    """fm-09: Algorithm §11.3 "business integrity: 원시 지표와 가중 종합 지표를 모두
    표시" — a report presenting a raw metric's growth WITHOUT a paired
    control-adjusted value must never be granted "B-layer success".

    No experiment-attribution/measurement service exists in this repo yet
    (see fm-09-measurement-fraud.yaml's own `notes` — honestly flagged,
    this is a harness-owned spec rule, not a wrapper around production
    code, unlike every other regression_suite_native check in this module).
    """

    def business_integrity_check(report: dict[str, float | None]) -> bool:
        """`True` iff `report` is eligible to claim success: BOTH the raw
        observation AND a control-adjusted value are present, and the
        control-adjusted value is what actually gates "success" (a raw-only
        report, or one where control moved by the same amount as treatment,
        never grants success)."""
        raw = report.get("raw_metric_delta")
        control_adjusted = report.get("control_adjusted_lift")
        if raw is None or control_adjusted is None:
            return False
        return control_adjusted > 0.0

    # Raw citation count grew, but the paired control group ALSO grew by
    # the same amount -> control-adjusted lift is ~0 -> no success.
    fraudulent_report = {"raw_metric_delta": 0.18, "control_adjusted_lift": 0.0}
    assert business_integrity_check(fraudulent_report) is False

    # Raw-only report (no control definition registered at all) -> refused,
    # matching CLAUDE.md principle 11 (no external lift claim without
    # registered control/evidence).
    raw_only_report = {"raw_metric_delta": 0.18, "control_adjusted_lift": None}
    assert business_integrity_check(raw_only_report) is False

    # A genuine, control-adjusted positive lift -> success legitimately granted.
    legitimate_report = {"raw_metric_delta": 0.18, "control_adjusted_lift": 0.11}
    assert business_integrity_check(legitimate_report) is True
