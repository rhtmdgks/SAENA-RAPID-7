# tools/contract-lint

Isolated Node toolchain for contract linting (ADR-0009/0011 — the sole Node exception).

## Known limitation (2026-07-12, W1)

`@asyncapi/cli` 6.x (parser-js v3) does NOT recognize
`schemaFormat: application/schema+json;version=draft-2020-12` — registered
JSON Schema formats stop at draft-07. Our AsyncAPI document truthfully
declares 2020-12 (ADR-0011 dialect), so `asyncapi validate` aborts with
"Unknown schema format".

Consequences (honest wiring):
- The BLOCKING gate for AsyncAPI correctness is the Python suite
  (`tests/contract/validate/test_asyncapi_*.py`,
  `test_composition_instances.py`) — real 2020-12 validation of every
  channel composition, stricter than the CLI.
- `just contract-lint-smoke` runs the CLI and asserts the failure is
  EXACTLY the known limitation (any other parse error fails the smoke).
- Re-evaluate at W2C (Redpanda wiring) — parser-js 2020-12 support or a
  shadow-doc strategy. Deviation from ADR-0011's toolchain table recorded
  here + surfaced in the W1 completion report.

Install: `npm ci --prefix tools/contract-lint --ignore-scripts`
