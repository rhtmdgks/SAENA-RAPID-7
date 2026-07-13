"""pytest fixtures for `tests/integration/measurement_failure` (w5-20).

Mirrors `tests/integration/measurement_pg/conftest.py` (w5-10) + `tests/
integration/failure_modes/conftest.py` (w3-09) EXACTLY: one
`postgres:16-alpine` testcontainer started ONCE per session; per-test
isolation via TRUNCATE; a FRESH `AsyncEngine` per test (event-loop-per-test
discipline — no pytest-asyncio plugin is installed, every test drives its
own `asyncio.run(scenario())`); and an HONEST Docker skip (probe the daemon
socket directly, never start-and-swallow). Deliberately DUPLICATED rather
than imported — those sibling directories are outside this patch unit's
exclusive write paths, and a bare `from conftest import ...` collides once
the whole suite is collected together (see either sibling's own docstring
for the full rationale, reused verbatim here).

`services/experimentation/experiment-attribution-service` is NOT (yet) a
`uv` workspace member — this conftest inserts its `src/` onto `sys.path`
directly (same workaround `measurement_pg/conftest.py` and
`svc_experiment_attribution_pipeline/conftest.py` use), PLUS the pipeline's
own `tests/unit/svc_experiment_attribution_pipeline` factory directory, so
this suite reuses the SAME `pipeline_factories` fixture graph the pipeline's
own unit tests are built on (mirrors wave5-plan.md's "reuse, not
reinvention" convention — this patch unit invents no new registration/
submission/policy fixture shape, only wires the REAL Postgres ports in place
of the in-memory reference).
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_SERVICE_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)
_PIPELINE_FACTORIES_DIR = _REPO_ROOT / "tests" / "unit" / "svc_experiment_attribution_pipeline"

for _p in (_THIS_DIR, _SERVICE_SRC, _PIPELINE_FACTORIES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from saena_experiment_attribution.persistence import adapter  # noqa: E402


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (mirrors every sibling suite's probe, duplicated rather than
    imported)."""
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        host_port = docker_host.removeprefix("tcp://")
        host, _, port_str = host_port.partition(":")
        port = int(port_str) if port_str else 2375
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            return False
    for candidate in (
        "/var/run/docker.sock",
        os.path.expanduser("~/.docker/run/docker.sock"),
        os.path.expanduser("~/.colima/default/docker.sock"),
    ):
        if os.path.exists(candidate):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(candidate)
                return True
            except OSError:
                continue
    return False


_DOCKER_AVAILABLE = _docker_available()


#: The container-free guard self-test module — it spawns pytest subprocesses
#: and asserts exit codes, needs NO Docker, and must run on every host to prove
#: the required-lane guard. EXEMPT from the Docker-absent skip below and from
#: the sessionfinish container accounting.
_CONTAINER_FREE_GUARD_MODULE = "test_failure_required_guard.py"


def _is_guard_selftest(item: pytest.Item) -> bool:
    return Path(str(item.fspath)).name == _CONTAINER_FREE_GUARD_MODULE


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _DOCKER_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(reason="Docker daemon not reachable — honest skip (ADR-0017)")
    for item in items:
        if "integration" in item.keywords and not _is_guard_selftest(item):
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017)"
    )


# --------------------------------------------------------------------------- #
# Required-mode fail-closed guard (MUST-FIX B). The honest Docker-absent skip
# above must NOT let this required failure-mode lane pass without running the
# real-Postgres failure/replay/rollback/conflict rows. When
# `SAENA_MEASUREMENT_FAILURE_REQUIRED=1` (set only by the
# `just measurement-failure-modes` named gate + its CI job), ANY skipped
# integration test in this directory — or ZERO passed — is a HARD FAILURE
# (non-zero, non-5 exit). Optional/local invocation (flag unset) keeps the
# honest skip. Same mechanism as the E2E lane's required guard.
_FAILURE_REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_FAILURE_REQUIRED"
_FAILURE_HARD_FAIL_EXIT = 6
_FAILURE_OUTCOMES: dict[str, set[str]] = {"passed": set(), "skipped": set(), "failed": set()}


