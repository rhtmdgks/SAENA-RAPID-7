"""Root pytest fixtures for `tests/integration/**` — w2-20 (Wave 2 exit).

Root-cause fix for the flaky gate (w2-20 task spec): `tests/integration/
orchestrator/test_execution_workflow.py::
test_duplicate_approve_signal_after_executing_is_a_no_op` (and other
`tests/integration/**` suites — real Temporal time-skipping test-server,
real `redpandadata/redpanda` / `postgres:16-alpine` testcontainers) flake
under full-suite load: multiple real external test-server/container
processes contending for CPU/scheduling when they all start inside one
`pytest` invocation alongside ~2000 deterministic unit/contract tests. The
tests are individually correct (pass 3/3 in isolation) — the flake is pure
process-contention noise from running real-external-process integration
suites in the same invocation as the deterministic gate, not a bug in the
tests or the code under test.

Fix: cleanly separate the two lanes.

  - This conftest's `pytest_collection_modifyitems` auto-marks EVERY test
    collected under `tests/integration/**` with `pytest.mark.integration`,
    regardless of whether that test's own subdirectory conftest/module
    already applies the marker (several — orchestrator, bus,
    persistence_postgres — already do so locally, since each patch unit's
    conftest was outside every OTHER unit's exclusive write path at the
    time it was written; approval_flow and gate_contract did not register
    it at all). This root conftest is collected for the whole
    `tests/integration` tree and makes the marker universal and
    unconditional — belt-and-suspenders with the existing per-directory
    `pytest_configure` marker *registrations* below (harmless to register
    the same marker string twice; pytest de-duplicates by name).
  - The root `pyproject.toml` `[tool.pytest.ini_options]` `markers` list
    registers `integration` globally (this patch unit, w2-20, is the
    Integrator/Lead for THIS unit and may edit root config — see task
    scope) so `-m integration` / `-m "not integration"` selection works
    from a single canonical registration, and the per-directory
    `pytest_configure` registrations become redundant-but-harmless
    (left in place: each is that subdirectory's own exclusive-write-path
    artifact from its patch unit, not worth churning here).
  - `justfile`'s blocking `test` recipe (run inside `verify`) now passes
    `-m "not integration"` — deterministic unit + contract lane only, no
    real external test-server/container processes, no contention, no
    flake. A new `test-integration` recipe runs `-m integration` alone
    (serial, real containers/test-servers) as a separate local/CI lane.
    Both lanes must run in CI (ADR-0018 lockstep: `just verify` and CI stay
    identical — the unit lane is the blocking required check, the
    integration lane runs as a separate serial job; see
    `docs/architecture/testing-strategy.md` "Two-lane test execution").
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent

# Import the E2E required-scenario completeness manifest/guard (test-support,
# same directory). Loaded here — at the tests/integration ANCESTOR — so the
# completeness guard fires for the composed-E2E lane no matter which subset of
# {measurement_e2e, measurement_workflow} paths a caller selects (a caller who
# drops one whole directory still triggers the ancestor conftest, so
# path-omission cannot dodge the guard).
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
import _gate_evidence  # noqa: E402
import _measurement_e2e_completeness as _e2e_complete  # noqa: E402

# Node-id -> outcome recorder for the E2E completeness guard. Populated by
# pytest_runtest_logreport below across the WHOLE session (both directories).
_E2E_PASSED: set[str] = set()
_E2E_SKIPPED: set[str] = set()
_E2E_FAILED: set[str] = set()
_E2E_XFAILED: set[str] = set()
_E2E_XPASSED: set[str] = set()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # `pytest_collection_modifyitems` is a session-global hook — pytest calls
    # EVERY conftest.py's implementation of it for the WHOLE collected item
    # list, not just items under this conftest's own directory (hook
    # collection is not directory-scoped the way fixtures are). Guard
    # explicitly by path so this only touches tests/integration/** and never
    # marks unit/contract tests collected elsewhere in the same session.
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except OSError:
            continue
        if _THIS_DIR in item_path.parents or item_path == _THIS_DIR:
            item.add_marker(pytest.mark.integration)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises a real external test-server/container "
        "process (Temporal time-skipping server, testcontainers postgres/"
        "redpanda, or other real-I/O wiring) under tests/integration/** — "
        "excluded from the blocking `just verify` unit lane (w2-20), run "
        "separately via `just test-integration`.",
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    # Record E2E node outcomes for the required-scenario completeness guard.
    # A fixture skip (Docker/ClickHouse/Temporal absent) surfaces at
    # when=="setup"; a pass/fail at when=="call". Only manifest nodes matter,
    # but record broadly and let the guard intersect with the manifest.
    if report.when == "setup" and report.outcome == "skipped":
        _E2E_SKIPPED.add(report.nodeid)
    elif report.when == "call":
        if report.outcome == "passed":
            if getattr(report, "wasxfail", None) is not None:
                _E2E_XPASSED.add(report.nodeid)  # xpassed — ran but not a clean pass
            else:
                _E2E_PASSED.add(report.nodeid)
        elif report.outcome == "failed":
            _E2E_FAILED.add(report.nodeid)
        elif report.outcome == "skipped":
            if getattr(report, "wasxfail", None) is not None:
                _E2E_XFAILED.add(report.nodeid)  # xfailed — NOT a real pass
            else:
                _E2E_SKIPPED.add(report.nodeid)


def _selected_e2e_node_ids(session: pytest.Session) -> set[str]:
    return {item.nodeid for item in session.items}


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # E2E REQUIRED-SCENARIO COMPLETENESS guard (Wave 5 Closure). Only acts when
    # the E2E required env is armed; otherwise silent (the umbrella
    # `just test-integration` lane and the unit lane never arm it). Compares the
    # authoritative manifest against what actually executed-and-PASSED, so a
    # partial `-k`/`-m`/`--deselect`/single-node/PYTEST_ADDOPTS selection —
    # which the pre-existing selected-set guards cannot see past — hard-fails
    # (exit 6) instead of going green on a fraction of the required scenarios.
    if not _e2e_complete.required_armed():
        return
    report = _e2e_complete.evaluate(_E2E_PASSED, _E2E_SKIPPED, _E2E_FAILED)

    # Emit machine-readable runtime EVIDENCE (Wave 5 evidence-integrity closure)
    # — ALWAYS, on pass OR fail, so the CI renderer sees the true state instead
    # of a static claim. xfailed/xpassed are counted separately and are NOT
    # treated as clean passes (an xfailed required node counts as missing).
    payload = _e2e_complete.build_evidence_payload(
        _E2E_PASSED,
        _E2E_SKIPPED,
        _E2E_FAILED,
        selected_ids=_selected_e2e_node_ids(session),
        xfailed=len(_E2E_XFAILED),
        xpassed=len(_E2E_XPASSED),
        witnesses=_gate_evidence.witnesses(),
        intended_exit_code=_e2e_complete.HARD_FAIL_EXIT,
    )
    _gate_evidence.write_evidence(payload)

    if report.ok:
        return
    # Set the hard-fail exit code FIRST — must hold even if the terminal
    # reporter is unavailable (e.g. `-p no:terminalreporter`).
    session.exitstatus = _e2e_complete.HARD_FAIL_EXIT
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    reporter.write_line(_e2e_complete.format_failure(report), red=True)
