"""pytest fixtures for `tests/integration/intelligence_e2e` (w4-17).

Mirrors `tests/integration/clickhouse/conftest.py`'s own `clickhouse/
clickhouse-server` testcontainer + honest-Docker-skip + per-test-TRUNCATE
conventions (ADR-0017) exactly — same probe, same skip-reason shape, same
session-scoped container / function-scoped truncate split. Duplicated here
rather than imported: that package's own conftest is outside this unit's
exclusive write paths (`tests/e2e/intelligence/**` and `tests/integration/
intelligence_e2e/**` only), and this repo's existing precedent (`tests/
integration/execution_e2e/conftest.py` vs. `tests/integration/bus/
conftest.py` vs. `tests/integration/persistence_postgres/conftest.py`, all
three carrying their own independently-duplicated Docker probe) is to keep
every integration subdirectory's own honest-skip probe self-contained.

`tests/e2e/intelligence` is inserted onto `sys.path` too — this package's
own test module reuses `intelligence_e2e_harness.py` (that directory's own
harness module) so the ClickHouse-backed lane builds from BYTE-IDENTICAL
synthetic input to the pure-synthetic lane (see that harness module's own
docstring for why this matters for the "same hash across lanes" assertion).
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_E2E_INTELLIGENCE_DIR = _REPO_ROOT / "tests" / "e2e" / "intelligence"

for _path in (_THIS_DIR, _E2E_INTELLIGENCE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor  # noqa: E402
from saena_analytics_clickhouse.schema import TABLE_NAMES, migrate_up  # noqa: E402
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore  # noqa: E402


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (copied verbatim from `tests/integration/clickhouse/
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


_DOCKER_AVAILABLE = _docker_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _DOCKER_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(
        reason="Docker daemon not reachable — honest skip (ADR-0017), w4-17 "
        "ClickHouse-backed composite intelligence E2E requires a reachable "
        "Docker daemon for the clickhouse/clickhouse-server testcontainer"
    )
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except OSError:
            continue
        if _THIS_DIR in item_path.parents or item_path == _THIS_DIR:
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises a real external test-server/container process "
        "(clickhouse/clickhouse-server testcontainer) — excluded from the "
        "blocking `just verify` unit lane.",
    )


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator[object]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    from testcontainers.clickhouse import ClickHouseContainer

    with ClickHouseContainer("clickhouse/clickhouse-server:24.8-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _migrated_executor(clickhouse_container: object) -> ClickHouseConnectExecutor:
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
def analytics_store(executor: ClickHouseConnectExecutor) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(executor)
