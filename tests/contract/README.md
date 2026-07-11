# tests/contract

## Purpose

Contract test harness design for SAENA RAPID-7. This document is the
implementer-facing design note for **W1** (the wave that adds the real
`packages/contracts` schema files and wires the compatibility harness
against real N-1 git tags). It also documents the W0 bootstrap fixtures
and tests that already live in this directory.

Authority: `docs/decisions/ADR-0011-contract-schema-conventions.md`,
`ADR-0012-contract-compatibility-policy.md`,
`ADR-0013-event-envelope-v1.md`. This README does not restate or
reinterpret those ADRs — where this doc and an ADR appear to disagree,
the ADR wins and this doc is wrong.

## Scope

In: directory layout for `validate/`, `compat/`, `fixtures/`; ownership
split between the Contracts Steward and testing/QA; the `contracts/{name}/vX.Y.Z`
tag scheme as consumed by the harness; the tolerant-read test
obligation. Out: the actual `packages/contracts` schema files (W1), git
tag issuance policy/authority (Contracts Steward, ADR-0011), CI wiring
(T17/T18).

## Layout

```
tests/contract/
├── README.md                      # this file
├── test_envelope_fixtures.py      # W0: envelope draft-schema fixture tests
├── test_compat_selfdiff.py        # W0: structural-diff function + self-diff smoke test
├── validate/                      # W1: per-contract schema self-validation +
│                                   #     instance validation (one module/dir per
│                                   #     contract in packages/contracts/registry.json)
├── compat/                        # W1: N-1 git-tag compatibility harness
│                                   #     (see "Compatibility harness" below)
└── fixtures/
    ├── envelope/                  # W0: envelope-specific fixtures (bootstrap,
    │   ├── draft-envelope.schema.json   #     see file header — non-authoritative)
    │   ├── valid/
    │   └── invalid/
    └── <contract-name>/           # W1: one fixture dir per contract, mirroring
                                    #     packages/contracts/registry.json entries
```

### `validate/`

Schema self-validation (does the schema file itself conform to JSON
Schema 2020-12 / OpenAPI 3.1 / AsyncAPI 3.0 — the `--check-metaschema`
class of check) plus instance validation (do the fixture instances in
`fixtures/<contract-name>/valid|invalid` validate as expected against
the contract's current schema). One module (or subdirectory) per
contract, named after the contract's `registry.json` entry.

### `compat/`

**N-1 git-tag comparison.** For each contract, given its current schema
and the schema as it existed at the previous release tag
(`contracts/{name}/vX.Y.Z`, ADR-0011), the compat harness performs the
two-leg check ADR-0012 mandates:

1. **Previous-tag examples validate against the current schema.**
   Resolve the most recent `contracts/{name}/vX.Y.Z` tag strictly older
   than the current working schema (via `packages/contracts/registry.json`
   + `git tag`/`git show <tag>:<path>`), load that tag's example
   instance fixtures, and run them through the current schema. All must
   pass — this is the "does the new schema still accept old instances"
   backward-compatibility check ADR-0012 §"Backward compatibility 1차
   보장" specifies as the primary breaking-change signal.

2. **Structural diff detects forbidden changes.** Independent of
   instance-level pass/fail, diff the previous-tag schema document
   against the current schema document and flag any of the following
   when they occur **without an accompanying major version bump**:
   - a **required** field added or removed,
   - a property's declared **type narrowed** (fewer accepted JSON types
     than before),
   - an **enum narrowed or widened** — per ADR-0012, both directions are
     breaking for event payloads (narrowing drops values a producer may
     still emit; widening produces a value an old consumer cannot
     recognize, i.e. forward-incompatible). This is a corrected
     position vs. the original draft ("widen = minor") — see ADR-0012
     §Context for the record of that correction.

   `structural_diff()` in `test_compat_selfdiff.py` is the W0 bootstrap
   implementation of leg 2's diff function (recursive: `required` sets,
   property `type`, `enum` sets, walked through `properties`, `$defs`,
   and `oneOf`/`anyOf`/`allOf` branches). W1 wires it to real N-1 tag
   pairs pulled via `git show`; W0 only proves the function against
   itself (self-diff must be empty) and against synthetic before/after
   dicts.

   For **signed contracts** (`additionalProperties: false`, closed —
   ADR-0012), *any* diff at all — including a plain optional-property
   addition — is breaking; the diff function's leg-2 output should be
   interpreted more strictly for that contract class than for open event
   payloads. W1 implementers: gate this distinction on the contract's
   `registry.json` category, not on ad hoc per-call flags.

   `oasdiff` is an OpenAPI-only **secondary** detector (ADR-0012) — it
   supplements, never replaces, the primary structural-diff harness for
   the OpenAPI-family contracts' path/parameter-level detail that JSON
   Schema diffing does not cover.

### `fixtures/`

