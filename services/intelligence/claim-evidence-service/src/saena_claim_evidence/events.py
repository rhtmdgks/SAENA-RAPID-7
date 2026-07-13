"""`build_claim_evidence_versioned_event` — `claim.evidence.versioned.v1` emission.

Builds via `saena_domain.events.EnvelopeFactory.build_tenant_envelope`
(the single-authority envelope constructor — see that module's own
docstring "why no ad hoc envelope dict"); this module never hand-builds an
envelope dict that merely looks valid. `claim.evidence.versioned.v1` is a
CONFIRMED v1 AsyncAPI channel (w4-10,
`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml` — producer
`claim-evidence-service`, `context_type: tenant`), so
`EnvelopeFactory.build_tenant_envelope` dual-validates the built envelope
(jsonschema + pydantic) against `saena_schemas.event.
claim_evidence_versioned_v1.ClaimEvidenceVersionedV1Payload` byte-for-byte
regardless of whether that event_type also happens to be registered in
`saena_domain.events.factory.EVENT_PAYLOAD_MODELS` (it is not, as of this
patch unit — that dict binds only 6 of the 12 CONFIRMED v1 channels to an
extra, redundant pydantic-model check; the AsyncAPI channel's own
`payload.$ref` is what the jsonschema half of `EnvelopeFactory`'s dual
validation always enforces, for every channel, with or without that extra
binding).

`payload` fields are exactly `{project_id, ledger_version, claim_count,
evidence_count, provenance_ref}` per the task instruction — this module
never adds a `tenant_id`/`run_id` key to `payload` (ADR-0024(e)-1, enforced
independently by `EnvelopeFactory` itself via
`PayloadDuplicatesEnvelopeFieldError`).
"""

from __future__ import annotations

from typing import Any

from saena_domain.events import EnvelopeFactory

from saena_claim_evidence.ledger import ClaimEvidenceLedgerState

EVENT_TYPE = "claim.evidence.versioned.v1"
PRODUCER = "claim-evidence-service"


def summarize_ledger(ledger_state: ClaimEvidenceLedgerState) -> tuple[int, int]:
    """Return `(claim_count, evidence_count)` — the number of DISTINCT
    `claim_id`/`evidence_id` values with at least one entry in
    `ledger_state` (append-only replay/no-op entries never double-count;
    counting distinct ids, not raw entry rows, is what makes this figure
    stable across a claim's later re-evaluated "republish" entries — see
    `ledger.py`'s "fail-closed-on-mutation" section)."""
    claim_ids = {entry.claim.claim_id for entry in ledger_state if entry.claim is not None}
    evidence_ids = {
        entry.evidence.evidence_id for entry in ledger_state if entry.evidence is not None
    }
    return len(claim_ids), len(evidence_ids)


def build_claim_evidence_versioned_event(
    *,
    tenant_id: str,
    run_id: str,
    project_id: str,
    ledger_version: str,
    ledger_state: ClaimEvidenceLedgerState,
    provenance_ref: str,
    idempotency_key: str,
    occurred_at: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Build a `claim.evidence.versioned.v1` tenant-context envelope for one
    ledger version snapshot.

    `provenance_ref` MUST already be a `sha256:<hex>` string (typically
    `hashing.compute_ledger_entry_hash` over the caller's own chosen
    "what does this ledger_version anchor" material — this module does not
    itself decide what that material is, since "ledger version" spans
    however many claim/evidence entries the caller considers part of one
    published version; it only validates the SHAPE via
    `EnvelopeFactory`'s dual jsonschema+pydantic check, which rejects a
    non-conforming `provenance_ref` with `EnvelopeValidationError`).

    `claim_count`/`evidence_count` are derived from `ledger_state` via
    `summarize_ledger` — never caller-supplied, so they can never drift
    from the ledger they describe.
    """
    claim_count, evidence_count = summarize_ledger(ledger_state)
    payload = {
        "project_id": project_id,
        "ledger_version": ledger_version,
        "claim_count": claim_count,
        "evidence_count": evidence_count,
        "provenance_ref": provenance_ref,
    }
    return EnvelopeFactory.build_tenant_envelope(
        producer=PRODUCER,
        event_type=EVENT_TYPE,
        tenant_id=tenant_id,
        run_id=run_id,
        idempotency_key=idempotency_key,
        payload=payload,
        occurred_at=occurred_at,
        trace_id=trace_id,
    )


__all__ = ["EVENT_TYPE", "PRODUCER", "build_claim_evidence_versioned_event", "summarize_ledger"]
