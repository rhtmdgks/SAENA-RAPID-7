"""`DeploymentConfirmedConsumer` — consumes `deployment.confirmed.v1` (w5-12).

Consumes an ALREADY-DESERIALIZED envelope + payload (dict shapes, mirroring
how `saena_domain.events.factory.EnvelopeFactory` represents an envelope),
validates the payload against the generated `saena_schemas` model, converts
it into a `saena_domain.measurement.confirmation.DeploymentConfirmation`, and
runs it through `validate_confirmation` (w5-03) — the domain's sole
fail-closed gate to a trusted clock start.

## Envelope tenant_id is the SOLE authority (ADR-0014)

Per ADR-0014 ("이벤트 페이로드에 envelope tenant_id와 별도로 tenant 식별
필드를 중복 정의하지 않는다"), the envelope's `tenant_id` member is the only
trusted tenant identity for this event. If the payload ALSO carries a
`tenant_id` key, that is a violation — this consumer rejects it outright
(`TenantDuplicationError`) rather than silently ignoring the duplicate or
silently preferring one value over the other. This mirrors
`saena_domain.events.factory._reject_duplicate_identifiers`, re-derived here
because this boundary validates payloads it receives off the wire directly
(not necessarily built via `EnvelopeFactory`).

## Tenant-scoped registration lookup neutralizes the w5-03 `cross_tenant_replay`
## oracle (w5-18 finding — see `ports.RegistrationLookup` for the full
## rationale)

This consumer NEVER looks up a registration by `registration_hash` alone. It
always calls `RegistrationLookup.lookup(envelope_tenant_id,
registration_hash)` — the compound key structurally prevents a caller from
presenting another tenant's real registration hash and observing a
distinguishing response. A miss (whether "wrong tenant" or "never existed")
degrades identically into `RejectionReason.UNKNOWN_REGISTRATION` further
downstream inside `validate_confirmation` — this consumer does not add its
own distinguishing branch on top.

## server_received_at authority

`server_received_at` is read from the caller-supplied `TransportMetadata`
(never from the payload) and passed to `validate_confirmation` as the
trusted timestamp anchor — the payload's own `confirmed_at` is treated
purely as an untrusted claim, exactly as `confirmation.py` documents.

## Outcomes

- `Accepted` → `ConfirmationStore.put_confirmation(...)` is called, THEN
  `WorkflowSignal.signal_confirmed(...)` is called directly (ADR-0003: a
  direct signal, never a bus event from this boundary).
- `Duplicate` → no-op: neither the store nor the workflow signal is invoked
  again (idempotent replay, no double-signal).
- `Rejected` → an audit-shaped `RejectionRecord` is returned. It carries
  ONLY the typed `reason_code` + `idempotency_key` + `experiment_id`
  references — the raw incoming payload is NEVER echoed into it (mirrors
  `saena_domain.measurement.confirmation`'s own non-leaking rejection
  discipline).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError
from saena_domain.measurement.confirmation import (
    Accepted,
    ConfirmationVerdict,
    DeploymentConfirmation,
    Duplicate,
    PriorState,
    Rejected,
    RejectionReason,
    TrustVerifier,
    validate_confirmation,
)
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    ConfirmationStore,
)
from saena_schemas.event.deployment_confirmed_v1 import DeploymentConfirmedV1Payload

from .errors import PayloadValidationError, TenantDuplicationError
from .ports import RegistrationLookup, WorkflowSignal

#: Payload-level fields ADR-0014 forbids duplicating from the envelope.
_ENVELOPE_IDENTIFIER_FIELDS = ("tenant_id", "run_id")


@dataclass(frozen=True, slots=True)
class TransportMetadata:
    """Transport-layer facts supplied by the bus consumer, NEVER the payload.

    `server_received_at` is the trusted timestamp authority `confirmation.py`
    requires — it must originate from the consuming process/broker
    observing the message, never from anything inside the payload bytes.
    """

    server_received_at: datetime
    envelope_tenant_id: str
    envelope_run_id: str


class RejectionRecord(BaseModel):
    """Audit-shaped rejection — NEVER echoes the raw incoming payload.

    Carries only the typed reason and the two identifying references the
    domain's own `Rejected` verdict carries (`idempotency_key`,
    `experiment_id`) — mirrors
    `saena_domain.measurement.confirmation.Rejected`'s non-leaking shape one
    layer up, at the service-boundary audit-trail level.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: RejectionReason
    idempotency_key: str
    experiment_id: str


ConsumeOutcome = Accepted | Duplicate | RejectionRecord


