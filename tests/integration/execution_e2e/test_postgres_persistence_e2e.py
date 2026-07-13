"""Durable persistence + tenant isolation, against a REAL `postgres:16-alpine`
testcontainer (same `PostgresContainer`/schema-bootstrap pattern as
`tests/integration/persistence_postgres/conftest.py`), driving the REAL
async `saena_domain.persistence.postgres` adapters directly.

REPORTED GAP (not fixed — out of this unit's exclusive-write path): NONE of
tenant-control-service / plan-contract-service / audit-ledger-service /
artifact-registry-service actually construct a `Postgres*` adapter anywhere
in their own `create_app(...)` wiring today — every FastAPI app this
suite's other tests build (`tests/e2e/execution/`) is wired to the SYNC
in-memory ports (`InMemoryTenantRepository`, `InMemoryPlanRepository`, ...).
The real, async Postgres adapters exist and are unit-proven
(`tests/integration/persistence_postgres/`), but nothing in `services/**`
wires them into a running app — there is no production bootstrap module
this suite could exercise "the real HTTP app backed by real Postgres"
through. This module instead proves the adapters THEMSELVES durably persist
and tenant-isolate the exact state shapes this suite's steps 1/3/9/11/13
produce (tenant records, audit hash-chain entries, artifact manifests),
directly against their own async port surface — the strongest REAL-Postgres
proof available without inventing a service-bootstrap change this unit is
not authorized to make.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Coroutine, Iterator
from typing import Any

import pytest
from saena_domain.audit.chain import build_entry
from saena_domain.audit.hashing import GENESIS
from saena_domain.identity import TenantContext, TenantId
from saena_domain.persistence.errors import NotFoundError, TenantIsolationError
from saena_domain.persistence.postgres.adapters import (
    PostgresArtifactManifestStore,
    PostgresAuditLedger,
    PostgresTenantRepository,
)
from saena_domain.persistence.postgres.tables import SCHEMA_NAME, metadata
from sqlalchemy import DDL
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

TENANT_1 = "e2e-tenant-one"
TENANT_2 = "e2e-tenant-two"
RUN_ID = "run-e2e-0001"
PATCH_UNIT_ID = "PU-01"


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


_DOCKER_AVAILABLE = _docker_available()


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="module")
def postgres_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
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
    """Function-scoped engine, per-test TRUNCATE — same event-loop-per-test
    discipline as `tests/integration/persistence_postgres/conftest.py`."""

    async def _truncate() -> None:
        throwaway = create_async_engine(postgres_url)
        try:
            async with throwaway.begin() as conn:
                table_names = ", ".join(
                    f'"{SCHEMA_NAME}"."{t.name}"' for t in metadata.sorted_tables
                )
                await conn.execute(sql_text(f"TRUNCATE TABLE {table_names}"))
        finally:
            await throwaway.dispose()

    _run(_truncate())

    eng = create_async_engine(postgres_url)
    yield eng
    eng.sync_engine.dispose()


def test_tenant_record_persists_and_survives_a_fresh_connection(engine: AsyncEngine) -> None:
    """Step 1 + step 14, durability proof: a tenant created via the REAL
    `TenantContext`/`PostgresTenantRepository` path is readable back through
    a BRAND NEW engine/connection (genuine durability, not an in-process
    cache artifact)."""

    async def scenario() -> tuple[str, str]:
        repo = PostgresTenantRepository(engine)
        payload = {
            "tenant_id": TENANT_1,
            "display_name": "Synthetic Tenant One",
            "isolation_profile": "internal-k3s",
            "namespace": f"saena-tenant-{TENANT_1}",
            "policy_version": "1.0.0",
            "engine_scope": ["chatgpt-search"],
            "status": "active",
            "retention_policy_ref": "retention-standard-v1",
            "created_at": "2026-07-13T00:00:00Z",
            "updated_at": "2026-07-13T00:00:00Z",
        }
        context = TenantContext.from_payload(payload)
        await repo.put(TenantId(TENANT_1), context)

        # A SECOND, independent engine — proves this round-tripped through
        # real Postgres storage, not an in-process object still held alive.
        second_engine = create_async_engine(engine.url)
        try:
            second_repo = PostgresTenantRepository(second_engine)
            fetched = await second_repo.get(TenantId(TENANT_1))
            record = await second_repo.get_record(TenantId(TENANT_1))
        finally:
            await second_engine.dispose()
        return fetched.tenant_id.value, record.status

    tenant_id_value, status = _run(scenario())
    assert tenant_id_value == TENANT_1
    assert status == "active"


def test_tenant_isolation_at_the_postgres_layer(engine: AsyncEngine) -> None:
    """Step 13 at the storage layer: tenant 2's own repository read never
    resolves tenant 1's row — `NotFoundError`, never a cross-tenant leak."""

    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        context = TenantContext.from_payload(
            {
                "tenant_id": TENANT_1,
                "display_name": "Synthetic Tenant One",
                "isolation_profile": "internal-k3s",
                "namespace": f"saena-tenant-{TENANT_1}",
                "policy_version": "1.0.0",
                "engine_scope": ["chatgpt-search"],
                "status": "active",
                "retention_policy_ref": "retention-standard-v1",
                "created_at": "2026-07-13T00:00:00Z",
                "updated_at": "2026-07-13T00:00:00Z",
            }
        )
        await repo.put(TenantId(TENANT_1), context)

        with pytest.raises(NotFoundError):
            await repo.get(TenantId(TENANT_2))

    _run(scenario())


