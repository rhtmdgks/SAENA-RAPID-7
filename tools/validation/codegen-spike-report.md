# Codegen + compatibility planner spike — datamodel-code-generator vs JSON Schema 2020-12

- Unit: `w1-02-codegen-spike`
- Authority: approved plan §2 Codegen + Compatibility planner spike protocol (ADR-0009:38, ADR-0011:62), Ruling R8 (AsyncAPI `allOf`-overlay validation).
- Scope: verify `datamodel-code-generator` support for the project's JSON Schema 2020-12 patterns (envelope `oneOf`/`unevaluatedProperties` sealing, closed `additionalProperties:false` schemas, AsyncAPI `allOf`-overlay combination) before any typed-model work (W1-12) proceeds.
- Toolchain: `datamodel-code-generator==0.68.1`, `pydantic==2.13.4` (dev-only in this unit; moves to `packages/schemas` runtime in w1-12 per ADR-0011 SSOT split), `openapi-spec-validator==0.9.0`, `pyyaml==6.0.3`, `check-jsonschema==0.37.4` (pre-existing dev dep), `mypy==1.20.2` (pre-existing dev dep), Python 3.12.

All commands below were run from the repo/worktree root (`/Users/edmond104/Documents/GitHub/SAENA-RAPID-7.worktrees/w1-02-codegen-spike`) unless otherwise noted. All generated code and scratch schemas live under a `/private/tmp` scratchpad and are **not** committed; only this report and the dependency lock changes land in the repo, per the unit's touch-file allowlist.

## Overall verdict: **PASS**

P1–P4 all pass with zero disagreements in the round-trip parity matrix. P5 passes with one flag adjustment (`--use-annotated`, documented below). P6 (Ruling R8) confirms `unevaluatedProperties` sealing survives the AsyncAPI `allOf`-overlay merge pattern in both the raw JSON Schema and the generated pydantic model. **w1-12 typed-model work may proceed** using the recommended flag set below.

---

## P1 — 2020-12 input processed without errors/warnings

**Command:**
```
uv run datamodel-codegen \
  --input tests/contract/fixtures/envelope/draft-envelope.schema.json \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --schema-version 2020-12 \
  --use-annotated \
  --output <scratch>/envelope_v1_final.py
```

**Result:** exit code `0`. Only stderr output is a `FutureWarning` about the default formatter pipeline (black/isort becoming opt-in in a future `datamodel-code-generator` release) — not a schema-processing warning:

```
.../datamodel_code_generator/format.py:277: FutureWarning: The default external
formatters (black, isort) will become opt-in in a future version. ...
  warn_deprecated(
```

No errors or warnings related to `$schema: https://json-schema.org/draft/2020-12/schema`, `oneOf`, `unevaluatedProperties`, or `$ref` resolution against `$defs`. Passing `--schema-version 2020-12` explicitly (rather than relying on `auto` detection from `$schema`) produced identical output to `auto` in a side-by-side check — recorded here as the explicit, defensive form for the `just codegen` recipe.

**Verdict: PASS.**

---

## P2 — envelope `oneOf` 3-branch → per-branch models + union; sealing parity

**Input:** `tests/contract/fixtures/envelope/draft-envelope.schema.json` (real 2020-12 fixture, `oneOf` of `tenantContextEnvelope` / `systemContextEnvelope` / `aggregateContextEnvelope`, each `unevaluatedProperties: false`).

**Generated output (excerpt, class list):** `TenantContextEnvelope`, `SystemContextEnvelope`, `AggregateContextEnvelope` (one pydantic `BaseModel` per `oneOf` branch), plus a union root model:

```python
class SaenaEventEnvelopeV1Draft(
    RootModel[TenantContextEnvelope | SystemContextEnvelope | AggregateContextEnvelope]
):
    root: TenantContextEnvelope | SystemContextEnvelope | AggregateContextEnvelope = (
        Field(..., description="Implements ADR-0013 event envelope v1: ...")
    )
```

Each of the three branch models carries:
```python
model_config = ConfigDict(
    extra='forbid',
)
```
generated automatically from `unevaluatedProperties: false` — **no explicit `--extra-fields forbid` flag required** (see P4 note on why a blanket flag is wrong here).

