"""Approved-contract fact extraction — mission item 1, "... + the approved
contract".

`saena_quality_eval` does not own `ChangePlan`/Action Contract storage
(that is `saena_domain.policy`/plan-contract-service's job) — this module
only extracts the three facts a quality-eval run needs FROM an
already-approved `ChangePlan` payload (validated here against the
`domain/change-plan/v1` contract's generated pydantic model,
`ChangeplanActionContract`, so a caller cannot silently pass a malformed
"approved contract" through to the gate engine):

- `repo_commit` -> the approved base commit `gates.gate_commit_coherence`
  checks a `PatchArtifact.base_commit` against.
- `patch_units[].id` -> the approved patch-unit id set
  `gates.gate_diff_rationality` checks every diff hunk's linkage against.
- `approved_scope` -> the glob list `gates.gate_boundary`-shaped
  `BoundaryOutcome.approved_scope_globs` mirrors (this module does not
  itself compute `BoundaryOutcome.out_of_scope_files` — glob matching
  against `approved_scope` is a caller/harness concern, same as every
  other gate's "pluggable check over adapter output" shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from saena_schemas.domain.change_plan_v1 import ChangeplanActionContract

from saena_quality_eval.errors import ApprovedContractValidationError


@dataclass(frozen=True, slots=True)
class ApprovedContractFacts:
    """The 3 facts a quality-eval run needs from an approved `ChangePlan`."""

    approved_base_commit: str
    approved_patch_unit_ids: frozenset[str]
    approved_scope_globs: tuple[str, ...]


def extract_approved_contract_facts(change_plan: dict[str, Any]) -> ApprovedContractFacts:
    """Validate `change_plan` against `domain/change-plan/v1` and extract
    the facts this engine needs.

    Raises `ApprovedContractValidationError` if `change_plan` does not
    conform to that CLOSED contract shape.
    """
    try:
        model = ChangeplanActionContract.model_validate(change_plan)
    except ValidationError as exc:
        raise ApprovedContractValidationError(
            "supplied approved contract does not conform to domain/change-plan/v1",
            context={},
        ) from exc
    return ApprovedContractFacts(
        approved_base_commit=str(model.repo_commit.root),
        approved_patch_unit_ids=frozenset(unit.id for unit in model.patch_units),
        approved_scope_globs=tuple(model.approved_scope),
    )


__all__ = ["ApprovedContractFacts", "extract_approved_contract_facts"]
