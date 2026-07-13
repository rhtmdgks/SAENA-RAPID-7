"""Factory helpers + fakes for `tests/integration/intelligence_failure` (w4-18).

Deliberately NOT named `conftest.py`'s own module surface (see that file's
docstring / `tests/integration/failure_modes/failure_modes_postgres_
factories.py`'s identical precedent for the collision rationale). Every
factory here builds SYNTHETIC, deterministic fixtures only — no live
ChatGPT/creds/customer repo content anywhere in this module.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from saena_analytics_clickhouse.errors import AnalyticsClickHouseError
from saena_analytics_clickhouse.rows import ObservationRow
from saena_analytics_clickhouse.schema import TABLE_NAMES
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore
from saena_chatgpt_observer.observation import PlatformObservation
from saena_chatgpt_observer.source import CapturedObservation, FakeObservationSource
from saena_claim_evidence.evaluation import EvidenceFreshnessPolicy, EvidenceLinkStatus
from saena_domain.events import EnvelopeFactory
from saena_domain.experiment.models import ExperimentArm, ExperimentRegistration, MetricDefinition
from saena_domain.identity import TenantId
from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim

TENANT_A = "acme-co"
TENANT_B = "globex-co"

RUN_ID = "run-w4-18-0001"


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Plain `asyncio.run` — no pytest-asyncio plugin is installed in this
    workspace (same precedent reused throughout this repo's integration
    suites, e.g. `tests/integration/failure_modes/
    failure_modes_postgres_factories.py::run_async`)."""
    return asyncio.run(coro)


# --- claim-evidence -----------------------------------------------------------------


def make_extracted_claim(**overrides: Any) -> ExtractedClaim:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "project_id": "proj-1",
        "claim_id": "claim-1",
        "entity_id": "entity-1",
        "claim_text": "our product reduces churn by an evidence-backed margin",
        "status": "active",
        "effective_from": "2026-07-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z",
    }
    fields.update(overrides)
    return ExtractedClaim.model_validate(fields)


def make_evidence_record(**overrides: Any) -> EvidenceRecord:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "project_id": "proj-1",
        "evidence_id": "evidence-1",
        "claim_id": "claim-1",
        "source_uri": "https://example.com/case-study",
        "excerpt": "customer case study excerpt",
        "freshness_checked_at": "2026-07-01T00:00:00Z",
        "content_hash": "sha256:" + "a" * 64,
    }
    fields.update(overrides)
    return EvidenceRecord.model_validate(fields)


DEFAULT_FRESHNESS_POLICY = EvidenceFreshnessPolicy(max_age_seconds=90 * 24 * 3600)
DEFAULT_NOW = datetime(2026, 7, 13, tzinfo=UTC)
DEFAULT_LINK_STATUSES: dict[str, EvidenceLinkStatus] = {"evidence-1": EvidenceLinkStatus.LINKED}


# --- experiment ledger ----------------------------------------------------------------


def make_experiment_registration(**overrides: Any) -> ExperimentRegistration:
    fields: dict[str, Any] = {
        "experiment_id": "exp-1",
        "tenant_id": TENANT_A,
        "run_id": RUN_ID,
        "arms": (
            ExperimentArm(arm_id="baseline", role="baseline"),
            ExperimentArm(arm_id="treatment", role="treatment", asset_ref="ref://asset/treatment"),
            ExperimentArm(arm_id="control", role="control", asset_ref="ref://asset/control"),
        ),
        "metric_definitions": (
            MetricDefinition(metric_id="citation_rate", description="citation rate per query"),
        ),
        "query_cluster_ref": "ref://query-cluster/1",
        "locale": "en-US",
        "browser_policy": "standard",
        "repeat_count": 3,
        "asset_hash": "sha256:" + "b" * 64,
        "code_version_hash": "sha256:" + "c" * 64,
        "created_by": "actor-experimenter",
        "approved_by": "actor-approver",
        "created_at": DEFAULT_NOW,
    }
    fields.update(overrides)
    return ExperimentRegistration.model_validate(fields)


# --- chatgpt-observer -----------------------------------------------------------------


