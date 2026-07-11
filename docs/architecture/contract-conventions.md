# Contract conventions

## Purpose

Practical, implementer-facing summary of ADR-0011 (schema conventions),
ADR-0012 (compatibility policy), ADR-0013 (event envelope v1), ADR-0014
(tenant propagation), and ADR-0015 (canonical error model). This is a
condensation for people writing contracts and consuming code in W1+; it
is **not authoritative** — where this document and an ADR disagree, the
ADR wins, and this document should be corrected to match.

## Scope

In: naming rules, directory layout, `$id` scheme, versioning/tagging,
compatibility rules, the envelope field table, tenant propagation
summary, and the error model summary — as accepted in ADR-0011/0012/
0013/0014/0015. Out: the actual schema files (`packages/contracts/`,
W1), harness implementation detail (see `tests/contract/README.md`).

## Naming

- **File/field naming**: `snake_case` for all JSON Schema property names
  and file basenames (`event-envelope.schema.json`, not
  `EventEnvelope.schema.json`; `tenant_id`, not `tenantId`).
- **Contract/event naming**: `<domain>.<entity>.<action>.v<major>` for
  event types and AsyncAPI topics — the two must always be identical,
  1:1, no separate management (ADR-0013). Pattern:
  `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}\.v[0-9]+$`
  (e.g. `patch.unit.completed.v1`).
- **Error codes**: `saena.<category>.<reason>` (ADR-0015), e.g.
  `saena.policy_denied.gate_unavailable`.
- **Tag scheme**: `contracts/{name}/vX.Y.Z`, one tag per contract
  release, full semver (ADR-0011).

## Directory layout (ADR-0011)

