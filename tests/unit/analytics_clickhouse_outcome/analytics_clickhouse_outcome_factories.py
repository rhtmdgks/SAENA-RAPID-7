"""Factory helpers for `tests/unit/analytics_clickhouse_outcome` (w5-11).

Reuses `tests/unit/analytics_clickhouse`'s own `FakeClickHouseExecutor` +
`new_fake_executor_with_tables` verbatim (same in-memory, zero-I/O double,
now pre-seeded with `measurement_outcome` too since `schema.TABLE_NAMES`
includes it) rather than re-implementing a second fake — see that module's
own docstring for why `FakeClickHouseExecutor` understands exactly the fixed
SQL shapes `query.py` emits.

Deliberately NOT named `conftest.py` for the SAME collision reason
`analytics_clickhouse_factories.py`'s own docstring documents (pytest's
`prepend` import mode collides a second `conftest` module under the bare
top-level name once the whole `tests/` suite is collected together) — this
module is imported by its own unique dotted name
(`analytics_clickhouse_outcome_factories`, inserted onto `sys.path` by this
directory's own `conftest.py`).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from typing import Any

# `tests/unit/analytics_clickhouse` is a SIBLING test directory, not an
# importable package under `saena_*` — reach its factories module the same
# way this directory's own `conftest.py` reaches this module: insert its
# directory onto `sys.path` once, then import by bare dotted name.
_SIBLING_DIR = Path(__file__).resolve().parent.parent / "analytics_clickhouse"
if str(_SIBLING_DIR) not in sys.path:
    sys.path.insert(0, str(_SIBLING_DIR))

from analytics_clickhouse_factories import (  # noqa: E402
    FakeClickHouseExecutor,
    new_fake_executor_with_tables,
)
from saena_analytics_clickhouse.rows import MeasurementOutcomeRow  # noqa: E402

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_WINDOW_START = _dt.datetime(2026, 7, 1, tzinfo=_dt.UTC)
_WINDOW_END = _dt.datetime(2026, 7, 8, tzinfo=_dt.UTC)


def make_measurement_outcome_row(**overrides: Any) -> MeasurementOutcomeRow:
    """A `MeasurementOutcomeRow` with every required field defaulted to a
    valid, deterministic B-PASS-shaped fixture — override any field by
    keyword (mirrors `make_observation_row`'s own `**overrides` convention)."""
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "mo-1",
        "idempotency_key": "idem-mo-1",
        "occurred_at": _WINDOW_END,
        "experiment_id": "exp-1",
        "registration_canonical_hash": "sha256:" + "a" * 64,
        "window_started_at": _WINDOW_START,
        "window_ended_at": _WINDOW_END,
        "b_verdict": "pass",
        "reason_codes": ("two_independent_layers_confirmed",),
        "outcome_layer": "discovery",
        "sample_count_treatment": 128,
        "sample_count_control": 130,
        "insufficient_data": False,
        "evidence_bundle_manifest_hash": "sha256:" + "b" * 64,
        "grs_policy_version": "grs-v1",
        "grs_policy_hash": "sha256:" + "c" * 64,
        "grs_policy_provenance": "policy://grs/test-fixture",
        "evidence_basis_id": "sha256:" + "d" * 64,
        "net_of_control_lift": 0.12,
        "raw_lift": 0.15,
    }
    fields.update(overrides)
    return MeasurementOutcomeRow(**fields)


def new_fake_executor_with_outcome_table() -> FakeClickHouseExecutor:
    """A `FakeClickHouseExecutor` pre-seeded with every table this package
    owns (mirrors `migrate_up` having already run), including
    `measurement_outcome` — a thin re-export of
    `new_fake_executor_with_tables` under this directory's own name, since
    `schema.TABLE_NAMES` already includes `measurement_outcome` (w5-11)."""
    return new_fake_executor_with_tables()


__all__ = [
    "TENANT_A",
    "TENANT_B",
    "FakeClickHouseExecutor",
    "make_measurement_outcome_row",
    "new_fake_executor_with_outcome_table",
]
