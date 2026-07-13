"""`evals.engine` — the deterministic, fixture-based eval harness core.

Modules:
  - `fixture`: `Fixture` value object + YAML fixture loader.
  - `result`: `ScoreResult` (a scorer's pure output) + `FixtureOutcome`
    (a fixture's expectation vs. actual result, with the pass/fail verdict
    the harness itself renders).
  - `runner`: `run_fixture`/`run_axis`/`run_directory` — pure, seeded,
    no-wall-clock execution of one fixture (or a whole axis directory)
    against a scorer function.
  - `evidence_registry`: the evidence-integrity primitive shared by the
    `evidence_integrity` axis AND every other axis/fixture that carries a
    `material_claims` block (CLAUDE.md principle 11 — "증거 없는 완료 선언 금지",
    "no unregistered evidence").
  - `schema_validation`: local, offline `jsonschema` validation against
    `packages/contracts/json-schema/**` (the frozen, versioned domain/event
    contracts) — the `contract_compliance` axis's primitive.
  - `scorers/`: one pure module per eval axis, each exposing a single
    `score(fixture: Fixture) -> ScoreResult` function.

Every module in this package is pure: no `datetime.now()`/`time.time()`
wall-clock read, no `random`/`secrets`/`uuid4()` — every fixture's `seed`
field is carried through for provenance (some scorers use it directly, e.g.
`reproducibility`), but the harness itself never substitutes randomness for
a fixture's own explicit `input` data. Given the same fixture file, every
scorer produces the byte-identical `ScoreResult` on every run, on every
machine (Algorithm §11.3 "reproducibility" completion criterion, applied to
the harness's own code, not only to what it evaluates).
"""

from __future__ import annotations