def make_platform_observation(**overrides: Any) -> PlatformObservation:
    fields: dict[str, Any] = {
        "engine_id": "chatgpt-search",
        "tenant_id": TENANT_A,
        "run_id": RUN_ID,
        "query_text": "best crm for startups",
        "citation_refs": ("ref://citation/1",),
        "raw_object_ref": "ref://object/1",
        "observed_at": "2026-07-13T00:00:00Z",
    }
    fields.update(overrides)
    return PlatformObservation(**fields)


def make_observation_source_with_one_query(
    *, query_text: str = "best crm for startups", fail_times: int = 0
) -> FakeObservationSource:
    """A `FakeObservationSource` pre-registered with exactly one query,
    optionally scheduled to fail transiently `fail_times` times before
    succeeding (or, for `fail_times` set above the run's own retry budget by
    the caller, to exhaust retries and never succeed — see
    `test_rollback_fail_closed.py`)."""
    source = FakeObservationSource()
    source.register_query(
        query_text,
        CapturedObservation(citation_refs=("ref://citation/1",), raw_object_ref="ref://object/1"),
    )
    if fail_times:
        source.fail_next(query_text, times=fail_times)
    return source


# --- analytics-clickhouse: in-memory fake executor -------------------------------------
#
# Deliberately a LOCAL duplicate of `tests/unit/analytics_clickhouse/
# analytics_clickhouse_factories.py::FakeClickHouseExecutor` (outside this
# patch unit's exclusive write paths — not imported from), same collision
# rationale as every other duplicated factory module in this repo's
# integration suites (see module docstring). This module ADDS one
# capability that unit-lane fixture does not need: `FailingInsertExecutor`,
# an executor whose `insert_rows` can be armed to raise on demand — the
# vehicle for this package's "ClickHouse insert failure leaves no partial
# committed state" scenario.

_EQ_PARAM_RE = re.compile(r"^eq_(.+)_(\d+)$")
_FROM_RE = re.compile(r"FROM\s+(\w+)", re.IGNORECASE)
_SELECT_RE = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE)
_LIMIT_RE = re.compile(r"LIMIT\s+(\d+)", re.IGNORECASE)


def _extract_table(sql: str) -> str:
    match = _FROM_RE.search(sql)
    assert match is not None, "query SQL must contain a FROM clause"
    return match.group(1)


def _select_columns(sql: str) -> list[str]:
    match = _SELECT_RE.search(sql)
    assert match is not None, "query SQL must contain a SELECT clause"
    return [c.strip() for c in match.group(1).split(",")]


def _matches(row: dict[str, Any], params: Mapping[str, Any]) -> bool:
    for key, value in params.items():
        if key == "tenant_id":
            if row.get("tenant_id") != value:
                return False
        elif key == "range_start":
            if row.get("occurred_at") < value:
                return False
        elif key == "range_end":
            if not (row.get("occurred_at") < value):
                return False
        else:
            eq_match = _EQ_PARAM_RE.match(key)
            if eq_match is not None:
                column = eq_match.group(1)
                if row.get(column) != value:
                    return False
    return True


