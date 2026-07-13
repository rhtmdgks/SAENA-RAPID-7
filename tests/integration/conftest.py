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

from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent


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
