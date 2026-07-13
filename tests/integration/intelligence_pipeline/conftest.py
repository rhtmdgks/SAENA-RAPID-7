"""pytest fixtures for `tests/integration/intelligence_pipeline` (w4-13).

Chains the ALREADY-BUILT Wave-4 intelligence components end to end against a
REAL ClickHouse container (`clickhouse/clickhouse-server`, `testcontainers`)
— this package writes/reads NOTHING new: it wires

    saena_chatgpt_observer.pool_capture.run_pooled_observation
        -> saena_chatgpt_observer.artifact_gateway (single raw-content gateway)
        -> saena_analytics_clickhouse.store.ClickHouseAnalyticsStore (real ClickHouse)
        -> saena_citation_intelligence.service.normalize_citation

exactly as `docs/architecture/wave4-plan.md` w4-13 describes ("observation
-> artifact -> ClickHouse -> citation intelligence integration").

Two of the three intelligence packages this suite imports
(`saena_citation_intelligence`, `saena_analytics_clickhouse`) are NOT yet
root-workspace members as of this patch unit (see each package's own
`pyproject.toml` "NOTE"/"Integrator" comment) — this conftest inserts their
`src/` directories onto `sys.path` directly, the SAME workaround
`tests/integration/vector/conftest.py` and `tests/unit/svc_citation_
intelligence/conftest.py` already use for `saena_vector_store`/
`saena_citation_intelligence`. `saena_chatgpt_observer` (this suite's third
intelligence package) IS already a registered workspace member (Wave 3,
`services/acquisition/chatgpt-observer-service` — unchanged by that
registration status here) and imports normally, no `sys.path` insert needed.

Docker/dependency-availability discipline mirrors `tests/integration/
clickhouse/conftest.py` EXACTLY (same three-candidate-socket Docker probe,
copied verbatim rather than imported — that module lives outside this
unit's own exclusive write paths, `tests/integration/intelligence_pipeline/
**` only): a real, verifiable "Docker is down" signal (raw socket connect),
distinct from an honest "`clickhouse-connect` not installed" skip (this
package's own runtime dependency situation — see `packages/analytics-
clickhouse/pyproject.toml`'s Integrator note: it is not yet pulled into the
shared `uv.lock`/venv). Every test in this package is marked `pytest.mark.
integration` (also auto-applied by the root `tests/integration/conftest.py`,
belt-and-suspenders, same convention every other `tests/integration/**`
subdirectory conftest follows).
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent

_CITATION_INTELLIGENCE_SRC = (
    _REPO_ROOT / "services" / "intelligence" / "citation-intelligence-service" / "src"
)
_ANALYTICS_CLICKHOUSE_SRC = _REPO_ROOT / "packages" / "analytics-clickhouse" / "src"

for _path in (_THIS_DIR, _CITATION_INTELLIGENCE_SRC, _ANALYTICS_CLICKHOUSE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor  # noqa: E402
from saena_analytics_clickhouse.schema import TABLE_NAMES, migrate_up  # noqa: E402
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore  # noqa: E402


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (copied verbatim from `tests/integration/clickhouse/
    conftest.py::_docker_available`, itself copied from `tests/integration/
    persistence_postgres/conftest.py`, same rationale each time: outside
    this unit's own exclusive write paths, so duplicated rather than
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
                        "clickhouse-connect not installed — saena_analytics_clickhouse is not "
                        "yet a registered root workspace member (see its pyproject.toml "
                        "Integrator note); honest skip, distinct from a Docker-unreachable skip"
                    )
                )
            )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017) — "
        "w4-13 observation->artifact->ClickHouse->citation composite pipeline suite.",
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
    """Session-scoped: one real client, tables created once via `migrate_up`
    (mirrors `tests/integration/clickhouse/conftest.py`'s own fixture)."""
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