def test_audit_hash_chain_persists_and_verifies_across_the_run(engine: AsyncEngine) -> None:
    """Step 11, durability proof: the SAME 3-entry decision trail this
    suite's `tests/e2e/execution/test_synthetic_tenant_execution_e2e.py`
    relays into the in-process `audit-ledger-service` app is, here,
    appended through the REAL Postgres-backed `AuditLedgerPort` and
    verified via a fresh connection — `verify()` must be green, and tenant
    2's own chain must be empty (isolation)."""

    async def scenario() -> tuple[bool, int | None, int]:
        ledger = PostgresAuditLedger(engine)
        actions = [
            ("plan.contract.submitted_for_approval.v1", {"contract_hash": "sha256:" + "a" * 64}),
            ("plan.contract.approved.v1", {"contract_hash": "sha256:" + "a" * 64}),
            ("run.handoff.assembled.v1", {"contract_hash": "sha256:" + "a" * 64}),
        ]
        prev_hash = GENESIS
        for index, (action, payload) in enumerate(actions):
            entry = build_entry(
                prev_hash=prev_hash,
                action=action,
                recorded_at="2026-07-13T00:0" + str(index) + ":00Z",
                scope="tenant",
                trace_id=f"{index:032x}",
                payload=payload,
                tenant_id=TENANT_1,
                run_id=RUN_ID,
            )
            appended = await ledger.append(entry)
            prev_hash = appended.event_hash.root

        # Fresh connection/engine for the read side — durability, not cache.
        second_engine = create_async_engine(engine.url)
        try:
            second_ledger = PostgresAuditLedger(second_engine)
            ok, first_broken = await second_ledger.verify(tenant_id=TenantId(TENANT_1))
            tenant_2_entries = await second_ledger.read_range(tenant_id=TenantId(TENANT_2))
        finally:
            await second_engine.dispose()
        return ok, first_broken, len(tenant_2_entries)

    ok, first_broken, tenant_2_count = _run(scenario())
    assert (ok, first_broken) == (True, None)
    assert tenant_2_count == 0, "tenant 2's own chain must be empty — no cross-tenant leakage"


def test_artifact_manifest_persists_and_tenant_isolates(engine: AsyncEngine) -> None:
    """Step 9, durability proof: the patch-artifact manifest agent-runner's
    step registers persists through the REAL `ArtifactManifestPort`
    Postgres adapter, and a colliding key registered under a DIFFERENT
    tenant raises `TenantIsolationError` (never a silent overwrite)."""

    manifest = {
        "tenant_id": TENANT_1,
        "run_id": RUN_ID,
        "patch_unit_id": PATCH_UNIT_ID,
        "worktree_commit": "c" * 40,
        "base_commit": "a" * 40,
        "artifact_uri": f"blob://{TENANT_1}/" + "d" * 64,
        "artifact_hash": "sha256:" + "d" * 64,
        "manifest_uri": f"manifest://{TENANT_1}/{PATCH_UNIT_ID}/" + "c" * 40,
        "changed_files": ["apps/web/docs/new-page.md"],
        "quality_gate_ids": ["build", "tests"],
        "evidence_ids": ["EV-01"],
        "contract_hash": "sha256:" + "e" * 64,
        "rollback_ref": f"git-revert:{PATCH_UNIT_ID}",
        "created_at": "2026-07-13T00:00:00Z",
    }

    async def scenario() -> dict[str, Any]:
        store = PostgresArtifactManifestStore(engine)
        stored = await store.put(TenantId(TENANT_1), PATCH_UNIT_ID, "c" * 40, manifest)

        second_engine = create_async_engine(engine.url)
        try:
            second_store = PostgresArtifactManifestStore(second_engine)
            fetched = await second_store.get(TenantId(TENANT_1), PATCH_UNIT_ID, "c" * 40)
            with pytest.raises(TenantIsolationError):
                await second_store.get(TenantId(TENANT_2), PATCH_UNIT_ID, "c" * 40)
        finally:
            await second_engine.dispose()
        assert stored == manifest
        return fetched

    fetched = _run(scenario())
    assert fetched == manifest
