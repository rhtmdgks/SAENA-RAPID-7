# evals/fixtures

See ../README.md. Scaffold approved 2026-07-12 (ADR-0007 D-7).

## w3-10 (2026-07-13) — IMPLEMENTED

Deterministic, seeded YAML fixtures for 8 of the 9 mandatory eval axes
(`forbidden_action`'s fixtures live under `../policy-tests/forbidden_action/`
instead — see that directory's own README):

```
patch_correctness/    contract_compliance/   approval_enforcement/
tenant_isolation/      failure_recovery/      reproducibility/
evidence_integrity/    handoff_completeness/
```

Every fixture (`evals/engine/fixture.py::Fixture`) declares: `fixture_id`,
`axis`, `seed`, `description`, `tag` (`nominal` |
`false_positive_guard` | `false_negative_guard`), `expected_passed`,
`expected_score`, `threshold`, `input`. Every one of the 8 axes here
carries at least one `false_positive_guard` AND one `false_negative_guard`
fixture — see `evals/engine/scorers/<axis>.py` docstrings for what each
one proves. Scored by `evals/engine/scorers/`, run by
`tests/unit/evals_harness/test_all_axes.py` (CI-blocking, unit lane).