**Behavioral test (`uv run python`, in-process against generated model):**
- Valid tenant instance parses: PASS.
- Unknown top-level field (`unexpected_field`) on `TenantContextEnvelope`: rejected with `pydantic.ValidationError` (`extra_forbidden`). PASS.
- Unknown top-level field on `SystemContextEnvelope`: rejected. PASS.
- `run_id` injected into `SystemContextEnvelope` (forbidden per ADR-0013 `not/anyOf` clause in the source schema): **rejected** by the generated model — not because `not`/`anyOf` was translated (codegen does not emit a `not` constraint; that JSON Schema keyword has no pydantic model-level equivalent and is a known codegen limitation), but because `run_id` is simply absent from `SystemContextEnvelope`'s declared fields, so `extra='forbid'` catches it as an unrecognized property. **The behavioral outcome required by P2 (sealing parity) is achieved, but by field-non-declaration + `extra='forbid'`, not by explicit `not`-translation.** This is the correct sealing *behavior*, documented per the ruling's "keyword support not required, behavior is the test."

**Verdict: PASS** (behavioral sealing parity confirmed for all 3 branches; keyword-level `not` translation is not supported and not required).

---

## P3 — closed schema (ADR-0014 TenantContext, 10 fields) → `extra='forbid'`

**Input:** scratch schema `<scratch>/schemas/tenant-context.schema.json` (not committed), mirroring the 10-field `TenantContext` list fixed in ADR-0014 (`tenant_id`, `display_name`, `isolation_profile`, `namespace`, `policy_version`, `engine_scope`, `status`, `retention_policy_ref`, `created_at`, `updated_at`), with `additionalProperties: false` and all 10 fields `required`.

**Command:**
```
uv run datamodel-codegen \
  --input <scratch>/schemas/tenant-context.schema.json \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --schema-version 2020-12 \
  --use-annotated \
  --output <scratch>/tenant_context_final.py
```

**Result:** exit `0`, same benign `FutureWarning` as P1. Generated model:
```python
class TenantcontextScratchAdr0014(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    tenant_id: Annotated[str, Field(pattern=r'^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$')]
    display_name: Annotated[str, Field(min_length=1)]
    isolation_profile: IsolationProfile
    namespace: str
    policy_version: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$')]
    engine_scope: Annotated[list[EngineScopeEnum], Field(min_length=1)]
    status: Status
    retention_policy_ref: Annotated[str, Field(min_length=1)]
    created_at: AwareDatetime
    updated_at: AwareDatetime
```

**Behavioral test:** valid 10-field instance parses; instance with an added `extra_field` is rejected with `ValidationError` (`extra_forbidden`).

**Verdict: PASS.**

---

## P4 — round-trip parity matrix (check-jsonschema vs pydantic)

Fixtures: all files under `tests/contract/fixtures/envelope/{valid,invalid}/*.json`, with `_`-prefixed metadata keys (`_expected_violation`, `_note`) stripped before both checks, per protocol. Ground truth = `check-jsonschema --schemafile tests/contract/fixtures/envelope/draft-envelope.schema.json <fixture>`. Comparison = `pydantic.TypeAdapter(SaenaEventEnvelopeV1Draft).validate_python(<fixture>)` against the P1/P2 generated union model.

### First pass — flag-tuning finding (documented, not a final-verdict failure)

The first matrix run used `--extra-fields forbid` (a blanket flag applied to **every** generated model regardless of whether the source sub-schema declared closedness). This produced **4 disagreements**: all 3 valid fixtures failed pydantic parsing, because the shared `Payload` sub-model (source: `commonFields.payload`, which is an **open** `type: object` with only `engine_id` declared and *no* `additionalProperties`/`unevaluatedProperties` keyword) was incorrectly sealed, rejecting legitimate extra payload fields like `patch_unit_id`, `worktree_commit`, `quality_gate_status`.

**Root cause:** `--extra-fields forbid` overrides the schema's own openness/closedness signal. It is the wrong flag for schemas that mix open and closed sub-objects (our envelope: closed at the branch/root level via `unevaluatedProperties: false`, open at the `payload` level by design).

**Fix:** drop `--extra-fields forbid` entirely. `datamodel-code-generator` correctly infers `extra='forbid'` per-model from `unevaluatedProperties: false` / `additionalProperties: false` **when present**, and leaves models without those keywords open (default pydantic `extra='ignore'`/no `model_config` override) — exactly matching the schema's semantics. This is the flag-set finding folded into the final recommendation below.

### Final pass — matrix with corrected flags (`--use-annotated`, no `--extra-fields`)

**Command (matrix driver script, scratch-only):** `uv run python <scratch>/output/p4_matrix_final.py` (runs `check-jsonschema` as subprocess ground truth + in-process pydantic validation against `envelope_v1_final.py`, generated with the command shown in P1).

