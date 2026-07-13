"""saena_orchestrator — agent-orchestrator-service (W2B).

Public surface:
  - `saena_orchestrator.workflow_logic` — pure run-state-machine core
    (import-safe, unit-testable without a Temporal server): re-validates
    approval signals over `saena_domain.policy` (ADR-0003 step 4
    defense-in-depth).
  - `saena_orchestrator.timeouts` — Activity `startToCloseTimeout`/heartbeat
    constants (W2B exit gate: `>= 7200s + buffer`).
  - `saena_orchestrator.workflow` — the Temporal `ExecutionWorkflow`
    definition (WAITING_APPROVAL -> EXECUTING only via `approve` signal).
  - `saena_orchestrator.activities` — the stub execution Activity (real
    execution lands in W3).
  - `saena_orchestrator.signal_client` — the `SignalClient` local port
    plan-contract-service uses to send the `approve` signal (no cross-service
    Python import — see that module's docstring).

Source specification references (READ ONLY basis for this module):
- docs/decisions/ADR-0003-approval-transition-authority-path.md
- docs/architecture/implementation-waves.md (W2B exit)
- docs/architecture/resilience.md (Activity timeout/heartbeat formula)
- docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md §4.3
"""

from __future__ import annotations

__all__: list[str] = []
