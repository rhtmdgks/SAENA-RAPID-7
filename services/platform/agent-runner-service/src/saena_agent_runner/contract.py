"""ChangePlan (Action Contract) parsing — structural validation only.

Reuses the generated `saena_schemas.domain.change_plan_v1.ChangeplanActionContract`
pydantic model (codegen from `packages/contracts/json-schema/domain/
change-plan/v1/change-plan.schema.json`, ADR-0011 codegen-is-SSOT) rather than
hand-declaring a second DTO for the same closed, signed contract. This module
adds no new fields — it only wraps `model_validate` with this package's own
`ContractValidationError`, and a small lookup helper
(`get_patch_unit`) the runner needs repeatedly.

`contract_hash` is deliberately NOT a field of `ChangeplanActionContract`
(self-reference avoidance, per the schema's own `$comment`) — every call site
in this package that needs to compare a contract against an
`ApprovalDecision.contract_hash` receives the hash as an explicit,
separately-supplied argument (`expected_contract_hash`), never derived from
the contract dict itself. Computing that hash (JCS canonicalization) is an
explicitly out-of-scope, pre-W2A ADR per the schema's own `$comment` — this
package is a CONSUMER of an already-computed hash, never its producer.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_schemas.domain.change_plan_v1 import ChangeplanActionContract, PatchUnit

from saena_agent_runner.errors import ContractValidationError, PatchUnitNotApprovedError


def parse_change_plan(raw: dict[str, Any]) -> ChangeplanActionContract:
    """Validate `raw` against the closed `ChangePlan` (Action Contract) schema.

    Raises `ContractValidationError` on any structural violation — a
    malformed/tampered contract is refused here, before any approval or
    execution logic ever sees it.
    """
    try:
        return ChangeplanActionContract.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(
            f"ChangePlan failed schema validation: {exc}", context={}
        ) from exc


def get_patch_unit(contract: ChangeplanActionContract, patch_unit_id: str) -> PatchUnit:
    """Return the named patch unit from `contract`.

    Raises `PatchUnitNotApprovedError` if `patch_unit_id` is not a member of
    `contract.patch_units` at all — this is the "execute ONLY the approved
    patch_units NAMED IN THE CONTRACT" boundary: a patch unit id that isn't
    even in the contract is refused with the same error family as one that
    is in the contract but was not individually approved (both are "not an
    executable patch unit for this run", from the caller's point of view).
    """
    for unit in contract.patch_units:
        if unit.id == patch_unit_id:
            return unit
    raise PatchUnitNotApprovedError(
        f"patch_unit_id {patch_unit_id!r} is not a member of this ChangePlan's "
        "patch_units — refusing to execute a unit the contract never named",
        context={"patch_unit_id": patch_unit_id},
    )


__all__ = ["ChangeplanActionContract", "PatchUnit", "get_patch_unit", "parse_change_plan"]
