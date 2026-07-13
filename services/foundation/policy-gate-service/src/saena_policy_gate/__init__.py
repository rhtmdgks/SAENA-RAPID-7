"""saena_policy_gate — OPA-style default-deny policy gate (W2A).

Public surface:
  - `saena_policy_gate.engine` — default-deny `PolicyEngine`, argv-level
    command deny-bypass classification.
  - `saena_policy_gate.service` — fail-closed orchestration, H-3 plan-check,
    idempotent decision recording.
  - `saena_policy_gate.app` — FastAPI application (`create_app()` / `app`).
  - `saena_policy_gate.errors` — `saena.<category>.<reason>` error taxonomy.
"""

from __future__ import annotations

__all__: list[str] = []