class DeploymentConfirmedConsumer:
    """Consumes `deployment.confirmed.v1` envelope+payload dicts.

    All collaborators are injected — no real bus/DB. `prior_state` is a
    mutable mapping the caller owns (mirrors
    `saena_domain.measurement.confirmation.PriorState`); this consumer reads
    it via `validate_confirmation` but does not itself decide persistence
    beyond calling `ConfirmationStore.put_confirmation` on an `Accepted`
    verdict — the caller is responsible for keeping `prior_state` and the
    `ConfirmationStore` consistent (e.g. by rebuilding `prior_state` from the
    store, or wiring both to the same backing store in production).
    """

    def __init__(
        self,
        *,
        registration_lookup: RegistrationLookup,
        confirmation_store: ConfirmationStore,
        workflow_signal: WorkflowSignal,
        trust_verifier: TrustVerifier | None,
        allowed_skew_seconds: int = 0,
    ) -> None:
        self._registration_lookup = registration_lookup
        self._confirmation_store = confirmation_store
        self._workflow_signal = workflow_signal
        self._trust_verifier = trust_verifier
        self._allowed_skew_seconds = allowed_skew_seconds

    def consume(
        self,
        payload: dict[str, object],
        *,
        transport: TransportMetadata,
        prior_state: PriorState,
    ) -> ConsumeOutcome:
        """Validate + apply one `deployment.confirmed.v1` message.

        Raises `PayloadValidationError` (or `TenantDuplicationError`, a
        subclass) for a structurally-invalid payload — a message that fails
        even to parse against the contract never reaches
        `validate_confirmation` at all. A structurally-valid payload that
        fails a DOMAIN guard (identity/backdate/replay/etc.) instead returns
        a `RejectionRecord` (not a raised exception) — mirrors
        `validate_confirmation`'s own fail-closed-but-typed-return
        discipline rather than exceptions for expected-shape rejections.
        """
        self._reject_payload_tenant_duplication(payload)
        parsed = self._parse_payload(payload)
        confirmation = self._to_domain_confirmation(parsed, transport)

        registration_view = self._registration_lookup.lookup(
            transport.envelope_tenant_id, parsed.registration_ref.registration_canonical_hash.root
        )
        if registration_view is None:
            # Compound-key miss: identical outcome whether the hash belongs
            # to another tenant or does not exist at all (w5-18 oracle
            # neutralization — see ports.RegistrationLookup docstring). We
            # hand validate_confirmation a registration_view whose identity
            # fields cannot possibly match the confirmation's, so it falls
            # through to its own tenant/identity guards and rejects with a
            # reason that is already non-leaking by construction.
            return RejectionRecord(
                reason_code=RejectionReason.UNKNOWN_REGISTRATION,
                idempotency_key=confirmation.idempotency_key,
                experiment_id=confirmation.experiment_id,
            )

        verdict: ConfirmationVerdict = validate_confirmation(
            confirmation,
            registration_view,
            transport.server_received_at,
            self._trust_verifier,
            prior_state,
            allowed_skew_seconds=self._allowed_skew_seconds,
        )

        if isinstance(verdict, Accepted):
            return self._apply_accepted(verdict)
        if isinstance(verdict, Duplicate):
            # Idempotent no-op: neither store nor workflow signal fire again.
            return verdict
        return self._to_rejection_record(verdict)

    def _apply_accepted(self, accepted: Accepted) -> Accepted:
        record = ConfirmationRecord(
            tenant_id=accepted.confirmation.tenant_id,
            confirmation_key=accepted.confirmation.idempotency_key,
            measurement_kind="deployment_confirmation",
            payload=accepted.confirmation.model_dump(mode="json"),
        )
        self._confirmation_store.put_confirmation(
            accepted.confirmation.tenant_id, accepted.confirmation.idempotency_key, record
        )
        # ADR-0003: direct signal, never a bus event, from this boundary.
        self._workflow_signal.signal_confirmed(
            accepted.confirmation.tenant_id,
            accepted.confirmation.experiment_id,
            accepted.server_received_at.isoformat(),
        )
        return accepted

    @staticmethod
    def _to_rejection_record(rejected: Rejected) -> RejectionRecord:
        return RejectionRecord(
            reason_code=rejected.reason_code,
            idempotency_key=rejected.idempotency_key,
            experiment_id=rejected.experiment_id,
        )

    @staticmethod
    def _reject_payload_tenant_duplication(payload: dict[str, object]) -> None:
        """ADR-0014: envelope `tenant_id` is the sole authority; a payload
        carrying its own `tenant_id`/`run_id` is rejected outright."""
        for field_name in _ENVELOPE_IDENTIFIER_FIELDS:
            if field_name in payload:
                raise TenantDuplicationError(
                    f"payload duplicates envelope-authoritative field {field_name!r} "
                    "(ADR-0014: no payload tenant/run duplication)",
                    context={"field": field_name},
                )

    @staticmethod
    def _parse_payload(payload: dict[str, object]) -> DeploymentConfirmedV1Payload:
        try:
            return DeploymentConfirmedV1Payload.model_validate(payload)
        except ValidationError as exc:
            raise PayloadValidationError(
                "deployment.confirmed.v1 payload failed contract validation",
                context={"errors": exc.error_count()},
            ) from exc

    @staticmethod
    def _to_domain_confirmation(
        parsed: DeploymentConfirmedV1Payload, transport: TransportMetadata
    ) -> DeploymentConfirmation:
        confirmer = parsed.confirmer
        return DeploymentConfirmation(
            experiment_id=parsed.registration_ref.experiment_id,
            tenant_id=transport.envelope_tenant_id,
            run_id=transport.envelope_run_id,
            project=parsed.deployment_target.kind,
            site=parsed.deployment_target.identifier,
            registration_canonical_hash=parsed.registration_ref.registration_canonical_hash.root,
            deployment_target=parsed.deployment_target.identifier,
            deployed_commit_sha=parsed.deployed_commit_sha.root
            if parsed.deployed_commit_sha is not None
            else None,
            artifact_hash=parsed.artifact_hash.root if parsed.artifact_hash is not None else None,
            confirmed_at=_parse_timestamp(parsed.confirmed_at.root),
            idempotency_key=parsed.deployment_id,
            confirmer_identity=confirmer.identity,
            confirmer_signature=confirmer.signature_ref.root
            if confirmer.signature_ref is not None
            else confirmer.method,
        )


def _parse_timestamp(value: str) -> datetime:
    # contract pattern guarantees a Z-suffixed RFC3339 string.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = [
    "ConsumeOutcome",
    "DeploymentConfirmedConsumer",
    "RejectionRecord",
    "TransportMetadata",
]
