"""Wave 5 measurement/B-layer domain modules (pure, deterministic).

Module ownership (wave5-plan.md DAG — one unit per module file):
confirmation/clock (w5-03), binding (w5-04), did (w5-05),
outcome_layer/b_gate/reason_codes (w5-06), grs (w5-07), evidence (w5-08),
ports (w5-09). Public re-exports are added by the Integrator at merge time only.

Separate namespace from ``saena_domain.experiment`` by design: the W4
registration model is registration-only and structurally guarded against
outcome vocabulary (tests/unit/domain_experiment/test_no_outcome_fields.py).
"""
