"""Success/failure event payload builders for the 4 Wave 3 job-kind events.

Builds PAYLOAD dicts only (NOT full envelopes — envelope construction,
including topic/producer/`engine_id`-catalog checks, is
`saena_domain.events.EnvelopeFactory`'s job, a separate w2-02 patch unit;
callers here are expected to compose
`EnvelopeFactory.build_tenant_envelope(..., payload=build_xxx_payload(...))`
themselves, passing the relevant `JobKind`'s `producer_id`
(`saena_domain.execution.job_kind.profile_for(kind).producer_id`) as
`producer=`). Reuses the SAME generated pydantic payload models
`saena_domain.events.factory.EVENT_PAYLOAD_MODELS` already binds
(`saena_schemas.event.*`) to validate every builder's output before
returning it — no duplicate DTOs (ADR-0011 codegen-is-SSOT discipline).

Covers exactly the 4 event families this patch unit's mission names:

- `repo.intaken.v1`                                 (`JobKind.REPOSITORY_INTAKE`)
- `patch.unit.completed.v1`                         (`JobKind.AGENT_RUNNER`)
- `quality.gate.passed.v1` / `quality.gate.failed.v1` (`JobKind.QUALITY_EVAL`)
- `site.inventory.completed.v1`                     (`JobKind.SITE_DISCOVERY`)

**Deliberately left for a later unit**: `JobKind.CHATGPT_OBSERVER`'s event
(`observation.captured.v1`) has no builder here. It is outside this patch
unit's named event list AND, unlike the 4 above, REQUIRES
`payload.engine_id` (ADR-0013 observation/citation/experiment family rule,
`x-saena-engine-id-required: true` in the AsyncAPI catalog) — this module's
`saena_domain.execution.engine.guard_engine_id` is available for that later
unit to reuse, but wiring up `observation.captured.v1`'s own payload builder
is not part of this deliverable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError
from saena_schemas.event.patch_unit_completed_v1 import PatchUnitCompletedV1Payload
from saena_schemas.event.quality_gate_result_v1 import QualityGatePassedFailedV1Payload
from saena_schemas.event.repo_intaken_v1 import RepoIntakenV1Payload
from saena_schemas.event.site_inventory_completed_v1 import SiteInventoryCompletedV1Payload

from saena_domain.execution.errors import EventPayloadValidationError
from saena_domain.execution.job_error import JobError


def _validate(event_type: str, model: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        instance = model.model_validate(payload)
    except ValidationError as exc:
        raise EventPayloadValidationError(
            f"built payload does not conform to the {event_type!r} payload contract: {exc}",
            context={"event_type": event_type},
        ) from exc
    return instance.model_dump(mode="json", exclude_none=True)


def build_repo_intaken_payload(
    *,
    repo_commit: str,
    content_hash: str,
    snapshot_uri: str | None = None,
) -> dict[str, Any]:
    """`repo.intaken.v1` payload (`JobKind.REPOSITORY_INTAKE`, producer
    `repository-intake-service`). Never carries source content or file
    listings (schema `$comment`) — only the commit SHA / content hash /
    opaque snapshot URI."""
    payload: dict[str, Any] = {"repo_commit": repo_commit, "content_hash": content_hash}
    if snapshot_uri is not None:
        payload["snapshot_uri"] = snapshot_uri
    return _validate("repo.intaken.v1", RepoIntakenV1Payload, payload)


def build_patch_unit_completed_payload(
    *,
    patch_unit_id: str,
    worktree_commit: str,
    manifest_uri: str | None = None,
    changed_files: Sequence[str] | None = None,
    quality_gate_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """`patch.unit.completed.v1` payload (`JobKind.AGENT_RUNNER`, producer
    `agent-runner-service`). `changed_files` carries paths only, never
    content (schema `$comment`)."""
    payload: dict[str, Any] = {
        "patch_unit_id": patch_unit_id,
        "worktree_commit": worktree_commit,
    }
    if manifest_uri is not None:
        payload["manifest_uri"] = manifest_uri
    if changed_files is not None:
        payload["changed_files"] = list(changed_files)
    if quality_gate_ids is not None:
        payload["quality_gate_ids"] = list(quality_gate_ids)
    return _validate("patch.unit.completed.v1", PatchUnitCompletedV1Payload, payload)


def _build_quality_gate_result_payload(
    *,
    patch_unit_id: str,
    gate_id: str,
    failures: Sequence[JobError] | None,
    report_uri: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"patch_unit_id": patch_unit_id, "gate_id": gate_id}
    if failures is not None:
        payload["failures"] = [failure.to_error_detail_payload() for failure in failures]
    if report_uri is not None:
        payload["report_uri"] = report_uri
    return _validate("quality.gate.passed|failed.v1", QualityGatePassedFailedV1Payload, payload)


def build_quality_gate_passed_payload(
    *,
    patch_unit_id: str,
    gate_id: str,
    report_uri: str | None = None,
) -> dict[str, Any]:
    """`quality.gate.passed.v1` payload (`JobKind.QUALITY_EVAL`, producer
    `quality-eval-service`). The AsyncAPI channel-layer overlay (R4) forbids
    a `failures` key on this channel — this builder enforces that same rule
    at the call-shape level by never accepting a `failures` argument at
    all."""
    return _build_quality_gate_result_payload(
        patch_unit_id=patch_unit_id, gate_id=gate_id, failures=None, report_uri=report_uri
    )


def build_quality_gate_failed_payload(
    *,
    patch_unit_id: str,
    gate_id: str,
    failures: Sequence[JobError],
    report_uri: str | None = None,
) -> dict[str, Any]:
    """`quality.gate.failed.v1` payload (`JobKind.QUALITY_EVAL`, producer
    `quality-eval-service`). The AsyncAPI channel-layer overlay (R4)
    requires >=1 `failures` item on this channel — enforced here directly
    (`EventPayloadValidationError` on an empty/missing sequence) rather than
    deferred entirely to schema/channel validation."""
    if not failures:
        raise EventPayloadValidationError(
            "quality.gate.failed.v1 requires at least one JobError in `failures` "
            "(AsyncAPI channel-layer overlay R4)",
            context={"event_type": "quality.gate.failed.v1"},
        )
    return _build_quality_gate_result_payload(
        patch_unit_id=patch_unit_id,
        gate_id=gate_id,
        failures=failures,
        report_uri=report_uri,
    )


def build_site_inventory_completed_payload(
    *,
    site_id: str,
    inventory_version: str,
) -> dict[str, Any]:
    """`site.inventory.completed.v1` payload (`JobKind.SITE_DISCOVERY`,
    producer `site-discovery-service`)."""
    payload: dict[str, Any] = {"site_id": site_id, "inventory_version": inventory_version}
    return _validate("site.inventory.completed.v1", SiteInventoryCompletedV1Payload, payload)


__all__ = [
    "build_patch_unit_completed_payload",
    "build_quality_gate_failed_payload",
    "build_quality_gate_passed_payload",
    "build_repo_intaken_payload",
    "build_site_inventory_completed_payload",
]
