"""pytest fixtures for `tests/integration/clickhouse_outcome` (w5-11).

Same "one container per SESSION, TRUNCATE between tests" discipline as
`tests/integration/clickhouse/conftest.py` — this directory intentionally
does NOT spin up a SECOND container: it reuses the exact same session-scoped
`ClickHouseContainer` fixture chain (imported directly, not duplicated),
since both directories exercise the SAME `saena_analytics_clickhouse`
package/schema and a second container per test session would be a pure
waste of Docker-daemon resources with no isolation benefit (the "one
container per session" precedent this repo already established for the
sibling `tests/integration/clickhouse` directory is deliberately preserved
here, not re-litigated). Every table this package owns — including
`measurement_outcome` (w5-11) — is created once via `migrate_up` and
TRUNCATEd before each test.

Honest skip (mission instruction, ADR-0017): reuses the SAME Docker-daemon
reachability probe / `clickhouse-connect`-importability check as the sibling
`tests/integration/clickhouse/conftest.py` (verbatim copy of the probe logic,
not an import of it — `conftest.py` modules are not meant to be imported
across directories, same rationale test factory modules give for their own
non-`conftest` naming).
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
from saena_analytics_clickhouse.schema import TABLE_NAMES, migrate_up  # noqa: E402
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore  # noqa: E402

# Same env-var-name convention as `tests/integration/clickhouse/conftest.py`
# — a DEDICATED name for this directory (never re-using the sibling
# directory's own constant by import, per this module's own docstring), a
# fixed obviously-synthetic value, `setdefault` so a real run that already
# set it is never silently overwritten.
TEST_QUERY_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__OUTCOME_INTEGRATION_FIXTURE"
os.environ.setdefault(
    TEST_QUERY_SIGNING_KEY_ENV_VAR,
    "outcome-integration-test-fixture-signing-key-not-a-real-secret",
)


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (verbatim copy of `tests/integration/clickhouse/conftest.py`'s
    own probe, see this module's docstring for why it is copied, not
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
    """Session-scoped: one real client, every owned table (including
    `measurement_outcome`) created once via `migrate_up`."""
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
    """Function-scoped: TRUNCATE every owned table before each test."""
    for table in TABLE_NAMES:
        _migrated_executor.execute(f"TRUNCATE TABLE IF EXISTS {table}")
    return _migrated_executor


@pytest.fixture
def store(executor: ClickHouseConnectExecutor) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(executor)
