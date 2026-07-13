"""W3-08 synthetic-tenant execution E2E suite — pure-orchestration-logic
narrative (no real external container/test-server process; see
`tests/integration/execution_e2e/` for the container/Temporal-backed
counterparts of steps 6 and 10).

Builds on `tests/integration/approval_flow`'s shared plan-contract/
policy-gate/audit-ledger harness pieces and `tests/unit/svc_repository_intake`'s
fakes (`conftest.py` inserts both directories onto `sys.path`) rather than
duplicating that wiring — this package's own job is the full Plan ->
approval -> patch -> verify -> handoff narrative, plus the git-backed
worktree/artifact-registry adapters this specific mission needs
(`git_worktree_adapter.py`, `artifact_registry_adapters.py`).
"""

from __future__ import annotations
