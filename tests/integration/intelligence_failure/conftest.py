"""pytest fixtures for `tests/integration/intelligence_failure` (w4-18).

Failure / rollback / rebuild / idempotency coverage for the Wave-4
intelligence stack (claim-evidence ledger + QEEG read-projection,
chatgpt-observer capture, analytics-clickhouse append store, experiment
ledger hash chain, bus outbox/idempotency). SYNTHETIC + deterministic —
no live ChatGPT/creds/customer repo anywhere in this package (mission
constraint), mirrors `tests/integration/failure_modes/**`'s (w3-09) own
style exactly: a real-testcontainer half for the outbox/idempotency
mechanism (Postgres, already proven generically by w3-09) composed with
this unit's OWN pure-Python failure-injection scenarios for the
intelligence-specific ledgers/projections, which need no container at all
(claim-evidence ledger, QEEG replay, experiment ledger, and the
ClickHouse-shaped store are all pure in-memory adapters over an injected
seam — see each source module's own docstring).

`services/intelligence/claim-evidence-service` and
`packages/analytics-clickhouse` are BOTH deliberately not yet root `uv`
workspace members (see each package's own `pyproject.toml` "NOTE" —
registering a new workspace member touches root `pyproject.toml`, outside
every parallel Wave-4 unit's exclusive write path; Integrator-only, per
CLAUDE.md "단일 owner"). This conftest inserts each package's `src/`
directly onto `sys.path`, exactly like `tests/unit/svc_claim_evidence/
conftest.py`'s own precedent (that module's docstring explains the
rationale in full; reused verbatim here rather than re-argued). `saena_
domain` (qeeg + experiment + bus + persistence) and `saena_chatgpt_
observer` ARE already root-registered workspace members and need no such
insert.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_CLAIM_EVIDENCE_SRC = _REPO_ROOT / "services" / "intelligence" / "claim-evidence-service" / "src"
_ANALYTICS_CLICKHOUSE_SRC = _REPO_ROOT / "packages" / "analytics-clickhouse" / "src"

for _path in (_THIS_DIR, _CLAIM_EVIDENCE_SRC, _ANALYTICS_CLICKHOUSE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (copied verbatim from `tests/integration/failure_modes/
    conftest.py::_docker_available`, itself copied from `tests/integration/
    persistence_postgres/conftest.py`, same rationale each time: a real,
    verifiable "Docker is down" signal, never a swallowed container-start
    exception)."""
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
    """Only the Postgres-backed outbox/idempotency scenario
    (`test_rollback_fail_closed.py::test_*_against_real_postgres*`) needs a
    reachable Docker daemon — every other scenario in this package is pure
    in-memory/deterministic and always runs. Tests are opted into the
    Docker-only skip via `pytest.mark.docker` (applied locally on the
    handful of real-Postgres tests), never blanket-applied to the whole
    package (deliberately narrower than `tests/integration/failure_modes/
    conftest.py`'s own blanket "every `integration`-marked test" skip,
    since MOST of this package's own tests carry no such real-I/O
    dependency at all)."""
    if _DOCKER_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(
        reason="Docker daemon not reachable — honest skip (ADR-0017); only "
        "this package's real-Postgres outbox/idempotency scenario needs it"
    )
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017)"
    )
    config.addinivalue_line(
        "markers",
        "docker: this specific test needs a reachable Docker daemon "
        "(a subset of this package's own `integration`-marked tests)",
    )


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Plain `asyncio.run` — no pytest-asyncio plugin is installed in this
    workspace (see `tests/integration/failure_modes/conftest.py`'s own
    identical precedent/docstring)."""
    import asyncio

    return asyncio.run(coro)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[Any]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(postgres_container: Any) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture
def pg_schema(postgres_url: str) -> None:
    """NOT session-scoped/autouse (deliberately, unlike `tests/integration/
    failure_modes/conftest.py::_create_schema`) — an autouse fixture would
    force the skip-if-no-Docker `postgres_container`/`postgres_url` chain to
    resolve for EVERY test collected in this package, not just the one
    module that actually needs real Postgres. Function-scoped instead;
    `pg_engine` below is the only fixture that pulls this one in."""
    from saena_domain.persistence.postgres.tables import SCHEMA_NAME, metadata
    from sqlalchemy import DDL
    from sqlalchemy.ext.asyncio import create_async_engine

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
def pg_engine(postgres_url: str, pg_schema: None) -> Iterator[Any]:
    """Function-scoped fresh `AsyncEngine`, tables truncated first (clean
    slate per test) — mirrors `tests/integration/failure_modes/conftest.py::
    engine` exactly."""
    from saena_domain.persistence.postgres.tables import SCHEMA_NAME, metadata
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

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
