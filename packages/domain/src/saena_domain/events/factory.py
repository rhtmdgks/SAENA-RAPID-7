"""EnvelopeFactory — builds and dual-validates SAENA event envelopes.

Implements ADR-0013 (event envelope v1, 9 common fields + `context_type`
discriminator + rev.2 `payload` as 10th structural member) and the ADR-0024
deviations relevant to event payloads: (d) `pattern` changes are
open-class-breaking (enforced upstream in the contract, not here), (e)
event payload must not re-project envelope-level `tenant_id`/`run_id`.

Three builder entry points, one per `context_type` branch (ADR-0013
§Current decision discriminator table):

- `build_tenant_envelope`   — `context_type: tenant`, requires `tenant_id`
  + `run_id` (ADR-0013 rev.2 ④: tenant branch `run_id` stays required).
- `build_system_envelope`   — `context_type: system`, `tenant_id`/`run_id`
  structurally absent (never accepted as kwargs).
- `build_aggregate_envelope` — `context_type: aggregate`, `tenant_id`/`run_id`
  structurally absent; requires the 5 k-anonymity/lineage fields.

Every builder performs, in order:
  1. Envelope-vs-payload duplicate-identifier check (ADR-0024(e)-1).
  2. Field synthesis: `event_id` (UUIDv7), `occurred_at` (RFC3339 UTC,
     Z-suffix only), `trace_id` (accept caller-provided 32-hex lowercase, else
     generate), `schema_version` format check (3-part semver, no
     prerelease/build).
  3. Topic/producer discipline (ADR-0013 event_type == topic name 1:1):
     `event_type` must be a declared AsyncAPI channel address, and
     `producer` must match that channel's expected producer.
  4. `engine_id` guard (ADR-0013 closed enum: `chatgpt-search` only).
  5. Known-event-type payload binding: if `event_type` is one of the 6
     CONFIRMED payload-bearing events, `payload` is parsed with that event's
     generated pydantic model (no duplicate DTOs) in addition to the generic
     envelope-level payload container check.
  6. Dual validation: jsonschema (2020-12, local Registry) AND pydantic
     (generated `SaenaEventEnvelopeV1`) both must pass, or
     `EnvelopeValidationError` is raised with every collected message.

Catalog gap note (`build_system_envelope`): the CONFIRMED v1 AsyncAPI catalog
(`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`, 12 channels)
contains zero `context_type: system` channels as of this patch unit — only
11 tenant + 1 aggregate. `docs/architecture/api-event-contracts.md:30` and
ADR-0013's own appendix example 2 (`adapter.config.updated.v1`) document the
SystemContext shape illustratively, but that topic has not landed in the
catalog a producer/topic check can consult. Every builder therefore accepts
an optional `asyncapi_path` override (test-only escape hatch, defaults to the
real catalog) so `build_system_envelope`'s happy-path behavior can be proven
against a small fixture catalog without asserting a not-yet-CONFIRMED topic
into the production AsyncAPI file. See `tests/unit/domain_events/fixtures/`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1
from saena_schemas.envelope.event_envelope_v1.engine_id import Schema as EngineIdSchema
from saena_schemas.event.patch_unit_completed_v1 import PatchUnitCompletedV1Payload
from saena_schemas.event.plan_contract_approved_v1 import PlanContractApprovedV1Payload
from saena_schemas.event.plan_contract_proposed_v1 import PlanContractProposedV1Payload
from saena_schemas.event.quality_gate_result_v1 import QualityGatePassedFailedV1Payload
from saena_schemas.event.repo_intaken_v1 import RepoIntakenV1Payload
from saena_schemas.event.site_inventory_completed_v1 import SiteInventoryCompletedV1Payload

from saena_domain.events._topics import load_topic_catalog
from saena_domain.events._uuid7 import generate_uuid7
from saena_domain.events._validation import jsonschema_errors
from saena_domain.events.errors import (
    EngineNotPermittedError,
    EnvelopeValidationError,
    PayloadDuplicatesEnvelopeFieldError,
    ProducerMismatchError,
    TopicMismatchError,
)

# The 6 CONFIRMED event payload contracts (approved plan §2 "event/ 6종";
# tests/contract/validate/test_event_payloads.py `_CONTRACTS` is the parallel
# contract-test-side enumeration of this same set). `quality.gate.passed.v1`
# and `quality.gate.failed.v1` share one payload schema/model (R4
# channel-layer split — see quality-gate-result.schema.json $comment) so both
# event_type strings map to the same model class here.
EVENT_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "repo.intaken.v1": RepoIntakenV1Payload,
    "site.inventory.completed.v1": SiteInventoryCompletedV1Payload,
    "plan.contract.proposed.v1": PlanContractProposedV1Payload,
    "plan.contract.approved.v1": PlanContractApprovedV1Payload,
    "patch.unit.completed.v1": PatchUnitCompletedV1Payload,
    "quality.gate.passed.v1": QualityGatePassedFailedV1Payload,
    "quality.gate.failed.v1": QualityGatePassedFailedV1Payload,
}

_PERMITTED_ENGINE_IDS = frozenset(item.value for item in EngineIdSchema)

_SCHEMA_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_OCCURRED_AT_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)

_ENVELOPE_IDENTIFIER_FIELDS = ("tenant_id", "run_id")

DEFAULT_SCHEMA_VERSION = "1.0.0"


def _reject_duplicate_identifiers(payload: dict[str, Any]) -> None:
    """ADR-0024(e)-1: payload must not re-project tenant_id/run_id."""
    for field_name in _ENVELOPE_IDENTIFIER_FIELDS:
        if field_name in payload:
            raise PayloadDuplicatesEnvelopeFieldError(field_name)


def _check_schema_version(schema_version: str) -> None:
    if not _SCHEMA_VERSION_PATTERN.match(schema_version):
        msg = (
            f"schema_version {schema_version!r} must be pure MAJOR.MINOR.PATCH "
            "(no prerelease/build metadata — ADR-0013 rev.2 ③)"
        )
        raise ValueError(msg)


def _check_or_generate_trace_id(trace_id: str | None) -> str:
    if trace_id is None:
        return generate_uuid7().replace("-", "")[:32]
    if not _TRACE_ID_PATTERN.match(trace_id):
        msg = f"trace_id {trace_id!r} must be 32 lowercase-hex characters (W3C trace context)"
        raise ValueError(msg)
    return trace_id


def _check_occurred_at(occurred_at: str) -> None:
    if not _OCCURRED_AT_PATTERN.match(occurred_at):
        msg = (
            f"occurred_at {occurred_at!r} must be RFC3339 UTC with a Z suffix "
            "only (ADR-0013 rev.2 ② — +00:00 offset form is rejected)"
        )
        raise ValueError(msg)


def _check_topic_and_producer(
    event_type: str, producer: str, *, asyncapi_path: Path | None = None
) -> None:
    catalog = load_topic_catalog() if asyncapi_path is None else load_topic_catalog(asyncapi_path)
    info = catalog.get(event_type)
    if info is None:
        raise TopicMismatchError(event_type)
    if info.expected_producer != producer:
        raise ProducerMismatchError(event_type, producer, info.expected_producer)


def _check_engine_id(payload: dict[str, Any]) -> None:
    engine_id = payload.get("engine_id")
    if engine_id is None:
        return
    if engine_id not in _PERMITTED_ENGINE_IDS:
        raise EngineNotPermittedError(str(engine_id))


def _check_known_payload_model(event_type: str, payload: dict[str, Any]) -> None:
    """If `event_type` has a bound generated payload model, parse `payload`
    with it (no duplicate DTOs — reuses `saena_schemas.event.*` as-is).
    """
    model = EVENT_PAYLOAD_MODELS.get(event_type)
    if model is None:
        return
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        msg = f"payload does not conform to the {event_type!r} payload contract: {exc}"
        raise EnvelopeValidationError([msg]) from exc


def _dual_validate(envelope: dict[str, Any]) -> None:
    messages = jsonschema_errors(envelope)
    try:
        SaenaEventEnvelopeV1.model_validate(envelope)
    except ValidationError as exc:
        messages.append(f"pydantic: {exc}")
    if messages:
        raise EnvelopeValidationError(messages)


def _base_fields(
    *,
    producer: str,
    event_type: str,
    occurred_at: str | None,
    trace_id: str | None,
    idempotency_key: str,
    schema_version: str,
    asyncapi_path: Path | None = None,
) -> dict[str, Any]:
    if occurred_at is None:
        # UTC millisecond-precision Z-suffixed timestamp, matching the
        # contract's timestamp_utc pattern (fractional seconds optional).
        import datetime as _dt

        occurred_at = (
            _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    _check_occurred_at(occurred_at)
    _check_schema_version(schema_version)
    resolved_trace_id = _check_or_generate_trace_id(trace_id)
    _check_topic_and_producer(event_type, producer, asyncapi_path=asyncapi_path)

    return {
        "event_id": generate_uuid7(),
        "schema_version": schema_version,
        "producer": producer,
        "occurred_at": occurred_at,
        "trace_id": resolved_trace_id,
        "idempotency_key": idempotency_key,
        "event_type": event_type,
    }


class EnvelopeFactory:
    """Builds envelopes for the three ADR-0013 `context_type` branches.

    `idempotency_key` is always caller-supplied (task spec: "caller-supplied
    required — document per-event key rules from contract-catalog"). This
    module does not invent per-event key derivation rules beyond that
    contract — callers own composing the key per
    `docs/architecture/contract-catalog.md`'s idempotency guidance for their
    specific event (e.g. `patch.unit.completed.v1` fixtures in ADR-0013's
    appendix use `f"{tenant_id}:{run_id}:{patch_unit_id}"`); the factory only
    enforces that a non-empty string is present.
    """

    @staticmethod
    def build_tenant_envelope(
        *,
        producer: str,
        event_type: str,
        tenant_id: str,
        run_id: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        trace_id: str | None = None,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        asyncapi_path: Path | None = None,
    ) -> dict[str, Any]:
        resolved_payload = dict(payload) if payload is not None else {}
        _reject_duplicate_identifiers(resolved_payload)
        _check_engine_id(resolved_payload)
        _check_known_payload_model(event_type, resolved_payload)

        envelope: dict[str, Any] = {
            "context_type": "tenant",
            "tenant_id": tenant_id,
            "run_id": run_id,
            "payload": resolved_payload,
            **_base_fields(
                producer=producer,
                event_type=event_type,
                occurred_at=occurred_at,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                schema_version=schema_version,
                asyncapi_path=asyncapi_path,
            ),
        }
        _dual_validate(envelope)
        return envelope

    @staticmethod
    def build_system_envelope(
        *,
        producer: str,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        trace_id: str | None = None,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        asyncapi_path: Path | None = None,
    ) -> dict[str, Any]:
        resolved_payload = dict(payload) if payload is not None else {}
        _reject_duplicate_identifiers(resolved_payload)
        _check_engine_id(resolved_payload)
        _check_known_payload_model(event_type, resolved_payload)

        envelope: dict[str, Any] = {
            "context_type": "system",
            "payload": resolved_payload,
            **_base_fields(
                producer=producer,
                event_type=event_type,
                occurred_at=occurred_at,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                schema_version=schema_version,
                asyncapi_path=asyncapi_path,
            ),
        }
        _dual_validate(envelope)
        return envelope

    @staticmethod
    def build_aggregate_envelope(
        *,
        producer: str,
        event_type: str,
        aggregate_scope_id: str,
        cohort_size: int,
        privacy_threshold: int,
        de_identification_status: str,
        lineage_audit_ref: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        trace_id: str | None = None,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        asyncapi_path: Path | None = None,
    ) -> dict[str, Any]:
        resolved_payload = dict(payload) if payload is not None else {}
        _reject_duplicate_identifiers(resolved_payload)
        _check_engine_id(resolved_payload)
        _check_known_payload_model(event_type, resolved_payload)

        envelope: dict[str, Any] = {
            "context_type": "aggregate",
            "aggregate_scope_id": aggregate_scope_id,
            "cohort_size": cohort_size,
            "privacy_threshold": privacy_threshold,
            "de_identification_status": de_identification_status,
            "lineage_audit_ref": lineage_audit_ref,
            "payload": resolved_payload,
            **_base_fields(
                producer=producer,
                event_type=event_type,
                occurred_at=occurred_at,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                schema_version=schema_version,
                asyncapi_path=asyncapi_path,
            ),
        }
        _dual_validate(envelope)
        return envelope