**Directory-per-major** — a major version boundary is a directory
boundary, so multiple majors can be served concurrently (required by
ADR-0012's compatibility model):

```
packages/contracts/json-schema/<category>/<name>/v<major>/<name>.schema.json
packages/contracts/openapi/<name>/v<major>/openapi.yaml
packages/contracts/asyncapi/<name>/v<major>/asyncapi.yaml
```

`category` ∈ `envelope | context | domain | event | common`.

`packages/contracts` is the **sole hand-edited SSOT**. `packages/schemas`
is codegen/derived output only — never hand-edit it (2026-07-12 SSOT
boundary decision, ADR-0011).

Test-side layout (harness, not contracts themselves) is documented in
`tests/contract/README.md`: `validate/` (schema self-validation +
instance validation), `compat/` (N-1 tag comparison), `fixtures/`
(per-contract instance fixtures).

## `$id` scheme (ADR-0011)

```
https://schemas.the-saena.ai/{category}/{name}/v{major}/{name}.schema.json
```

- `schemas.the-saena.ai` is a **non-resolvable identifier** — a
  namespace, not a live HTTP endpoint. Never write code that fetches
  `$id` over the network.
- `$id` path maps 1:1 to the filesystem path — you can derive one from
  the other without consulting a registry.
- Every schema file's **first key must be `"$schema"`**, value
  `https://json-schema.org/draft/2020-12/schema` — CI lint enforces
  this ordering.

Error `type` URIs follow the same non-resolvable pattern (ADR-0015):
`https://schemas.the-saena.ai/errors/<category>/<code>`.

## Dialect and validation toolchain (ADR-0011)

| Contract family | Dialect | Validator |
|---|---|---|
| JSON Schema (signed contracts, domain, envelope, common) | **2020-12** | check-jsonschema / jsonschema (Python) |
| Synchronous API | **OpenAPI 3.1** | openapi-spec-validator (Python) |
| Async events | **AsyncAPI 3.0** | `@asyncapi/cli` (Node — the **sole** Node exception, isolated to contract-lint use per ADR-0009) |

2020-12 was chosen specifically because it aligns with OpenAPI 3.1 (`$ref`
sharing without translation) and because `unevaluatedProperties` — required
to seal the envelope's `oneOf` context branches — does not exist in
draft-07.

**codegen**: schema-first, generated types only, no hand-written types.
Concrete tool (datamodel-code-generator) is a W1 entry spike, not yet
adopted.

## Versioning and compatibility (ADR-0012)

Three contract classes, three rules:

| Class | Policy | Rule |
|---|---|---|
| **Signed contracts** (ChangePlan, ApprovalDecision, etc. — closed, `additionalProperties: false`) | closed | **Any** change is major — field add/remove, type change, enum change, no exceptions. |
| **Event payload** (open, progressive evolution) | open | Optional field add = **minor**. Required field add, type narrowing, semantic change = **major**. |
| **Envelope** (frozen) | frozen | **Any** change requires a **new ADR** — ADR-0013 is the v1 authority; field add/remove/meaning-change needs an ADR-0013 revision or a successor ADR. |

**Enum rule (event payloads)**: both **narrowing and widening are
major.** This is a corrected position — an early draft treated widening
as minor under a "tolerant-read" assumption; the corrected rule is that
widening is forward-incompatible for old consumers (they cannot handle a
value they've never seen), so it is major regardless of direction.

**Tolerant-read is still required, separately**: independent of the
major-bump rule above, consumers must handle an unrecognized enum value
without erroring (defense-in-depth for the rollout window where old and
new consumers coexist). This is not a loophole that makes widening
minor — it is a second, independent safety net. See `tests/contract/README.md`
§"Tolerant-read test obligation" for the harness-level test requirement.

**Backward-compat primary check**: "does the new schema still accept
N-1 instances" is the practical breaking-change signal. The compat
harness (single implementation, testing/QA-owned; judgment rules and
`registry.json`/git-tag issuance are Contracts Steward-owned per
ADR-0011/0012) checks this plus a structural diff for forbidden changes
made without a major bump. `oasdiff` is a secondary, OpenAPI-only
detector — never primary.

## Envelope v1 fields (ADR-0013)

9 common fields (k3s §4.1's original 8 are frozen; `event_type` is the
9th field, a deliberate, ADR-owned deviation from the k3s spec text):

| # | Field | Type/format | Notes |
|---|---|---|---|
| 1 | `event_id` | UUIDv7 | sortable |
| 2 | `tenant_id` | string | required/forbidden per context, see below |
| 3 | `run_id` | string | required/forbidden per context, see below |
| 4 | `schema_version` | semver string | ADR-0012 compatibility target |
| 5 | `producer` | string | publishing service identifier |
| 6 | `occurred_at` | RFC3339 UTC timestamp | |
| 7 | `trace_id` | 32-hex string | W3C trace context format |
| 8 | `idempotency_key` | string | dedup key, at-least-once delivery |
| 9 | `event_type` | string, pattern above | identical to AsyncAPI topic name |

**`context_type` discriminator**: `tenant \| system \| aggregate`,
structured as `oneOf` (3 branches) + `unevaluatedProperties: false`
(requires 2020-12).

| context_type | `tenant_id` | `run_id` | Additional required fields |
|---|---|---|---|
| **tenant** | required | required for run-scoped events (non-run nullability: **OPEN**) | — |
| **system** | **property itself forbidden** | **property itself forbidden** | — |
| **aggregate** | **property itself forbidden** | **property itself forbidden** | `aggregate_scope_id` (string), `cohort_size` (integer ≥1), `privacy_threshold` (integer ≥1), `de_identification_status` (enum: `k_anonymized`\|`suppressed`\|`pending_review`), `lineage_audit_ref` (opaque audit-ledger hash, audit-role-only viewing) |

"Forbidden" for system/aggregate means the property cannot appear in the
schema at all — not "optional and absent."

**k-anonymity gate is NOT schema-expressible**: `cohort_size ≥
privacy_threshold` is a cross-field relational constraint JSON Schema
2020-12 has no operator for. The schema only enforces each field's type
and lower bound; the relation must be enforced by a **runtime gate at
publish time** (W2A). A permanent regression fixture
(`tests/contract/fixtures/envelope/invalid/cohort-below-threshold.json`)
documents this gap deliberately — it is schema-valid on purpose.

**`engine_id`**: required in observation/citation/experiment event
payloads. **Closed enum, v1 single value**: `["chatgpt-search"]`. Any
other value (Google AI Overviews, AI Mode, Gemini, ...) is rejected at
the schema level — the contract-level enforcement of CLAUDE.md's "Engine
scope v1: ChatGPT Search only" principle. Adding an engine requires
re-approval + a new ADR + a major version bump (consistent with the
enum-widening-is-major rule above).

## Tenant propagation (ADR-0014)

- `tenant_id` is an **immutable** DNS-safe slug:
  `^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$` (max 32 chars, sized to fit
  under the `saena-tenant-<id>` ≤63-char namespace convention). No
  rename — a changed identity requires a new `tenant_id` and a
  migration procedure.
- Three propagation paths:
  - **Events**: envelope `tenant_id` (ADR-0013) is the sole authority —
    never duplicate a tenant field inside an event payload.
  - **Sync HTTP**: header `X-Saena-Tenant-Id`, cross-checked against pod
    env `SAENA_TENANT_ID`. Mismatch → 403 **and** an audit event
    (recording which values disagreed). Silent-ignore or 200-on-mismatch
    code paths are forbidden.
  - **Observability**: OTel baggage + span attribute `saena.tenant_id`.
- `TenantContext` field list is fixed at W0 (schema file itself is W1
  P0 #1): `tenant_id`, `display_name`, `isolation_profile`
  (`internal-k3s`\|`saas-shared`), `namespace` (derived from
  `tenant_id`, never independently supplied), `policy_version`,
  `engine_scope` (array, v1 = `["chatgpt-search"]`), `status`
  (`active`\|`suspended`\|`terminating`), `retention_policy_ref`,
  `created_at`, `updated_at`.

## Canonical error model (ADR-0015)

**Sync API errors**: RFC 9457 `application/problem+json`, standard
fields (`type`, `title`, `status`, `detail`, `instance`) plus SAENA
extensions:

| Extension field | Rule |
|---|---|
| `error_code` | `saena.<category>.<reason>` |
| `retryable` | boolean |
| `trace_id` | same 32-hex W3C format as envelope `trace_id` — the 3-way correlation key |
| `tenant_id` | optional, when applicable |
| `run_id` | optional, when applicable |

**9 error categories** (default `retryable`):

| Category | Example code | Retryable | Notes |
|---|---|---|---|
| `validation` | `saena.validation.schema_mismatch` | no | |
| `auth` | `saena.auth.token_invalid` | no | |
| `policy_denied` | `saena.policy_denied.<reason>` | no | includes `gate_unavailable` — gate failure is **fail-closed**, never fail-open |
| `conflict` | `saena.conflict.version_stale` | no | |
| `not_found` | `saena.not_found.resource_missing` | no | |
| `rate_limited` | `saena.rate_limited.quota_exceeded` | **yes** | must include `Retry-After` header |
| `upstream_engine` | `saena.upstream_engine.timeout` | **yes** | apply backoff |
| `unavailable` | `saena.unavailable.service_down` | **yes** | |
| `internal` | `saena.internal.unexpected` | no (default) | unknown cause defaults to non-retryable, safe side |

**No separate error-event topics.** Failures ride the existing domain
event (payload carries error detail via `$ref` to
`common/error-detail/v1/error-detail.schema.json` — minimal 3 fields:
`error_code`, `retryable`, `summary`). Stack traces and raw
content/secrets are forbidden in error payloads and in `AuditEvent`
error records (which capture only `error_code` + `trace_id`).

**DLQ naming** (documented now, wired in W2C): `<topic>.dlq`, e.g.
`patch.unit.completed.v1.dlq`.

## Constraints (carried from source ADRs — see each ADR for full text)

- `"$schema"` must be the first key in every schema file, or CI lint
  fails.
- `$id` values are never used as live network fetch targets.
- `packages/schemas` is never hand-edited.
- Envelope structural changes always require a new/revised ADR — never
  a silent schema edit.
- Enum changes (either direction) without a major bump fail the compat
  harness.
- `policy_denied` never fails open, even on gate unavailability.
- `rate_limited` responses always carry `Retry-After`.

## Source specification references

- `docs/decisions/ADR-0011-contract-schema-conventions.md`
- `docs/decisions/ADR-0012-contract-compatibility-policy.md`
- `docs/decisions/ADR-0013-event-envelope-v1.md`
- `docs/decisions/ADR-0014-tenant-propagation.md`
- `docs/decisions/ADR-0015-canonical-error-model.md`
- `docs/architecture/contract-catalog.md`
- `docs/architecture/api-event-contracts.md`
- `docs/architecture/tenancy-model.md`
- `tests/contract/README.md` (harness design, T11)

## Status

CONFIRMED (summarizes accepted ADRs) / NOT IMPLEMENTED (no
`packages/contracts` schema files yet — W1).