Fixture instances, organized per-contract. Each contract's
`fixtures/<name>/valid/` and `fixtures/<name>/invalid/` mirror the
`envelope/valid|invalid` pattern established in W0 (see "Fixture
metadata convention" below). Fixtures are versioned alongside the
contract's git tag history — `compat/` reads *historical* fixture
snapshots via `git show <tag>:tests/contract/fixtures/<name>/valid/*.json`
(or equivalent), not just the working tree's current fixtures.

### Fixture metadata convention

Invalid fixtures MAY carry a top-level `_expected_violation` string
field (required) documenting why the fixture is invalid, and MAY carry
a `_note` field for fixtures that are intentionally schema-valid despite
representing a real-world invalid state (see the `cohort-below-threshold`
case below). Test code MUST strip these metadata keys before passing an
instance to a validator when the target schema seals extra properties
with `unevaluatedProperties: false` or `additionalProperties: false` —
otherwise the validator's failure reason degenerates into "unexpected
property `_expected_violation`" instead of the documented structural
violation, which defeats the fixture's purpose. See
`_strip_metadata_to_tempfile()` in `test_envelope_fixtures.py` for the
reference pattern.

## Ownership split (ADR-0011 §레지스트리, ADR-0012 §Harness 소유권 분리)

| Concern | Owner |
|---|---|
| Compatibility judgment rules (what counts as breaking) | **Contracts Steward** — sole authority, same line as ADR-0011's single-owner principle for `packages/contracts` |
| `packages/contracts/registry.json` content | **Contracts Steward** — sole authority |
| Git tag issuance (`contracts/{name}/vX.Y.Z`) | **Contracts Steward** — sole authority |
| Harness code (`validate/`, `compat/`, diff function, fixtures, CI wiring) | **testing/QA** — single implementation; dual/duplicate implementations of the same judgment logic are explicitly forbidden by ADR-0012 |

The Steward defines what breaking means and asserts it via tags/registry
entries; testing/QA is the sole implementer of the code that mechanically
checks it. Do not fork a second compatibility-checking implementation
inside a service repo "for convenience" — route through this harness.

## Tag scheme

`contracts/{name}/vX.Y.Z` (ADR-0011 §레지스트리). One tag per contract
release, full semver. The `compat/` harness resolves "the previous
version" for a given contract by listing tags matching
`contracts/{name}/v*`, sorting by semver, and picking the tag
immediately prior to the version currently under test — not by wall-clock
recency and not by walking `git log` on `main`.

## Tolerant-read test obligation (ADR-0012)

Independent of whether an enum change is (correctly) flagged as
breaking, every event-payload contract with a closed enum field (e.g.
`engine_id`, `de_identification_status`) MUST carry a **tolerant-read**
test: a fixture containing a value **not present** in the current
schema's enum, validated not against the schema (it is expected to fail
schema validation — that's the point of "enum change = major") but
against a **consumer-side handling stub** that asserts the stub degrades
safely (e.g. routes to a documented fallback branch, does not raise/crash)
rather than erroring. This is defense-in-depth for the
old-consumer/new-producer overlap window during a major version rollout,
not a loophole that makes enum widening non-breaking — ADR-0012 is
explicit that it is not a "free pass," it is a second, independent
safety net.

W1 implementers: this obligation currently has no worked example in this
repo (W0 shipped the envelope's `engine_id` enum as single-valued,
`["chatgpt-search"]`, so there is no "unknown value" to construct yet
without inventing a second engine). The first contract that ships with a
multi-value enum in W1 must include this test as part of its
`validate/` module — do not defer it a second time.

## What ships in W0 vs. W1

| Artifact | W0 (this patch unit) | W1 |
|---|---|---|
| `fixtures/envelope/{valid,invalid}/*.json` | shipped (3 valid, 4 invalid) | additional per-contract fixtures |
| `fixtures/envelope/draft-envelope.schema.json` | shipped, explicitly **non-authoritative** (see its `$comment`) | superseded by `packages/contracts/json-schema/envelope/v1/event-envelope.schema.json`, authored by Contracts Steward |
| `test_envelope_fixtures.py` | shipped | extended or retargeted once the authoritative schema lands |
| `test_compat_selfdiff.py` (`structural_diff()`) | shipped, self-diff only | wired to real N-1 git-tag pairs in `compat/` |
| `validate/`, `compat/` directories | **not created** — no content to validate yet beyond the envelope draft | created, populated per contract |
| Root `pyproject.toml` `testpaths` wiring | **not touched** (see Constraints) | T17/T18 |

## Constraints

- No fake green by deleting assertions.
- Root `pyproject.toml`'s `[tool.pytest.ini_options] testpaths = ["packages"]`
  is out of scope for this patch unit — `tests/contract` is invoked via
  explicit path (`uv run pytest tests/contract`) until T17/T18 wires it
  into `testpaths`. Do not edit root `pyproject.toml` from this harness
  work.
- `fixtures/envelope/draft-envelope.schema.json` is a harness bootstrap
  artifact, not a contract. It must never be imported/referenced by
  service code — only by this directory's tests.
- Harness judgment logic (what is breaking) must trace to an ADR, not to
  this README's prose, if the two ever conflict.

## Open decisions

- `validate/` and `compat/` directory-per-contract internal structure
  (single module per contract vs. shared parametrized suite) — W1.
- Whether `compat/`'s N-1 tag resolution needs to support N-2 depth —
  ADR-0012 §Open decisions, deferred to real usage data.

## Source specification references

- `docs/decisions/ADR-0011-contract-schema-conventions.md`
- `docs/decisions/ADR-0012-contract-compatibility-policy.md`
- `docs/decisions/ADR-0013-event-envelope-v1.md`
- `docs/architecture/testing-strategy.md`
- `docs/architecture/contract-conventions.md`

## Status

W0 bootstrap: envelope fixtures + draft schema + structural-diff
function + self-diff test IMPLEMENTED. `validate/`/`compat/` directories
and per-contract fixtures NOT IMPLEMENTED (W1).
