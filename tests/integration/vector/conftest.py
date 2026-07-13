"""pytest fixtures for `tests/integration/vector` (w4-07).

Mirrors `tests/integration/persistence_postgres/conftest.py`'s own
`postgres:16-alpine` testcontainer + honest-Docker-skip + per-test-TRUNCATE
+ fresh-`AsyncEngine`-per-test conventions (ADR-0017), with two
w4-07-specific differences:

1. `packages/vector-store` is not (yet) a `uv` workspace member (see
   `packages/vector-store/README.md` "Packaging note") — this conftest
   inserts `packages/vector-store/src` onto `sys.path` directly (the same
   workaround `tests/unit/forgectl/conftest.py` uses for `tools/forgectl`)
   so `import saena_vector_store` resolves without an editable install.
2. This suite's own Postgres container additionally runs `CREATE EXTENSION
   vector` (`PgVectorStore.create_schema`) — the pgvector extension image
   requirement this package's README documents; `postgres:16-alpine` alone
   does not have the extension installed, so this conftest uses the
   `pgvector/pgvector:pg16` image instead (the official pgvector-bundled
   Postgres image) rather than plain `postgres:16-alpine`.

`tests/` is not a package here (no `tests/integration/vector/__init__.py`)
— mirrors `tests/unit/forgectl`'s own "no `__init__.py`" convention for a
non-workspace-member package requiring a `sys.path` insert, rather than
`tests/integration/persistence_postgres`'s `__init__.py` (that package IS a
normal workspace member; the two situations are not equivalent).
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
_VECTOR_STORE_SRC = _REPO_ROOT / "packages" / "vector-store" / "src"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

if str(_VECTOR_STORE_SRC) not in sys.path:
    sys.path.insert(0, str(_VECTOR_STORE_SRC))

from saena_vector_store.pgvector.adapter import PgVectorStore  # noqa: E402

# The dimension every fixture record/query in this suite is built against —
# baked into the `vector(N)` column at `create_schema()` time (see
# `PgVectorStore.create_schema` docstring). Kept small and deliberately
# distinct from `packages/vector-store`'s own default (`TestEmbedder`'s
# `dimension=8` default) so a test that forgets to pass `dimension=` to a
# factory helper fails loudly with a real `DimensionMismatchError` rather
# than silently matching by coincidence.
TEST_DIMENSION = 4


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — never starts a container to
    find out (mirrors `tests/integration/persistence_postgres/conftest.py`'s
    own probe, duplicated here rather than imported: that module is outside
    this patch unit's exclusive write paths)."""
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
        reason="Docker daemon not reachable — honest skip (ADR-0017), w4-07 pgvector suite"
    )
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except OSError:
            continue
        if _THIS_DIR in item_path.parents or item_path == _THIS_DIR:
            item.add_marker(pytest.mark.integration)
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: real-I/O test requiring a reachable Docker daemon (ADR-0017) — "
        "w4-07 real pgvector/Postgres testcontainer suite",
    )


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="session", autouse=True)
def _create_schema(postgres_url: str) -> None:
    """Session-scoped, one-time DDL: `CREATE EXTENSION vector`, this
    package's own schema/table/index, all baked to `TEST_DIMENSION`."""

    async def _do() -> None:
        eng = create_async_engine(postgres_url)
        try:
            await PgVectorStore.create_schema(eng, dimension=TEST_DIMENSION)
        finally:
            await eng.dispose()

    _run(_do())


@pytest.fixture
def engine(postgres_url: str, _create_schema: None) -> Iterator[AsyncEngine]:
    """Function-scoped fresh `AsyncEngine` per test — see `tests/integration/
    persistence_postgres/conftest.py`'s own `engine` fixture docstring for
    the full "event-loop-per-test discipline" rationale this mirrors
    verbatim (asyncpg connections are bound to the event loop that created
    them; a shared engine across separate `asyncio.run()` calls breaks)."""

    async def _truncate() -> None:
        throwaway = create_async_engine(postgres_url)
        try:
            await PgVectorStore.truncate(throwaway)
        finally:
            await throwaway.dispose()

    _run(_truncate())

    eng = create_async_engine(postgres_url)
    yield eng

    eng.sync_engine.dispose()
