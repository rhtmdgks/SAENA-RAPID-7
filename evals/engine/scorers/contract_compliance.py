"""Axis 2 — contract compliance: "produced payloads validate against frozen
contracts" (Algorithm §11.1 diff-rationality / Contract Acceptance Matrix).

Fixture `input` names a `schema_relpath` (relative to
`packages/contracts/json-schema/`) and a `payload`; `evals.engine.
schema_validation.validate_payload` runs the REAL, frozen, versioned JSON
Schema contract file (not a copy) against it via `jsonschema` +
`referencing.Registry` local `$ref` resolution.
"""

from __future__ import annotations

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult
from evals.engine.schema_validation import validate_payload


def score(fixture: Fixture) -> ScoreResult:
    schema_relpath = fixture.input["schema_relpath"]
    payload = fixture.input["payload"]

    errors = validate_payload(schema_relpath, payload)
    passed = not errors
    return ScoreResult(passed=passed, score=1.0 if passed else 0.0, reasons=tuple(errors))


__all__ = ["score"]
