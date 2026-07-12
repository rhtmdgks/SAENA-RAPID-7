"""pytest fixtures for `tests/integration/persistence_postgres` (w2-13).

Spec basis: ADR-0017 ("통합 테스트 — testcontainers-python — W2A부터 도입"). One
`postgres:16-alpine` testcontainer is started ONCE per test SESSION (container
startup is the expensive part; a fresh container per test would make this
suite far slower for no isolation benefit) and every table this patch unit
owns (`saena_domain.persistence.postgres.tables.metadata`) is created once
against it. Per-TEST isolation is achieved by TRUNCATE-ing every owned table
between tests, not by tearing down/recreating the container or schema — this
keeps the suite fast while still giving each test a clean slate.

Event-loop-per-test discipline: this workspace has no pytest-asyncio-style
plugin installed, so every test function drives its own async work via a
single `asyncio.run(scenario())` call (see `tests/unit/domain_identity/
test_execution_context.py`'s own precedent) — each such call opens a BRAND
NEW event loop. `asyncpg` connections are bound to the event loop they were
created on and cannot be reused across a different loop (a
session-or-module-scoped `AsyncEngine`/connection pool created inside one
`asyncio.run()` call raises `InterfaceError: cannot perform operation:
another operation is in progress` the moment a DIFFERENT `asyncio.run()`
call — i.e. a different test's `scenario()` — tries to borrow a pooled
connection). The fixtures below therefore create a FRESH `AsyncEngine` PER
TEST (function-scoped `engine` fixture) bound to that test's own upcoming
`asyncio.run()` call, while the testcontainer itself (the expensive part)
stays session-scoped — the engine is a cheap, in-process pool object with no
actual connections opened until first use.

Honest skip (module docstring "Honest skip" requirement): every test in this
package is marked `pytest.mark.integration`. If the Docker daemon is not
reachable, the whole package is skipped via `pytest_collection_modifyitems`
below (probed once via a raw socket connect to the Docker socket/TCP host,
never by attempting a container start and swallowing the resulting
exception) — this is an HONEST skip (a real, verifiable "Docker is down"
signal), not a silent no-op. Docker IS confirmed running for this patch
unit's own verification run, so these tests are expected to actually
execute, not be skipped.

`run_async` (the `asyncio.run(scenario())` driver every test module in this
package uses) deliberately does NOT live in this file, even though it is
conceptually fixture-adjacent — it lives in `postgres_factories.py` instead.
Reason: pytest's default `prepend` import mode imports every `conftest.py`
in a collected tree under the SAME bare top-level name `conftest`; when the
FULL suite (`tests/unit/**` + `tests/contract/**` + this package) is
collected together, a plain `from conftest import run_async` in one of this
package's test modules resolves to WHICHEVER `conftest` module Python's
import cache already holds — often a different directory's `conftest.py`
entirely — raising `ImportError: cannot import name 'run_async' from
'conftest'`. This is the EXACT collision
`tests/unit/domain_persistence/persistence_factories.py`'s own docstring
documents (proven empirically there first); `postgres_factories.py`'s
uniquely-named module sidesteps it here the same way. Pytest FIXTURES
(the `@pytest.fixture`-decorated functions below) are unaffected by this —
pytest resolves fixtures through its own plugin manager by fixture name,
never through a plain `import conftest` statement, so they are safe to keep
in this file.
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
    find out (that would conflate "Docker is down" with any other container
    startup failure, and would be slow on every collection)."""
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
    # Default: local Unix domain socket (Docker Desktop / Colima / OrbStack).
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
    """Run a coroutine to completion — plain `asyncio.run`, no pytest-asyncio
    plugin is installed in this workspace (see module docstring precedent:
    `tests/unit/domain_identity/test_execution_context.py`'s own
    `asyncio.run(scenario())` pattern, reused here at fixture scope)."""
    return asyncio.run(coro)


@pytest.fixture(scope="session", autouse=True)
def _create_schema(postgres_url: str) -> None:
    """Session-scoped, one-time DDL: create the schema + every owned table.

    Uses its OWN short-lived engine/event-loop (via `_run`), entirely
    separate from the function-scoped `engine` fixture below — this fixture
    runs once, before any test's own `asyncio.run(scenario())` call, so
    there is no cross-loop connection reuse to worry about here.
    """

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
    """Function-scoped: a FRESH `AsyncEngine` per test (see module docstring
    "Event-loop-per-test discipline").

    Truncation runs against a SEPARATE, fully disposed throwaway engine
    (its own `asyncio.run()` call, its own event loop, closed before this
    fixture returns) rather than the `eng` instance handed to the test —
    `AsyncEngine.dispose()` alone does not guarantee every pooled
    `asyncpg` connection has fully released its loop-bound state
    synchronously enough to be safe for a DIFFERENT loop to reuse the same
    engine object afterward; using a throwaway engine sidesteps that
    entirely, so `eng` below has NEVER opened a connection before the test's
    own `asyncio.run(scenario())` call opens the first one against it.
    """

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

    # Synchronous pool teardown (NOT `await eng.dispose()`): the engine was
    # used inside the TEST's own `asyncio.run(scenario())` loop, which has
    # already been closed by the time this fixture resumes after `yield` —
    # an async `dispose()` here would need yet another event loop and hits
    # the same cross-loop `asyncpg` connection problem this fixture's own
    # docstring describes. `Engine.dispose()` (the sync facade under
    # `AsyncEngine.sync_engine`) closes the underlying connection pool
    # without needing a running loop at all, which is sufficient cleanup —
    # the pooled connections' sockets are closed at the OS level either way.
    eng.sync_engine.dispose()
