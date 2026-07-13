"""pytest fixtures for `tests/integration/measurement_e2e` (w5-19/c5-01) — the
REAL composed measurement E2E: real Postgres 16 + real ClickHouse 24.8 +
Temporal time-skipping, all in ONE lane, driving the ACTUAL
`saena_experiment_attribution.pipeline.run_measurement` composition (never a
mock/in-memory stand-in — that lane is `tests/e2e/measurement/**`).

Fixture composition mirrors the THREE existing real-container conftests this
task named as the read-first reference, combined into one session:

- `tests/integration/measurement_pg/conftest.py` — Postgres 16 testcontainer +
  migrations + per-test TRUNCATE + the `run` (`asyncio.run`) driver.
- `tests/integration/clickhouse_outcome/conftest.py` — ClickHouse 24.8
  testcontainer (session-scoped) + per-test TRUNCATE + `clickhouse-connect`
  availability probe.
- `tests/integration/measurement_workflow/conftest.py` /
  `test_measurement_workflow.py` — Temporal time-skipping test-server probe
  (bounded-timeout, honest-skip on startup failure).

Honest-skip discipline (ADR-0017), WITH the task's required hardening: a
Docker-absent / infra-absent environment gets an honest, explicit
`pytest.mark.skip` per missing dependency (never a silent pass) — but
`pytest_collection_modifyitems` ALSO fails the WHOLE session hard if this
directory collects ZERO test items regardless of cause (a collection-error/
import-error hiding as "no tests ran" must never look like an honest skip).
The per-item Docker/Temporal skip and the zero-collected hard-failure are
deliberately different mechanisms: the former honors a genuinely
Docker-absent local dev machine; the latter guards the CI lane (Docker-present
host, c5-05-wired) against silently collecting nothing.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_MEASUREMENT_PG_DIR = _REPO_ROOT / "tests" / "integration" / "measurement_pg"
_E2E_HARNESS_DIR = _REPO_ROOT / "tests" / "e2e" / "measurement"
_ATTRIBUTION_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)
_SKILL_BANK_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "strategy-skill-bank-service" / "src"
)

for _p in (_THIS_DIR, _MEASUREMENT_PG_DIR, _E2E_HARNESS_DIR, _ATTRIBUTION_SRC, _SKILL_BANK_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from saena_experiment_attribution.persistence import adapter  # noqa: E402

# --------------------------------------------------------------------------- #
# Honest-skip probes — verbatim-copied probe LOGIC (never imported across test
# directories, matching this repo's own established convention: each
# integration conftest duplicates the tiny socket probe rather than sharing a
# module, so no directory's collection depends on a sibling directory's file).
# --------------------------------------------------------------------------- #


def _docker_available() -> bool:
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


def _clickhouse_connect_available() -> bool:
    try:
        import clickhouse_connect  # noqa: F401
    except ImportError:
        return False
    return True


_DOCKER_AVAILABLE = _docker_available()
_CLICKHOUSE_CONNECT_AVAILABLE = _clickhouse_connect_available()

#: Test-only env var / signing key for the ClickHouse analytics query layer —
#: dedicated name for THIS directory (never imported from the sibling
#: `clickhouse_outcome` directory's own constant), fixed obviously-synthetic
#: value, `setdefault` so a real run that already set it is never overwritten.
_QUERY_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__MEASUREMENT_E2E_FIXTURE"
os.environ.setdefault(
    _QUERY_SIGNING_KEY_ENV_VAR,
    "measurement-e2e-integration-test-fixture-signing-key-not-a-real-secret",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: real-I/O test requiring a reachable Docker daemon "
        "(Postgres 16 + ClickHouse 24.8 testcontainers) and, for the "
        "Temporal-timer scenarios, a startable temporalio time-skipping "
        "test-server process (ADR-0017).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    this_dir_items = [
        item for item in items if _THIS_DIR in Path(str(item.fspath)).resolve().parents
    ]
    if not _DOCKER_AVAILABLE:
        skip_marker = pytest.mark.skip(
            reason="Docker daemon not reachable — honest skip (ADR-0017); this is the "
            "REQUIRED real-container measurement E2E lane and MUST run on any CI host "
            "with Docker present (c5-05 wiring)"
        )
        for item in this_dir_items:
            item.add_marker(skip_marker)
        return
    if not _CLICKHOUSE_CONNECT_AVAILABLE:
        skip_marker = pytest.mark.skip(
            reason="clickhouse-connect not installed — analytics-clickhouse is not yet a "
            "registered root workspace member (see pyproject.toml Integrator note); "
            "honest skip, distinct from a Docker-unreachable skip"
        )
        for item in this_dir_items:
            item.add_marker(skip_marker)


def pytest_collectstart(collector: pytest.Collector) -> None:
    # No-op hook retained only to document intent: collection ERRORS (as
    # opposed to zero collected items) already fail pytest's exit status on
    # their own; the explicit hard-failure guard lives in the session-scoped
    # `_require_nonzero_collection` fixture below (autouse), which is the
    # simplest reliable place to assert "this directory collected at least
    # one test item" without fighting pytest's own collection-error reporting.
    return


@pytest.fixture(scope="session", autouse=True)
def _require_nonzero_collection(request: pytest.FixtureRequest) -> Iterator[None]:
    """Hard-fail (not skip) if this directory collected ZERO test items.

    An honest per-item Docker/Temporal skip (above) still COLLECTS the item —
    it just marks it skipped, which is the correct, visible outcome for a
    genuinely Docker-absent local machine. What this guard catches is the
    OTHER failure mode: an import error, a naming typo (`test_*` mis-spelled),
    or a collection-time exception that makes pytest report "0 tests ran"
    with NO skip reason at all — which must never be mistaken for a passing
    lane. `session.testscollected` reflects the whole session's collected
    item count; this fixture is autouse + session-scoped so it evaluates once
    regardless of which test in this directory runs first.
    """
    yield
    session = request.session
    collected_here = [
        item for item in session.items if _THIS_DIR in Path(str(item.fspath)).resolve().parents
    ]
    if not collected_here:
        pytest.fail(
            "tests/integration/measurement_e2e collected ZERO test items — "
            "this is the REQUIRED real-container measurement E2E lane "
            "(wave5-plan.md E9); zero collection is a hard failure, never an "
            "honest skip (a Docker-absent environment still COLLECTS items, "
            "it only skips them individually)",
            pytrace=False,
        )


def run_async(coro):  # noqa: ANN001, ANN201
    """The `asyncio.run` driver every test in this suite uses, injected as a
    fixture below (never imported directly — see `measurement_pg/conftest.py`
    docstring on the `prepend`-import-mode collision this avoids)."""
    import asyncio

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
    if not _DOCKER_AVAILABLE:
        return

    async def _do() -> None:
        eng = create_async_engine(postgres_url)
        try:
            await adapter.apply_migrations(eng)
        finally:
            await eng.dispose()

    run_async(_do())


@pytest.fixture(autouse=True)
def _truncate_postgres_before_each_test(postgres_url: str, _apply_migrations: None) -> None:
    """Autouse, function-scoped: TRUNCATE every w5-10-owned table before EACH
    test in this directory — the session-scoped Postgres container is shared
    across every scenario, and several scenarios deliberately reuse the SAME
    default tenant/experiment/run identity from `measurement_e2e_harness.py`'s
    builders (e.g. `build_pass_scenario()`'s defaults), which would otherwise
    collide against the real append-only/idempotency constraints ACROSS tests
    (a divergence a mock-only lane would never surface — the whole point of
    this real-container lane). Mirrors `measurement_pg/conftest.py::engine`'s
    own per-test TRUNCATE discipline, applied here as an autouse fixture so
    every test benefits without each one explicitly depending on it."""
    if not _DOCKER_AVAILABLE:
        return

    async def _truncate() -> None:
        throwaway = create_async_engine(postgres_url)
        try:
            await adapter.truncate_all(throwaway)
        finally:
            await throwaway.dispose()

    run_async(_truncate())


@pytest.fixture
def pg_engine(
    postgres_url: str, _truncate_postgres_before_each_test: None
) -> Iterator[AsyncEngine]:
    """Function-scoped fresh `AsyncEngine` — TRUNCATE already ran via the
    autouse fixture above; this just hands back a connection for tests that
    want to issue raw SQL directly (none currently do, kept for parity with
    `measurement_pg/conftest.py::engine`)."""
    eng = create_async_engine(postgres_url)
    yield eng
    eng.sync_engine.dispose()


@pytest.fixture
def run():  # noqa: ANN201
    return run_async


# --------------------------------------------------------------------------- #
# ClickHouse — session container, function-scoped TRUNCATE (mirrors
# clickhouse_outcome/conftest.py).
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator[object]:
    if not _DOCKER_AVAILABLE or not _CLICKHOUSE_CONNECT_AVAILABLE:
        pytest.skip("Docker daemon not reachable or clickhouse-connect not installed")
    from testcontainers.clickhouse import ClickHouseContainer

    with ClickHouseContainer("clickhouse/clickhouse-server:24.8-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _migrated_ch_executor(clickhouse_container: object):  # noqa: ANN201
    import clickhouse_connect
    from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor
    from saena_analytics_clickhouse.schema import migrate_up

    client = clickhouse_connect.get_client(
        host=clickhouse_container.get_container_host_ip(),
        port=int(clickhouse_container.get_exposed_port(8123)),
        username=clickhouse_container.username,
        password=clickhouse_container.password,
        database=clickhouse_container.dbname,
    )
    executor = ClickHouseConnectExecutor(client)
    migrate_up(executor)
    return executor


@pytest.fixture
def ch_executor(_migrated_ch_executor):  # noqa: ANN001, ANN201
    from saena_analytics_clickhouse.schema import TABLE_NAMES

    for table in TABLE_NAMES:
        _migrated_ch_executor.execute(f"TRUNCATE TABLE IF EXISTS {table}")
    return _migrated_ch_executor


@pytest.fixture
def ch_store(ch_executor):  # noqa: ANN001, ANN201
    from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

    return ClickHouseAnalyticsStore(ch_executor)


# --------------------------------------------------------------------------- #
# Temporal time-skipping — bounded-timeout honest-skip probe, module-scoped
# environment shared by every Temporal-timer test in this directory (mirrors
# measurement_workflow/test_measurement_workflow.py's own probe fixture).
# --------------------------------------------------------------------------- #

_TEMPORAL_STARTUP_TIMEOUT_SECONDS = 30


async def _try_start_temporal_environment():  # noqa: ANN202
    import asyncio

    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    try:
        return await asyncio.wait_for(
            WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter),
            timeout=_TEMPORAL_STARTUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - probe: capture ANY startup failure to skip on
        return exc


@pytest.fixture(scope="session")
def _temporal_probe_result():  # noqa: ANN201
    if not _DOCKER_AVAILABLE:
        return RuntimeError("Docker daemon not reachable — skipping Temporal probe too")
    return run_async(_try_start_temporal_environment())


@pytest.fixture
def temporal_env(_temporal_probe_result):  # noqa: ANN001, ANN201
    if isinstance(_temporal_probe_result, Exception):
        pytest.skip(
            "temporalio time-skipping test server unavailable "
            f"(startup failed within {_TEMPORAL_STARTUP_TIMEOUT_SECONDS}s): "
            f"{type(_temporal_probe_result).__name__}: {_temporal_probe_result}"
        )
    return _temporal_probe_result


@pytest.fixture(scope="session", autouse=True)
def _shutdown_temporal_environment_after_session(_temporal_probe_result) -> Iterator[None]:  # noqa: ANN001
    yield
    if not isinstance(_temporal_probe_result, Exception):
        run_async(_temporal_probe_result.shutdown())
