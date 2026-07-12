"""Contract-name -> (saena_schemas pydantic model class, jsonschema
validator) registry for test_model_parity.py.

Not itself a test module. Centralizes the mapping so test_model_parity.py
stays a thin driver. Model classes are imported from `saena_schemas`
(packages/schemas, codegen-only per packages/schemas/README.md -- w1-12
scope, consumed read-only here).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import saena_schemas.context.actor_context_v1 as actor_context_v1
import saena_schemas.context.project_context_v1 as project_context_v1
import saena_schemas.context.run_context_experiment_v1 as run_context_experiment_v1
import saena_schemas.context.run_context_lifecycle_v1 as run_context_lifecycle_v1
import saena_schemas.context.site_context_v1 as site_context_v1
import saena_schemas.context.tenant_context_v1 as tenant_context_v1
import saena_schemas.context.workspace_context_v1 as workspace_context_v1
import saena_schemas.domain.approval_decision_v1 as approval_decision_v1
import saena_schemas.domain.audit_event_v1 as audit_event_v1
import saena_schemas.domain.change_plan_v1 as change_plan_v1
import saena_schemas.domain.patch_artifact_v1 as patch_artifact_v1
import saena_schemas.domain.source_snapshot_v1 as source_snapshot_v1
import saena_schemas.domain.verification_result_v1 as verification_result_v1
import saena_schemas.event.patch_unit_completed_v1 as patch_unit_completed_v1
import saena_schemas.event.plan_contract_approved_v1 as plan_contract_approved_v1
import saena_schemas.event.plan_contract_proposed_v1 as plan_contract_proposed_v1
import saena_schemas.event.quality_gate_result_v1 as quality_gate_result_v1
import saena_schemas.event.repo_intaken_v1 as repo_intaken_v1
import saena_schemas.event.site_inventory_completed_v1 as site_inventory_completed_v1
from _support import (
    CONTRACTS_JSON_SCHEMA_DIR,
    ENGINE_ID_SCHEMA,
    ERROR_DETAIL_SCHEMA,
    IDENTIFIERS_SCHEMA,
    build_validator,
)
from jsonschema import Draft202012Validator
from pydantic import BaseModel

CONTEXT_DIR = CONTRACTS_JSON_SCHEMA_DIR / "context"
DOMAIN_DIR = CONTRACTS_JSON_SCHEMA_DIR / "domain"
EVENT_DIR = CONTRACTS_JSON_SCHEMA_DIR / "event"


class ContractBinding(NamedTuple):
    schema_path: Path
    extra_resource_paths: tuple[Path, ...]
    model_cls: type[BaseModel]
    fixture_dir: Path
    # Invalid-fixture file names KNOWN to diverge between the schema
    # validator and the pydantic model verdict, because the codegen
    # output (packages/schemas, w1-12 scope) does not translate JSON
    # Schema allOf/if-then conditionals into pydantic-enforced
    # validators -- pydantic accepts what the conditional would reject.
    # The schema verdict remains authoritative (ADR-0011 SSOT); these are
    # documented codegen-coverage gaps, not silently-passing assertions.
    # Gap fixtures (schema-valid by design, e.g. namespace-mismatch) are
    # tracked separately by the per-contract validate/ modules and are
    # NOT part of this set (both sides already agree they're valid).
    known_conditional_gaps: frozenset[str] = frozenset()

    def build_validator(self) -> Draft202012Validator:
        return build_validator(
            self.schema_path, extra_resource_paths=list(self.extra_resource_paths)
        )


FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

BINDINGS: dict[str, ContractBinding] = {
    "tenant-context": ContractBinding(
        schema_path=CONTEXT_DIR / "tenant-context" / "v1" / "tenant-context.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA),
        model_cls=tenant_context_v1.TenantContext,
        fixture_dir=FIXTURES_ROOT / "tenant-context",
    ),
    "actor-context": ContractBinding(
        schema_path=CONTEXT_DIR / "actor-context" / "v1" / "actor-context.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=actor_context_v1.ActorContext,
        fixture_dir=FIXTURES_ROOT / "actor-context",
        # ActorContext's human=>tenant_id allOf/if-then is not represented
        # in the generated pydantic model (tenant_id stays optional there)
        # -- schema rejects, pydantic accepts.
        known_conditional_gaps=frozenset({"human-without-tenant-id.json"}),
    ),
    "workspace-context": ContractBinding(
        schema_path=CONTEXT_DIR / "workspace-context" / "v1" / "workspace-context.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=workspace_context_v1.WorkspaceContext,
        fixture_dir=FIXTURES_ROOT / "workspace-context",
    ),
    "project-context": ContractBinding(
        schema_path=CONTEXT_DIR / "project-context" / "v1" / "project-context.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=project_context_v1.ProjectContext,
        fixture_dir=FIXTURES_ROOT / "project-context",
    ),
    "site-context": ContractBinding(
        schema_path=CONTEXT_DIR / "site-context" / "v1" / "site-context.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=site_context_v1.SiteContext,
        fixture_dir=FIXTURES_ROOT / "site-context",
    ),
    "run-context-lifecycle": ContractBinding(
        schema_path=CONTEXT_DIR
        / "run-context-lifecycle"
        / "v1"
        / "run-context-lifecycle.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=run_context_lifecycle_v1.RuncontextLifecycle,
        fixture_dir=FIXTURES_ROOT / "run-context-lifecycle",
        # human-approval-required-wrong-type.json: pydantic's default
        # (lax) bool validation coerces the string "yes" to True (pydantic
        # v2 lax-mode str->bool coercion for recognized truthy tokens);
        # the JSON Schema's `type: boolean` strictly rejects a string.
        # Verified empirically (this unit's model-parity test authoring):
        # BaseModel(x: bool).model_validate({"x": "yes"}) succeeds.
        known_conditional_gaps=frozenset({"human-approval-required-wrong-type.json"}),
    ),
    "run-context-experiment": ContractBinding(
        schema_path=CONTEXT_DIR
        / "run-context-experiment"
        / "v1"
        / "run-context-experiment.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA),
        model_cls=run_context_experiment_v1.RuncontextExperiment,
        fixture_dir=FIXTURES_ROOT / "run-context-experiment",
        # duplicate-locales.json: the schema's `locales` array declares
        # `uniqueItems: true` (w1-06 critic SHOULD-FIX 3), but the
        # generated `Locale` RootModel (packages/schemas codegen output)
        # carries no equivalent duplicate-rejection validator -- the
        # current datamodel-code-generator flag set (justfile codegen
        # recipe) does not translate uniqueItems into a pydantic
        # constraint. Verified empirically during this unit's authoring.
        known_conditional_gaps=frozenset({"duplicate-locales.json"}),
    ),
    "change-plan": ContractBinding(
        schema_path=DOMAIN_DIR / "change-plan" / "v1" / "change-plan.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA),
        model_cls=change_plan_v1.ChangeplanActionContract,
        fixture_dir=FIXTURES_ROOT / "change-plan",
        # customer_id-legacy.json: schema rejects on TWO independent
        # grounds (extra property 'customer_id' under additionalProperties
        # :false, AND missing required 'tenant_id'). The generated pydantic
        # model also has extra="forbid" AND a required tenant_id field, so
        # it independently rejects too -- NOT a gap. Left out of this set
        # deliberately; verified by the parity test itself (both sides
        # reject).
    ),
    "approval-decision": ContractBinding(
        schema_path=DOMAIN_DIR / "approval-decision" / "v1" / "approval-decision.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=approval_decision_v1.ApprovalDecision,
        fixture_dir=FIXTURES_ROOT / "approval-decision",
    ),
    "source-snapshot": ContractBinding(
        schema_path=DOMAIN_DIR / "source-snapshot" / "v1" / "source-snapshot.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=source_snapshot_v1.SourceSnapshot,
        fixture_dir=FIXTURES_ROOT / "source-snapshot",
    ),
    "patch-artifact": ContractBinding(
        schema_path=DOMAIN_DIR / "patch-artifact" / "v1" / "patch-artifact.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=patch_artifact_v1.PatchArtifact,
        fixture_dir=FIXTURES_ROOT / "patch-artifact",
    ),
    "verification-result": ContractBinding(
        schema_path=DOMAIN_DIR / "verification-result" / "v1" / "verification-result.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA, ERROR_DETAIL_SCHEMA),
        model_cls=verification_result_v1.VerificationResult,
        fixture_dir=FIXTURES_ROOT / "verification-result",
        # R4 bidirectional if/then (failed=>failures required,
        # passed=>failures forbidden) is not represented in the generated
        # model (failures stays a plain optional field there regardless
        # of status) -- schema rejects both violation fixtures, pydantic
        # accepts both.
        known_conditional_gaps=frozenset(
            {"failed-without-failures.json", "passed-with-failures.json"}
        ),
    ),
    "audit-event": ContractBinding(
        schema_path=DOMAIN_DIR / "audit-event" / "v1" / "audit-event.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=audit_event_v1.AuditEvent,
        fixture_dir=FIXTURES_ROOT / "audit-event",
        # R9-1 scope discriminator (tenant=>tenant_id required,
        # system=>tenant_id/run_id forbidden) is not represented in the
        # generated model (tenant_id/run_id both stay plain optional
        # fields regardless of scope) -- schema rejects both violation
        # fixtures, pydantic accepts both.
        known_conditional_gaps=frozenset(
            {"system-scope-with-tenant-id.json", "tenant-scope-without-tenant-id.json"}
        ),
    ),
}

# Event payload contracts (fixtures live under fixtures/event-payloads/<name>/).
EVENT_PAYLOAD_BINDINGS: dict[str, ContractBinding] = {
    "patch-unit-completed": ContractBinding(
        schema_path=EVENT_DIR / "patch-unit-completed" / "v1" / "patch-unit-completed.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=patch_unit_completed_v1.PatchUnitCompletedV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "patch-unit-completed",
    ),
    "plan-contract-approved": ContractBinding(
        schema_path=EVENT_DIR
        / "plan-contract-approved"
        / "v1"
        / "plan-contract-approved.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=plan_contract_approved_v1.PlanContractApprovedV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "plan-contract-approved",
    ),
    "plan-contract-proposed": ContractBinding(
        schema_path=EVENT_DIR
        / "plan-contract-proposed"
        / "v1"
        / "plan-contract-proposed.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=plan_contract_proposed_v1.PlanContractProposedV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "plan-contract-proposed",
    ),
    "quality-gate-result": ContractBinding(
        schema_path=EVENT_DIR / "quality-gate-result" / "v1" / "quality-gate-result.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA, ERROR_DETAIL_SCHEMA),
        model_cls=quality_gate_result_v1.QualityGatePassedFailedV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "quality-gate-result",
    ),
    "repo-intaken": ContractBinding(
        schema_path=EVENT_DIR / "repo-intaken" / "v1" / "repo-intaken.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=repo_intaken_v1.RepoIntakenV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "repo-intaken",
    ),
    "site-inventory-completed": ContractBinding(
        schema_path=EVENT_DIR
        / "site-inventory-completed"
        / "v1"
        / "site-inventory-completed.schema.json",
        extra_resource_paths=(IDENTIFIERS_SCHEMA,),
        model_cls=site_inventory_completed_v1.SiteInventoryCompletedV1Payload,
        fixture_dir=FIXTURES_ROOT / "event-payloads" / "site-inventory-completed",
    ),
}
