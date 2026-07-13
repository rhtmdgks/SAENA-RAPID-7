"""ADR-0003 approval-authority boundary: `ApprovalDecision` verification.

This module is the ONE place `saena_agent_runner` decides "may this contract
execute at all, and which of its patch units." Every check here is
fail-closed: any missing field, mismatch, or non-`approved` decision raises
one of `saena_agent_runner.errors`' `ApprovalRequiredError` subclasses BEFORE
`runner.py` ever creates a worktree or touches a file.

ADR-0003 authority path: "Policy Gate 선행 검증·기록 ... 승인 시에만
plan-contract-service가 Temporal signal을 직접 발송 ... Temporal workflow의
자체 재검증은 defense-in-depth." This package sits downstream of that whole
path (it is handed an `ApprovalDecision` the orchestrator/Temporal layer has
already deemed authoritative) — `verify_approval` is this package's OWN
defense-in-depth re-check, not the primary authority itself. It never trusts
"an approval object was handed to me" alone; it re-derives the approved
patch-unit set from the object's OWN content every time.

Reuses the generated `saena_schemas.domain.approval_decision_v1.ApprovalDecision`
pydantic model (same codegen-is-SSOT rationale as `contract.py`).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_schemas.domain.approval_decision_v1 import ApprovalDecision, Decision

from saena_agent_runner.contract import ChangeplanActionContract
from saena_agent_runner.errors import (
    ApprovalContractHashMismatchError,
    ApprovalIdentityMismatchError,
    ApprovalMissingError,
    ApprovalRejectedError,
    ApprovalSignatureInvalidError,
    ContractValidationError,
)


def parse_approval_decision(raw: dict[str, Any] | None) -> ApprovalDecision:
    """Validate `raw` against the closed, signed `ApprovalDecision` schema.

    `raw=None` (no approval object supplied at all) raises
    `ApprovalMissingError` directly — the single most common fail-closed
    case (an execution attempt with no approval evidence whatsoever) gets
    its own specific error rather than falling through to a generic
    validation failure.

    Any other structural violation (missing required field, wrong shape,
    a `signature`/`signature_algorithm` that fails the schema's own
    `minLength: 1`) raises `ApprovalSignatureInvalidError` if the violation
    is under `signature`/`signature_algorithm`, otherwise the generic
    `ContractValidationError` — either way, a forged/malformed
    `ApprovalDecision` never reaches `verify_approval` as a validated object.
    """
    if raw is None:
        raise ApprovalMissingError(
            "no ApprovalDecision supplied — execution requires a valid approved "
            "contract_hash + ApprovalDecision (ADR-0003)",
            context={},
        )
    try:
        return ApprovalDecision.model_validate(raw)
    except ValidationError as exc:
        offending_fields = {".".join(str(p) for p in err["loc"]) for err in exc.errors()}
        if offending_fields & {"signature", "signature_algorithm"}:
            raise ApprovalSignatureInvalidError(
                f"ApprovalDecision.signature/signature_algorithm failed validation: {exc}",
                context={"offending_fields": sorted(offending_fields)},
            ) from exc
        raise ContractValidationError(
            f"ApprovalDecision failed schema validation: {exc}", context={}
        ) from exc


def verify_approval(
    *,
    contract: ChangeplanActionContract,
    approval: ApprovalDecision,
    expected_contract_hash: str,
    expected_tenant_id: str,
    expected_run_id: str,
) -> frozenset[str]:
    """Verify `approval` authorizes executing `contract`, fail-closed.

    Returns the frozenset of patch_unit_ids individually marked `approved`
    in `approval.patch_unit_decisions` — the ONLY patch units `runner.py`
    may subsequently execute. Raises (never returns a partial/empty
    "maybe") on:

    - `approval.contract_hash != expected_contract_hash` — the unapproved
      /forged/mismatched-contract-hash execution attempt this whole module
      exists to block (`ApprovalContractHashMismatchError`).
    - `approval.tenant_id`/`.run_id` not matching the executing
      `JobContext` identity (`ApprovalIdentityMismatchError`) — a
      structurally-valid approval for a DIFFERENT run/tenant must never
      authorize THIS run.
    - `approval.decision != "approved"` (`ApprovalRejectedError`) — an
      explicit B-department rejection, or any decision value other than
      the literal `"approved"`.

    Does NOT check `contract.tenant_id`/`.run_id` against `expected_*`
    itself — the caller (`runner.py`) is expected to have already bound
    `contract` to the executing `JobContext` before calling this; this
    function's job is specifically the `ApprovalDecision` cross-check.
    """
    if approval.contract_hash.root != expected_contract_hash:
        raise ApprovalContractHashMismatchError(
            "ApprovalDecision.contract_hash does not match the contract being "
            "executed — refusing execution (unapproved/forged/mismatched "
            "contract_hash, ADR-0003)",
            context={
                "expected_contract_hash": expected_contract_hash,
                "approval_contract_hash": approval.contract_hash.root,
            },
        )
    if approval.tenant_id.root != expected_tenant_id or approval.run_id.root != expected_run_id:
        raise ApprovalIdentityMismatchError(
            "ApprovalDecision.tenant_id/run_id does not match the executing "
            "JobContext — refusing a replayed/cross-run approval instance",
            context={
                "expected_tenant_id": expected_tenant_id,
                "expected_run_id": expected_run_id,
                "approval_tenant_id": approval.tenant_id.root,
                "approval_run_id": approval.run_id.root,
            },
        )
    if approval.decision != Decision.approved:
        raise ApprovalRejectedError(
            f"ApprovalDecision.decision is {approval.decision.value!r}, not "
            "'approved' — refusing execution",
            context={"decision": approval.decision.value},
        )
    return frozenset(
        unit_decision.patch_unit_id
        for unit_decision in approval.patch_unit_decisions
        if unit_decision.decision == Decision.approved
    )


__all__ = ["ApprovalDecision", "parse_approval_decision", "verify_approval"]