| set | fixture | jsonschema | pydantic | agree |
|---|---|---|---|---|
| valid | aggregate-strategy-card-eligible-v1.json | True | True | True |
| valid | system-adapter-config-updated-v1.json | True | True | True |
| valid | tenant-patch-unit-completed-v1.json | True | True | True |
| invalid | aggregate-with-tenant-id.json | False | False | True |
| invalid | cohort-below-threshold.json | True | True | True |
| invalid | engine-id-google.json | False | False | True |
| invalid | system-with-run-id.json | False | False | True |

**disagreements: 0**

Notes:
- `cohort-below-threshold.json` passes **both** validators, as expected — this is the documented runtime-gate case (ADR-0013: `cohort_size < privacy_threshold` is a cross-field relational invariant not expressible in JSON Schema 2020-12; a W2A publish-side runtime gate is required). Both jsonschema and pydantic agreeing to *pass* this fixture is the **correct** parity outcome per protocol, not a gap.
- `engine-id-google.json` is correctly rejected by both — the closed `enum: ["chatgpt-search"]` on `payload.engine_id` is preserved through codegen (CLAUDE.md Engine scope v1 enforcement survives codegen).

**Verdict: PASS — 0 disagreements** in the final parity matrix.

---

## P5 — generated code passes mypy at repo settings

Repo `[tool.mypy]` (from `pyproject.toml`): `python_version = "3.12"`, `warn_unused_ignores = true`, `warn_redundant_casts = true`, `disallow_untyped_defs = true`, `files = ["packages"]`. Since `files` points at `packages/` and generated scratch code lives outside the repo, verification used a temp mypy config file (in scratch, not committed) that mirrors every non-path repo setting and overrides only `files` to point at the scratch-generated modules:

```ini
[mypy]
python_version = 3.12
warn_unused_ignores = True
warn_redundant_casts = True
disallow_untyped_defs = True
files = envelope_v1_final.py, tenant_context_final.py
```

**Command:** `uv run mypy --config-file <scratch>/output/mypy_scratch2.ini` (run with cwd = scratch output dir).

### First attempt — flag-tuning finding

Default `datamodel-codegen` output (no `--use-annotated`, no `--field-constraints`) uses call-style constrained types, e.g. `constr(pattern=...)`, `conint(ge=1)`, as inline type annotations:
```python
root: constr(pattern=r'^[0-9a-f]{32}$') = Field(...)
```
mypy rejects these as invalid type annotations:
```
tenant_context.py:31: error: Invalid type comment or annotation  [valid-type]
tenant_context.py:31: note: Suggestion: use constr[...] instead of constr(...)
envelope_v1_noextraflag.py:37: error: Type expected within [...]  [misc]
envelope_v1_noextraflag.py:37: error: Invalid base class "RootModel"  [misc]
...
Found 23 errors in 2 files (checked 2 source files)
```
This is a well-known mypy/pydantic `conlist`/`constr`-style limitation (mypy cannot type-check the dynamic `constr(...)` factory call as a type expression).

**Fix:** add `--use-annotated` to the codegen invocation. This switches constrained-type fields to `typing.Annotated[str, Field(pattern=..., min_length=...)]` form, which mypy checks natively.

### Final attempt — with `--use-annotated`

**Command:** same as P1/P3 generation commands (both already include `--use-annotated`).

**Result:**
```
Success: no issues found in 2 source files
```

**Verdict: PASS** (with `--use-annotated` flag; without it, mypy fails — folded into final flag recommendation).

---

## P6 (Ruling R8) — AsyncAPI `allOf`-overlay combination

**Construction:** scratch schema `<scratch>/schemas/asyncapi-overlay-scratch.schema.json` (not committed) simulating the realistic AsyncAPI per-message overlay pattern: `allOf: [<tenantContextEnvelope-shaped base with unevaluatedProperties:false>, {properties: {event_type: {const: "patch.unit.completed.v1"}, context_type: {const: "tenant"}, payload: {type: object, properties: {...}, required: [...], additionalProperties: false}}}]`. This mirrors how a single AsyncAPI message schema narrows the general envelope to one concrete `event_type` + a closed payload shape.

**Two scratch instances** (not committed, `<scratch>/schemas/`):
- `overlay-instance-valid.json` — conforms to both `allOf` branches, no extra properties.
- `overlay-instance-invalid-extra-top-level.json` — identical, plus one extra top-level property `extra_top_level_field`.

