"""W2A approval-flow integration tests — component-wired flows.

Wires the ALREADY-MERGED forge-console-api, plan-contract-service,
policy-gate-service, audit-ledger-service apps together through their real
HTTP surfaces (`fastapi.testclient.TestClient` / `httpx.ASGITransport`,
never a direct Python import of one service by another — services-are-
independent, `.importlinter`) plus SHARED in-memory persistence
(`saena_domain.persistence` reference adapters) so events/decisions/audit
entries actually flow between the wired apps within one test process.

See `harness.py` for the shared wiring; `tests/e2e/approval/` builds the
end-to-end happy-path/fail-closed/bypass narrative on top of the same
harness.
"""

from __future__ import annotations
