"""E2E: dirty-tree write-blocking (with dirty-work preservation) and the
interrupt → resume-by-run-id lifecycle, including stale-world refusal.

Scenario keys: ``dirty_blocks_implement``, ``interrupt_resume``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _e2e_run import event_names, op, start
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, argv, cwd, env) -> int:  # type: ignore[no-untyped-def]
        self.calls.append((tuple(argv), str(cwd)))
        return 0


# --------------------------------------------------------------------------- #
# dirty-blocks-implement
# --------------------------------------------------------------------------- #
def test_dirty_blocks_implement__implement_blocked_on_dirty(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer, _dirty = build.build_dirty_repo(customers)
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=_Recorder())
    # A dirty customer tree BLOCKS a write mode, fail-closed.
    assert res.exit_code == EXIT_VALIDATION_FAILED
    assert "implement" in res.err and ("dirty" in res.err.lower() or "blocks" in res.err.lower())
    # No worktree was created for the refused write.
    assert not (customer.parent / f"{customer.name}.saena-worktrees").exists()


def test_dirty_blocks_implement__preflight_only_warns(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer, _dirty = build.build_dirty_repo(customers)
    res = start("preflight", customer)
    assert res.exit_code == EXIT_OK
    findings = res.json["report"]["boundary"]["findings"]
    codes = {(f["code"], f["severity"]) for f in findings}
    assert ("dirty_tree", "WARN") in codes


def test_dirty_blocks_implement__audit_only_warns(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer, _dirty = build.build_dirty_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    findings = res.json["report"]["boundary"]["findings"]
    assert any(f["code"] == "dirty_tree" and f["severity"] == "WARN" for f in findings)


def test_dirty_blocks_implement__dirty_work_preserved_after_run(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer, dirty = build.build_dirty_repo(customers)
    porcelain_before = build.porcelain(customer)
    dirty_before = dirty.read_text(encoding="utf-8")

    # A read run and a REFUSED write run must both leave the WIP untouched.
    assert start("audit", customer, "--dry-run").exit_code == EXIT_OK
    start("implement", customer, "--intake", str(complete_intake), launch_runner=_Recorder())

    assert build.porcelain(customer) == porcelain_before
    assert dirty.read_text(encoding="utf-8") == dirty_before
    assert (customer / "WIP-NOTES.txt").exists()  # untracked WIP still present


# --------------------------------------------------------------------------- #
# interrupt-resume
# --------------------------------------------------------------------------- #
def _started_run(build, customers) -> tuple[Path, str]:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    return customer, res.json["run_id"]


def test_interrupt_resume__resume_by_run_id_reflects_state(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    _customer, run_id = _started_run(build, customers)
    # "Interrupt" = simply stop; then resume purely by run id.
    res = op("resume", run_id)
    assert res.exit_code == EXIT_OK
    assert res.json["resumable"] is True
    assert res.json["last_mode"] == "audit"


def test_interrupt_resume__status_and_verify_after_interrupt(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    _customer, run_id = _started_run(build, customers)
    status = op("status", run_id)
    assert status.exit_code == EXIT_OK
    assert status.json["mode_history"][0]["mode"] == "audit"
    assert status.json["evidence_status"] == "VERIFIED"
    assert op("verify", run_id).exit_code == EXIT_OK


def test_interrupt_resume__resume_refused_after_customer_moves(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer, run_id = _started_run(build, customers)
    build.commit_change(customer)  # customer HEAD advances after the run
    res = op("resume", run_id)
    assert res.exit_code == EXIT_VALIDATION_FAILED
    assert "refusing to resume" in res.err and "customer HEAD" in res.err


def test_interrupt_resume__resume_refused_after_rapid7_change(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    _customer, run_id = _started_run(build, customers)
    # Simulate the RAPID-7 root advancing by rewriting the recorded binding SHA
    # (rewriting the real repo HEAD is neither possible nor desirable here).
    run_json = pilot_home / "pilot-runs" / run_id / "run.json"
    data = json.loads(run_json.read_text(encoding="utf-8"))
    data["rapid7_sha"] = "0" * 40
    run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    res = op("resume", run_id)
    assert res.exit_code == EXIT_VALIDATION_FAILED
    assert "refusing to resume" in res.err and "RAPID-7 HEAD" in res.err


def test_interrupt_resume__resume_appends_valid_evidence(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    _customer, run_id = _started_run(build, customers)
    assert op("resume", run_id).exit_code == EXIT_OK
    # Resume appended a chain-valid record and the chain still verifies.
    assert "resume-validated" in event_names(pilot_home, run_id)
    assert op("verify", run_id).exit_code == EXIT_OK
