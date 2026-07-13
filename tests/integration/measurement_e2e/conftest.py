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


#: EXPLICIT env-var contract that arms the zero-collected HARD FAILURE. The
#: c5-05 named-gate recipe (`just measurement-e2e`) sets this to "1" and names
#: this directory; in that invocation — and ONLY that invocation — zero items
#: collected FROM THIS DIRECTORY is a hard failure. An env-var contract is
#: used deliberately INSTEAD of guessing from `config.invocation_params.args`:
#: the real required CI invocation (`just test-integration` -> `pytest -m
#: integration` with NO bare path arg; locations come from pyproject
#: `testpaths`) passes no path to guess from, so path-guessing would be dead
#: code there; and a bare ancestor path (`pytest tests/integration -k <x>`)
#: would over-fire, hard-failing the whole suite because THIS lane collected 0
#: while an unrelated sibling test ran. The env var is unambiguous and robust
#: to how pytest is invoked.
_REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_E2E_REQUIRED"


def _required_armed() -> bool:
    """Fail-SAFE arming check (critic F should-fix): any non-empty value other
    than an explicit disable (``0``/``false``/``no``/``off``) arms required
    mode. So ``1``, ``true``, ``yes``, or even ``" 1 "`` (whitespace) all arm —
    a caller who sets the var at ALL meant the required lane; a typo like
    ``true`` must not silently downgrade it to the optional/honest-skip lane."""
    raw = os.environ.get(_REQUIRED_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _this_dir_items(items: list[pytest.Item]) -> list[pytest.Item]:
    return [item for item in items if _THIS_DIR in Path(str(item.fspath)).resolve().parents]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Runs ONCE after collection is FULLY complete — after every
    `pytest_collection_modifyitems` hook (including pytest's OWN internal
    `-k`/`-m` deselection) has run, and ALWAYS, even when the final selection
    is EMPTY. This is the correct home for the zero-collected HARD FAILURE:
    a session-scoped autouse fixture only instantiates when ≥1 test is
    actually selected (so it is silent on an empty selection — dead code for
    exactly the case it must catch), and `pytest_collection_modifyitems`
    fires BEFORE deselection (so it still sees the not-yet-deselected items).
    `session.items` here reflects the FINAL, post-deselection selection.

    The guard fires ONLY when the explicit env-var contract
    `SAENA_MEASUREMENT_E2E_REQUIRED=1` is set AND zero items were collected
    FROM THIS DIRECTORY specifically. That flag is set only by the c5-05
    required named-gate recipe (`just measurement-e2e`); an umbrella
    `just test-integration`, a dev ad-hoc run, or a broad `pytest
    tests/integration ...` never sets it, so 0-items-here in those runs is
    normal and silent (no false-fire). Counting items FROM THIS DIRECTORY —
    not the whole session — means a broad run that DOES set the flag and
    collects other directories but 0 here still fails correctly.

    Distinct from the Docker-absent honest skip (in
    `pytest_collection_modifyitems` below): a Docker-absent environment still
    COLLECTS every item here (they are merely marked skipped), so the count
    FROM THIS DIRECTORY is non-empty there — the guard stays silent and the
    individual honest skips stand. Zero items collected here WITH the flag set
    instead means a naming typo, a `-k`/`-m` mismatch, or an import/collection
    error silently produced nothing — a hard, non-5 failure, never exit-5.
    """
    if not _required_armed():
        return
    if _this_dir_items(session.items):
        return
    raise pytest.UsageError(
        "tests/integration/measurement_e2e collected ZERO test items while "
        f"{_REQUIRED_ENV_VAR}=1 — this is the REQUIRED real-container "
        "measurement E2E lane (wave5-plan.md E9); zero collection is a HARD "
        "FAILURE (returncode != 0, != 5), never an honest skip. A "
        "Docker-absent environment still COLLECTS these items (it only skips "
        "them individually with a reason); zero collection instead signals a "
        "naming typo, a -k/-m mismatch, or an import/collection error that "
        "must not silently pass."
    )


#: Test module (basename) whose items exercise the zero-collected GUARD
#: MECHANISM itself via subprocess + exit-code assertions — they need NO
#: Docker/ClickHouse/Temporal, only a Python interpreter, so they are EXEMPT
#: from the Docker/ClickHouse honest-skip below and run (proving the guard) on
#: every host, including Docker-absent CI.
_CONTAINER_FREE_GUARD_MODULE = "test_zero_collected_guard.py"


def _needs_containers(item: pytest.Item) -> bool:
    return Path(str(item.fspath)).name != _CONTAINER_FREE_GUARD_MODULE


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Hosts the honest per-item Docker/ClickHouse skips. The zero-collected
    HARD FAILURE lives in `pytest_collection_finish` above (which runs after
    `-k`/`-m` deselection and even on an empty selection); this hook fires
    BEFORE deselection, so it is NOT a reliable place to count final items.

    The container-free guard-mechanism module is EXEMPT from these skips: it
    proves the zero-collected guard via subprocess exit codes and needs no
    real infrastructure, so it must run even on a Docker-absent host."""
    container_items = [item for item in _this_dir_items(items) if _needs_containers(item)]
    if not container_items:
        return

    if not _DOCKER_AVAILABLE:
        skip_marker = pytest.mark.skip(
            reason="Docker daemon not reachable — honest skip (ADR-0017); this is the "
            "REQUIRED real-container measurement E2E lane and MUST run on any CI host "
            "with Docker present (c5-05 wiring)"
        )
        for item in container_items:
            item.add_marker(skip_marker)
        return
    if not _CLICKHOUSE_CONNECT_AVAILABLE:
        skip_marker = pytest.mark.skip(
            reason="clickhouse-connect not installed — analytics-clickhouse is not yet a "
            "registered root workspace member (see pyproject.toml Integrator note); "
            "honest skip, distinct from a Docker-unreachable skip"
        )
        for item in container_items:
            item.add_marker(skip_marker)


# --------------------------------------------------------------------------- #
# Required-mode fail-closed guard (MUST-FIX A): in REQUIRED mode the honest
# per-item skips above must NOT let the lane pass with the real-container
# scenarios un-run. `pytest_collection_finish` only catches ZERO COLLECTED; it
# does NOT catch "collected but all skipped" (infra absent → 24 collected, 19
# skipped, exit 0 = fail-open). This guard closes that: after the session, when
# `SAENA_MEASUREMENT_E2E_REQUIRED=1`, ANY skipped required container test — or
# ZERO passed — is a HARD FAILURE (non-zero, non-5 exit). Docker/ClickHouse/
# Temporal absence all surface as skips, so this one check covers every
# infra-absence, dependency-missing, and partial-skip path uniformly.
_HARD_FAIL_EXIT = 6
_OUTCOMES: dict[str, set[str]] = {"passed": set(), "skipped": set(), "failed": set()}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    # A setup-phase skip (fixture pytest.skip — how Docker/ClickHouse/Temporal
    # absence surfaces) reports at when=="setup"; a pass/fail at when=="call".
    if report.when == "setup" and report.outcome == "skipped":
        _OUTCOMES["skipped"].add(report.nodeid)
    elif report.when == "call":
        _OUTCOMES.setdefault(report.outcome, set()).add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _required_armed():
        return
    container_nodes = {
        item.nodeid for item in _this_dir_items(session.items) if _needs_containers(item)
    }
    skipped = container_nodes & _OUTCOMES["skipped"]
    passed = container_nodes & _OUTCOMES["passed"]
    reasons: list[str] = []
    if not container_nodes:
        # ZERO real-container tests were SELECTED while required mode is armed
        # (critic-F bypass): a `-k` keeping only the container-free guard
        # self-tests makes `pytest_collection_finish` silent (dir items exist)
        # AND leaves `container_nodes` empty. A required run that selects no
        # real-container scenario at all is a HARD FAILURE — the whole point of
        # arming the flag is to assert the real scenarios ran. (This is
        # independent of collection_finish's zero-DIR-items UsageError, whose
        # "empty" is whole-directory, not container-only.)
        reasons.append(
            "ZERO real-container E2E tests were SELECTED in required mode "
            "(a -k/-m selection that runs no Postgres/ClickHouse/Temporal scenario "
            "— the required flag asserts those scenarios RAN)"
        )
    if skipped:
        reasons.append(
            f"{len(skipped)} of {len(container_nodes)} REQUIRED real-container E2E "
            "test(s) were SKIPPED (infra absent: Docker/ClickHouse/Temporal, a missing "
            "runtime dependency, or a fixture that turned an infra failure into a skip)"
        )
    if not passed:
        reasons.append("ZERO required real-container E2E tests PASSED")
    if reasons:
        # Set the hard-fail exit code FIRST — it must hold even if the terminal
        # reporter is unavailable (e.g. `-p no:terminalreporter` via a poisoned
        # PYTEST_ADDOPTS), so the fail-closed contract never degrades to a
        # message-crash exit 1. Then guard the reporter for parity with the
        # failure sibling's `_report_hard_fail` (critic-F SHOULD-FIX).
        session.exitstatus = _HARD_FAIL_EXIT
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is None:
            return
        sep = "\n  - "
        reporter.write_line(
            f"\nSAENA_MEASUREMENT_E2E_REQUIRED=1 HARD FAILURE (exit {_HARD_FAIL_EXIT}):{sep}"
            + sep.join(reasons)
            + "\n  A required real-container lane must actually RUN its Postgres 16 / "
            "ClickHouse 24.8 / Temporal time-skipping scenarios — never a green "
            "'0 passed, N skipped'. Run on a host with Docker present, or invoke "
            "without SAENA_MEASUREMENT_E2E_REQUIRED for the optional/local lane.",
            red=True,
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
def _apply_migrations(request: pytest.FixtureRequest) -> None:
    # Resolve `postgres_url` LAZILY (not as a direct parameter): this is a
    # SESSION-scoped autouse fixture, so a direct `postgres_url` param would
    # pull `postgres_container` at session setup — and on a Docker-absent host
    # that fixture calls `pytest.skip(...)`, which (from a session-scoped
    # autouse fixture) sweeps EVERY test in the session into the skip,
    # including the container-free subprocess-based zero-collected guard tests
    # that must run on any host (c5-06 audit RV-3). Early-return before
    # touching the container when Docker is absent; the real container tests
    # still skip individually via `pytest_collection_modifyitems`.
    if not _DOCKER_AVAILABLE:
        return

    postgres_url = request.getfixturevalue("postgres_url")

    async def _do() -> None:
        eng = create_async_engine(postgres_url)
        try:
            await adapter.apply_migrations(eng)
        finally:
            await eng.dispose()

    run_async(_do())


@pytest.fixture(autouse=True)
def _truncate_postgres_before_each_test(request: pytest.FixtureRequest) -> None:
    """Autouse, function-scoped: TRUNCATE every w5-10-owned table before EACH
    test in this directory — the session-scoped Postgres container is shared
    across every scenario, and several scenarios deliberately reuse the SAME
    default tenant/experiment/run identity from `measurement_e2e_harness.py`'s
    builders (e.g. `build_pass_scenario()`'s defaults), which would otherwise
    collide against the real append-only/idempotency constraints ACROSS tests
    (a divergence a mock-only lane would never surface — the whole point of
    this real-container lane). Mirrors `measurement_pg/conftest.py::engine`'s
    own per-test TRUNCATE discipline, applied here as an autouse fixture so
    every test benefits without each one explicitly depending on it.

    Resolves `postgres_url`/`_apply_migrations` LAZILY (via `request.get
    fixturevalue`) rather than as direct parameters, and only for
    container-backed tests: the container-free guard-mechanism module must NOT
    pull the Postgres container (parameter resolution happens before the body,
    so a direct `postgres_url` param would sweep the subprocess-based guard
    tests into the Docker-absent skip — c5-06 audit RV-3). Those tests prove
    the zero-collected guard via subprocess exit codes and need no Docker."""
    if not _needs_containers(request.node) or not _DOCKER_AVAILABLE:
        return

    postgres_url = request.getfixturevalue("postgres_url")
    request.getfixturevalue("_apply_migrations")

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
