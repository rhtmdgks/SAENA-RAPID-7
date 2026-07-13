"""W3-08 synthetic-tenant execution E2E — real-container/test-server lane.

Covers the two mission steps `tests/e2e/execution/` deliberately cannot
(neither needs a mock — both need a REAL external process this repo already
has a harness for):

- `test_temporal_signal_e2e.py` — step 6, the ADR-0003 Temporal `approve`
  signal path, against a REAL `temporalio.testing.WorkflowEnvironment.
  start_time_skipping()` server (same pattern as `tests/integration/
  orchestrator/test_execution_workflow.py`).
- `test_event_bus_round_trip_e2e.py` — step 10, publishing this suite's own
  real event envelopes (`repo.intaken.v1`, `plan.contract.approved.v1`,
  `patch.unit.completed.v1`, `quality.gate.passed.v1`) to a REAL
  `redpandadata/redpanda` testcontainer and consuming them back (same
  pattern as `tests/integration/bus/test_redpanda_publisher.py`).
- `test_postgres_persistence_e2e.py` — durable persistence + tenant
  isolation for the tenant/plan/audit-chain/artifact-manifest state this
  suite's steps 1/3/11/13 exercise, against a REAL `postgres:16-alpine`
  testcontainer via `saena_domain.persistence.postgres`'s real async
  adapters (same pattern as `tests/integration/persistence_postgres/`).

Every test in this package is auto-marked `integration` by `tests/
integration/conftest.py`'s root `pytest_collection_modifyitems` hook — run
via `just test-integration`, never the blocking unit lane.
"""

from __future__ import annotations