class FakeClickHouseExecutor:
    """In-memory `ClickHouseExecutor` — zero I/O, understands exactly the
    fixed SQL shapes `saena_analytics_clickhouse.query`/`schema` emit (see
    the unit-lane sibling this duplicates for the full rationale)."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.ddl_log: list[str] = []
        self._lock = threading.Lock()

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        self.ddl_log.append(sql)

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> Sequence[tuple[Any, ...]]:
        params = params or {}
        table = _extract_table(sql)
        with self._lock:
            rows = list(self.tables.get(table, []))
        filtered = [row for row in rows if _matches(row, params)]
        limit_match = _LIMIT_RE.search(sql)
        if limit_match is not None:
            filtered = filtered[: int(limit_match.group(1))]
        columns = _select_columns(sql)
        return [tuple(row.get(column) for column in columns) for row in filtered]

    def insert_rows(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        with self._lock:
            stored = self.tables.setdefault(table, [])
            for values in rows:
                stored.append(dict(zip(columns, values, strict=True)))


def new_fake_clickhouse_executor() -> FakeClickHouseExecutor:
    """Pre-seeded with every table this package owns (mirrors `migrate_up`
    having already run)."""
    executor = FakeClickHouseExecutor()
    for table in TABLE_NAMES:
        executor.tables[table] = []
    return executor


class SimulatedInsertFailure(AnalyticsClickHouseError):
    """Synthetic "ClickHouse insert failure" — a transient/broker-shaped
    failure this package's own store never catches (matching the real
    `clickhouse-connect` driver's own behavior on a network/insert error:
    it propagates, it is never silently swallowed by `ClickHouseAnalyticsStore.
    _append`)."""

    error_code = "saena.analytics_clickhouse.simulated_insert_failure"


@dataclass
class FailingInsertExecutor:
    """Wraps a `FakeClickHouseExecutor`; `insert_rows` raises
    `SimulatedInsertFailure` while `armed` is `True` (armed by the test,
    disarmed to prove a SUBSEQUENT clean retry succeeds). `query`/`execute`
    always delegate straight through — only the INSERT path is ever made to
    fail, matching the mission's "ClickHouse insert failure" scenario
    specifically (not a blanket connectivity outage)."""

    inner: FakeClickHouseExecutor = field(default_factory=new_fake_clickhouse_executor)
    armed: bool = False
    insert_attempts: int = 0

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        self.inner.execute(sql, params)

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> Sequence[tuple[Any, ...]]:
        return self.inner.query(sql, params)

    def insert_rows(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        self.insert_attempts += 1
        if self.armed:
            raise SimulatedInsertFailure(
                "simulated ClickHouse insert failure — synthetic, no real driver involved",
                context={"table": table},
            )
        self.inner.insert_rows(table, columns, rows)


def make_observation_row(**overrides: Any) -> ObservationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "obs-1",
        "idempotency_key": "idem-obs-1",
        "occurred_at": datetime(2026, 7, 1, tzinfo=UTC),
        "engine_id": "chatgpt-search",
        "run_id": RUN_ID,
        "query_text": "best crm for startups",
        "citation_refs": ("ref://citation/1",),
        "raw_object_ref": "ref://object/1",
    }
    fields.update(overrides)
    return ObservationRow(**fields)


def new_clickhouse_store(executor: Any) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(executor)


# --- bus / outbox / idempotency envelope ------------------------------------------------


def make_patch_unit_completed_envelope(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = RUN_ID,
    patch_unit_id: str = "PU-INTEL-01",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """A real `patch.unit.completed.v1` envelope — used here purely as the
    vehicle to exercise the GENERIC outbox/idempotent-consumer mechanism
    (`saena_domain.bus`) this package's own claim-evidence/observation
    events would flow through once a later unit wires a producer for them;
    this patch unit's OWN exclusive path never adds a new event contract
    (`packages/contracts`/`packages/schemas` — single owner, w4-10 — are
    out of scope), so it reuses the SAME already-registered channel w3-09's
    own factories use for exactly this purpose (see that module's own
    docstring)."""
    key = idempotency_key or f"{tenant_id}:{run_id}:{patch_unit_id}"
    return EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id=tenant_id,
        run_id=run_id,
        idempotency_key=key,
        payload={
            "patch_unit_id": patch_unit_id,
            "worktree_commit": "d" * 40,
            "manifest_uri": f"manifest://{tenant_id}/{patch_unit_id}/{'d' * 40}",
            "changed_files": ["services/intelligence/README.md"],
            "quality_gate_ids": ["tests-01"],
        },
    )


__all__ = [
    "DEFAULT_FRESHNESS_POLICY",
    "DEFAULT_LINK_STATUSES",
    "DEFAULT_NOW",
    "RUN_ID",
    "TENANT_A",
    "TENANT_B",
    "FailingInsertExecutor",
    "FakeClickHouseExecutor",
    "SimulatedInsertFailure",
    "TenantId",
    "make_evidence_record",
    "make_experiment_registration",
    "make_extracted_claim",
    "make_observation_row",
    "make_observation_source_with_one_query",
    "make_patch_unit_completed_envelope",
    "make_platform_observation",
    "new_clickhouse_store",
    "new_fake_clickhouse_executor",
    "run_async",
]
