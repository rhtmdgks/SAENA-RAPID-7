"""pytest fixtures for `tests/integration/clickhouse` (w4-06).

Spec basis: ADR-0017 ("통합 테스트 — testcontainers-python — W2A부터 도입"),
mirrored here for a `clickhouse/clickhouse-server` container instead of
`postgres:16-alpine` — same "one container per SESSION, truncate between
tests" discipline as `tests/integration/persistence_postgres/conftest.py`
(this package's own tables are recreated once via `saena_analytics_clickhouse.
schema.migrate_up`, then TRUNCATEd between tests rather than dropped/
recreated).

Honest skip (mission instruction: "Docker unavailable -> write+skipif+report"):
the Docker daemon reachability probe below is copied verbatim from
`tests/integration/persistence_postgres/conftest.py` (same three
candidate-socket paths) — this is a REAL, verifiable "Docker is down" signal
(a raw socket connect), never a swallowed container-start exception. Every
test in this package is marked `pytest.mark.integration` (also auto-applied
by the root `tests/integration/conftest.py`, belt-and-suspenders).

Dependency note: `clickhouse-connect` (this package's only third-party
runtime dependency) is not yet present in the shared root `uv.lock`/venv as
of this patch unit (see `packages/analytics-clickhouse/pyproject.toml`'s
Integrator note — the package is not yet a registered workspace member). If
`clickhouse-connect` is not importable, this package's own tests are skipped
with an honest reason distinct from "Docker unreachable" (see
`_clickhouse_connect_available` below) — this is NOT a Docker-availability
report and must not be conflated with one.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor  # noqa: E402
from saena_analytics_clickhouse.schema import MIGRATIONS, TABLE_NAMES, migrate_up  # noqa: E402
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore  # noqa: E402


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (copied verbatim from `tests/integration/persistence_postgres/
    conftest.py::_docker_available`, same rationale)."""
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except OSError:
            continue
        if _THIS_DIR not in item_path.parents and item_path != _THIS_DIR:
            continue
        if not _DOCKER_AVAILABLE:
            item.add_marker(
                pytest.mark.skip(reason="Docker daemon not reachable — honest skip (ADR-0017)")
            )
        elif not _CLICKHOUSE_CONNECT_AVAILABLE:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "clickhouse-connect not installed — this package is not yet a "
                        "registered root workspace member (see pyproject.toml Integrator "
                        "note); honest skip, distinct from a Docker-unreachable skip"
                    )
                )
            )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017)"
    )


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator[object]:
    if not _DOCKER_AVAILABLE or not _CLICKHOUSE_CONNECT_AVAILABLE:
        pytest.skip("Docker daemon not reachable or clickhouse-connect not installed")
    from testcontainers.clickhouse import ClickHouseContainer

    with ClickHouseContainer("clickhouse/clickhouse-server:24.8-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _migrated_executor(clickhouse_container: object) -> ClickHouseConnectExecutor:
    """Session-scoped: one real client, tables created once via `migrate_up`."""
    import clickhouse_connect

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
def executor(_migrated_executor: ClickHouseConnectExecutor) -> ClickHouseConnectExecutor:
    """Function-scoped: TRUNCATE every owned table before each test (clean
    slate), reusing the session's client/connection."""
    for table in TABLE_NAMES:
        _migrated_executor.execute(f"TRUNCATE TABLE IF EXISTS {table}")
    return _migrated_executor


@pytest.fixture
def store(executor: ClickHouseConnectExecutor) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(executor)


@pytest.fixture
def migrations() -> tuple:
    return MIGRATIONS