**check-jsonschema results:**
```
=== VALID instance ===
ok -- validation done   (exit 0)

=== INVALID (extra top-level) instance ===
Schema validation errors were encountered.
  ...::$: Unevaluated properties are not allowed ('extra_top_level_field' was unexpected)
  (exit 1)
```
`unevaluatedProperties: false` on the base `allOf` branch correctly seals the **merged** schema (base + overlay), rejecting the extra top-level property even though it is not explicitly excluded by either individual `allOf` member in isolation — this is the exact 2020-12 `unevaluatedProperties`-across-`allOf` semantics the ruling asks to confirm.

**Codegen command:**
```
uv run datamodel-codegen \
  --input <scratch>/schemas/asyncapi-overlay-scratch.schema.json \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --schema-version 2020-12 \
  --use-annotated \
  --output <scratch>/output/overlay_final.py
```
Exit `0`, same benign `FutureWarning` only. The generator correctly **flattens the `allOf` merge into a single model** (`PatchUnitCompletedV1MessageSchemaScratchOverlay`), narrowing `event_type` to `Literal['patch.unit.completed.v1']` and `payload` to the closed nested `Payload` model (itself `extra='forbid'` from the nested `additionalProperties: false`), with the outer model also carrying `extra='forbid'` from the base branch's `unevaluatedProperties: false`.

**pydantic parity check (in-process):**
```
PASS: valid overlay instance parses under pydantic
PASS: invalid overlay instance rejected by pydantic (extra='forbid' honors unevaluatedProperties across allOf)
```

**Verdict: PASS.** `unevaluatedProperties` sealing is preserved correctly across the `allOf` overlay combination in both the raw JSON Schema validator and the codegen'd pydantic model; check-jsonschema and pydantic agree on both scratch instances.

---

## Final flag-set recommendation for the `just codegen` recipe

```
datamodel-codegen \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --schema-version 2020-12 \
  --use-annotated
```

Rationale per flag:
- `--input-file-type jsonschema` — matches ADR-0011's `packages/contracts` JSON Schema-first SSOT; do not use `auto` in the recipe (explicit is safer for CI reproducibility even though `auto` detection was verified to match in this spike).
- `--output-model-type pydantic_v2.BaseModel` — matches the target runtime type (pydantic v2), per protocol and the eventual `packages/schemas` runtime move in w1-12.
- `--target-python-version 3.12` — matches repo `requires-python = ">=3.12,<3.13"`.
- `--schema-version 2020-12` — explicit dialect pin; do not rely on `auto`-detection from `$schema` alone for the CI recipe (defensive against a future fixture omitting or mistyping `$schema`).
- `--use-annotated` — **required for P5 (mypy) to pass**; switches constrained types from mypy-incompatible `constr(...)`/`conint(...)` call-style annotations to `Annotated[T, Field(...)]` form.
- **Do NOT add `--extra-fields forbid`** — this is a blanket override that breaks P4 parity for any schema with open (non-`unevaluatedProperties`/`additionalProperties`-sealed) sub-objects, such as this project's `payload` field. Let the tool infer `extra='forbid'` per-model from the schema's own `unevaluatedProperties: false` / `additionalProperties: false` keywords — this is both the more correct and the higher-fidelity behavior, confirmed by the P2/P3/P4/P6 results above.

Two flag-tuning findings surfaced and were resolved during this spike (both folded into the recommendation above, not blockers): the `--extra-fields forbid` over-sealing problem (P4) and the `constr(...)`-style mypy incompatibility (P5, fixed by `--use-annotated`).

## Dependency versions locked (this unit)

Added to `[dependency-groups].dev` in `pyproject.toml` (dev-only in W1; `pydantic` moves to `packages/schemas` runtime dependencies in w1-12 per ADR-0011 SSOT split — `packages/contracts` is hand-edited SSOT, `packages/schemas` is codegen-output-only):

| package | constraint | locked |
|---|---|---|
| datamodel-code-generator | `>=0.26,<1` | 0.68.1 |
| pydantic | `>=2,<3` | 2.13.4 |
| openapi-spec-validator | `>=0.7,<1` | 0.9.0 |
| pyyaml | `>=6,<7` | 6.0.3 |

`uv lock` and `uv sync --locked` both ran clean; `uv run pytest -q` remains green at 38/38 after the dependency addition (no regressions from the new dev deps).

## Files touched in the repo by this unit

- `pyproject.toml` — added the 4 dev dependencies above to `[dependency-groups].dev`.
- `uv.lock` — relocked to include the new dependencies and their transitive closures.
- `tools/validation/codegen-spike-report.md` — this report.

No files under `packages/contracts`, `packages/schemas`, `events/`, or any other protected path were touched. All scratch schemas, generated model code, and test-harness scripts used to produce the evidence above live under `/private/tmp/claude-501/.../scratchpad/codegen-spike/` and were never committed.