def _failure_required_armed() -> bool:
    """Fail-SAFE arming (mirrors the E2E lane): any non-empty value other than
    an explicit disable (``0``/``false``/``no``/``off``) arms required mode —
    ``1``, ``true``, ``yes`` or ``" 1 "`` all arm. A caller who set the var at
    ALL meant the required lane; a typo must not silently downgrade it."""
    raw = os.environ.get(_FAILURE_REQUIRED_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _this_dir_integration_nodes(session: pytest.Session) -> set[str]:
    return {
        item.nodeid
        for item in session.items
        if _THIS_DIR in Path(str(item.fspath)).resolve().parents
        and "integration" in item.keywords
        and not _is_guard_selftest(item)
    }


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "setup" and report.outcome == "skipped":
        _FAILURE_OUTCOMES["skipped"].add(report.nodeid)
    elif report.when == "call":
        _FAILURE_OUTCOMES.setdefault(report.outcome, set()).add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _failure_required_armed():
        return
    nodes = _this_dir_integration_nodes(session)
    if not nodes:
        session.exitstatus = _FAILURE_HARD_FAIL_EXIT
        _report_hard_fail(
            session,
            [
                f"ZERO required failure-mode integration tests collected while "
                f"{_FAILURE_REQUIRED_ENV_VAR}=1 (naming typo / -k/-m mismatch / "
                "import error)"
            ],
        )
        return
    skipped = nodes & _FAILURE_OUTCOMES["skipped"]
    passed = nodes & _FAILURE_OUTCOMES["passed"]
    reasons: list[str] = []
    if skipped:
        reasons.append(
            f"{len(skipped)} of {len(nodes)} REQUIRED failure-mode integration test(s) "
            "were SKIPPED (Docker/Postgres absent or a fixture turned an infra failure "
            "into a skip)"
        )
    if not passed:
        reasons.append("ZERO required failure-mode integration tests PASSED")
    if reasons:
        session.exitstatus = _FAILURE_HARD_FAIL_EXIT
        _report_hard_fail(session, reasons)


def _report_hard_fail(session: pytest.Session, reasons: list[str]) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    sep = "\n  - "
    reporter.write_line(
        f"\n{_FAILURE_REQUIRED_ENV_VAR}=1 HARD FAILURE (exit {_FAILURE_HARD_FAIL_EXIT}):{sep}"
        + sep.join(reasons)
        + "\n  A required failure-mode lane must actually RUN its real-Postgres "
        "failure/replay/rollback/conflict rows — never a green '0 passed, N skipped'. "
        "Run on a host with Docker present, or invoke without "
        f"{_FAILURE_REQUIRED_ENV_VAR} for the optional/local lane.",
        red=True,
    )


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion — plain `asyncio.run` (no pytest-asyncio
    plugin in this workspace)."""
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(postgres_url: str) -> None:
    """Session-scoped one-time migration apply, on its own short-lived engine/loop."""

    async def _do() -> None:
        eng = create_async_engine(postgres_url)
        try:
            await adapter.apply_migrations(eng)
        finally:
            await eng.dispose()

    run_async(_do())


@pytest.fixture
def engine(postgres_url: str, _apply_migrations: None) -> Iterator[AsyncEngine]:
    """Function-scoped fresh `AsyncEngine` per test; TRUNCATE-reset on a
    throwaway engine first (see `measurement_pg/conftest.py` for the
    cross-loop rationale)."""

    async def _truncate() -> None:
        throwaway = create_async_engine(postgres_url)
        try:
            await adapter.truncate_all(throwaway)
        finally:
            await throwaway.dispose()

    run_async(_truncate())

    eng = create_async_engine(postgres_url)
    yield eng
    eng.sync_engine.dispose()


@pytest.fixture
def run() -> Any:
    """The `asyncio.run` driver every test in this suite uses, injected as a
    fixture (never `from conftest import run_async`, which collides under
    pytest's `prepend` import mode — same discipline as `measurement_pg`)."""
    return run_async
