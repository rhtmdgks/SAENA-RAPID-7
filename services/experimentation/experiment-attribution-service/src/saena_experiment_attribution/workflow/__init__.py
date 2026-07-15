"""saena_experiment_attribution.workflow — durable 7-day measurement Temporal
workflow (w5-14).

Public surface (mirrors ``saena_orchestrator``'s module split):
  - ``workflow_logic`` — pure measurement-workflow state-machine core
    (import-safe, unit-testable WITHOUT a Temporal server): structural
    re-check of the already-``Accepted`` confirmation reference, idempotency/
    conflict classification, terminal outcome vocabulary.
  - ``timeouts`` — Activity ``startToCloseTimeout``/heartbeat constants
    (resilience.md conventions).
  - ``activities`` — ``derive_window`` (wraps ``start_measurement_window``) +
    the ``collect_and_decide`` activity CONTRACT (Protocol) and a deterministic
    fixture implementation (the real DiD/B-gate pipeline is w5-13's).
  - ``workflow`` — the Temporal ``MeasurementWorkflow`` definition
    (signal-driven clock start, single replay-safe durable 7-day timer).

Source specification references (READ ONLY basis for this module):
- docs/architecture/wave5-plan.md (w5-14; E2; H5/H6; Binding conventions
  "Policy-Gate-first fail-closed → direct Temporal signal; bus events
  notification-only")
- docs/decisions/ADR-0003 (approval-transition authority path pattern, reused
  for the deployment-confirmed signal)
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §7.3:483 (Day-2 rule)
- saena_domain.measurement.{confirmation,clock} (REUSED validation/window
  semantics — not reimplemented here)
"""

from __future__ import annotations

__all__: list[str] = []
