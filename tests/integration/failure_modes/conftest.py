"""pytest fixtures for `tests/integration/failure_modes` (w3-09).

Container-backed half of the rollback-verification gate (testing-strategy.md
sec F-7) — the pure/deterministic half lives under `tests/security/
test_rollback_*.py`. Mirrors `tests/integration/persistence_postgres/
conftest.py`'s own `postgres:16-alpine` testcontainer + honest-Docker-skip
pattern EXACTLY (deliberately duplicated, not imported — that sibling
directory is outside this patch unit's exclusive write paths, and a bare
`from conftest import ...` collides once the whole suite is collected
together; see that module's own docstring for the full rationale, reused
verbatim here rather than re-argued).

Every test in this package is auto-marked `pytest.mark.integration` by the
ROOT `tests/integration/conftest.py`'s own `pytest_collection_modifyitems`
(path-scoped, applies to every test under `tests/integration/**`
unconditionally) — this conftest's own `pytest_configure` marker
registration below is redundant-but-harmless local documentation, matching
every sibling directory's own precedent.
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
from sqlalchemy import DDL, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from saena_domain.persistence.postgres.tables import SCHEMA_NAME, metadata  # noqa: E402


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (same precedent as `tests/integration/persistence_postgres/
    conftest.py::_docker_available`)."""
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
    skip_marker = pytest.mark.skip(reason="Docker daemon not reachable — honest skip (ADR-0017)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017)"
    )


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Plain `asyncio.run` — see `persistence_postgres/conftest.py`'s own
    "Event-loop-per-test discipline" docstring for why (no pytest-asyncio
    plugin is installed in this workspace)."""
    return asyncio.run(coro)


@pytest.fixture(scope="session", autouse=True)
def _create_schema(postgres_url: str) -> None:
    async def _do() -> None:
        eng = create_async_engine(postgres_url)
        try:
            async with eng.begin() as conn:
                await conn.execute(DDL(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}"'))
                await conn.run_sync(metadata.create_all)
        finally:
            await eng.dispose()

    _run(_do())


@pytest.fixture
def engine(postgres_url: str, _create_schema: None) -> Iterator[AsyncEngine]:
    """Function-scoped fresh `AsyncEngine` per test — see
    `persistence_postgres/conftest.py`'s own docstring for the cross-loop
    `asyncpg` rationale this mirrors exactly."""

    async def _truncate() -> None:
        throwaway = create_async_engine(postgres_url)
        try:
            async with throwaway.begin() as conn:
                table_names = ", ".join(
                    f'"{SCHEMA_NAME}"."{t.name}"' for t in metadata.sorted_tables
                )
                await conn.execute(text(f"TRUNCATE TABLE {table_names}"))
        finally:
            await throwaway.dispose()

    _run(_truncate())

    eng = create_async_engine(postgres_url)
    yield eng

    eng.sync_engine.dispose()
