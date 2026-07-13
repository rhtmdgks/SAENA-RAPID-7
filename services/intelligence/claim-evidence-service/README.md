# claim-evidence-service

| Field | Value |
|---|---|
| Service name | `claim-evidence-service` |
| Bounded context | Claim–evidence ledger |
| Primary responsibility | claim extraction, evidence ledger, freshness/legal status |
| Owned data | claim/evidence graph |
| Consumed contracts | source-of-truth; site assets |
| Published events | claim.evidence.versioned.v1 (CONFIRMED v1 AsyncAPI channel, w4-10) |
| Consumed events | site.inventory.completed.v1; demand.graph.versioned.v1; entity.graph.versioned.v1 (PROPOSED — 2026-07-12 감사: upstream 선언과 정합화; not yet consumed by this patch unit) |
| Upstream dependencies | entity-resolution-service; site-discovery-service |
| Downstream consumers | intervention-generator-service; quality-eval-service |
| Security boundary | unsupported claim = release-blocking; no fabricated evidence |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `intelligence` |
| Implementation status | **PARTIAL — W4 minimal (w4-04)** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §3.1, §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/wave4-plan.md` (w4-04 exclusive paths, QEEG split to w4-11)
- `docs/architecture/contract-catalog.md` rows `ExtractedClaim`/`EvidenceRecord`

## Status

PARTIAL (w4-04) — `saena_claim_evidence` implements the atomic
claim + evidence ledger's **write-model / command side only** (append
claims, append evidence, evaluate fail-closed publishability, emit
`claim.evidence.versioned.v1`):

- `evaluation.py` — `evaluate_claim_publishability`: a claim is
  publishable ONLY if at least one linked `EvidenceRecord` is present,
  fresh (`EvidenceFreshnessPolicy`, checked against an injected `now` —
  no wall-clock reads anywhere in this package), and not administratively
  `EvidenceLinkStatus.BLOCKED`. Absent/stale/blocked evidence -> not
  publishable, always with a caller-readable `blocking_reasons` tuple.
- `ledger.py` — `append_claim`/`append_evidence`/`set_evidence_link_status`:
  an append-only, tenant/project-scoped hash chain (REUSES
  `saena_domain.audit.canonical` for `content_hash` — no second hashing
  rule) covering both `ExtractedClaim` and `EvidenceRecord` entries,
  re-evaluating and recording each affected claim's publishability on
  every mutation (fail-closed-on-mutation, never silently stale).
- `store.py` — `InMemoryClaimEvidenceStore`: tenant-scoped store;
  cross-tenant put/get is rejected (`CrossTenantLedgerAccessError`,
  default-DENY), mirroring `saena_site_discovery.store`'s gating
  discipline. Reference in-memory adapter for this unit's own tests only.
- `events.py` — `build_claim_evidence_versioned_event`: builds the
  `claim.evidence.versioned.v1` tenant-context envelope via
  `saena_domain.events.EnvelopeFactory` (single-authority construction,
  dual jsonschema+pydantic validated) with `claim_count`/`evidence_count`
  always derived from the ledger itself, never caller-supplied.

**Engine = chatgpt-search only** (no Google/Gemini anywhere in this
package — nothing here even references an `engine_id`, since claim/
evidence ledger entries are engine-neutral facts about the customer's own
site content).

NOT in this patch unit's scope (a SEPARATE patch unit, w4-11 — "Do NOT
build QEEG" is an explicit task instruction, not an oversight): the
Question-Entity-Evidence Graph read-only projection/replay module. Also
NOT in scope: claim extraction from raw site content (an upstream concern
this package assumes already happened — it ingests already-extracted
`ExtractedClaim`/`EvidenceRecord` records), a real SQL persistence
adapter, consuming `site.inventory.completed.v1`/`demand.graph.
versioned.v1`/`entity.graph.versioned.v1`, a k3s Deployment manifest or
Dockerfile, and any outcome/DiD/causal/lift computation (Wave 5, forbidden
in W4 per `docs/architecture/wave4-plan.md`). This package is also NOT YET
a root `uv` workspace member (see `pyproject.toml`'s own NOTE) —
registering it is the Integrator's job at merge time.

## OPEN decisions (isolated, not invented)

- **Freshness threshold** (`EvidenceFreshnessPolicy.max_age_seconds`): no
  spec/ADR fixes a numeric staleness bound for evidence. This package
  never hardcodes one as a bare literal default — every caller supplies an
  explicit `EvidenceFreshnessPolicy`; `ledger.DEFAULT_FRESHNESS_POLICY`
  (90 days) exists only as a usable, clearly-not-hidden fallback for
  callers that have not yet been given a production value, and is
  documented as non-normative.
- **Claim extraction method**: out of scope — this package assumes
  `ExtractedClaim`/`EvidenceRecord` records already exist when handed to
  it; how they are produced (LLM extraction, manual authoring, etc.) is a
  separate, unbuilt upstream concern.
