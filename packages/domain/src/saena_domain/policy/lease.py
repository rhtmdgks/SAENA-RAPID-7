"""Per-patch-unit lease value object (H-7).

security-model.md H-7: "per-patch-unit secret lease + Git write token 분리".
This module models the LEASE RECORD as a plain, immutable value object only
(task instruction 4: "model per-patch-unit lease issuance on approval (lease
record: unit id, scope, expiry — value object only)") — it does not issue
secrets, tokens, or perform any I/O. Actual secret-broker wiring
(security-model.md 6.1 Secret lifecycle: B승인 -> Secret broker -> short-lived
tenant token -> Runner Job) is out of this patch unit's scope.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PatchUnitLease:
    """Value object: a per-patch-unit execution lease issued on approval."""

    patch_unit_id: str
    scope: tuple[str, ...]
    expiry: str  # timestamp_utc-formatted (identifiers.schema.json timestamp_utc)


def issue_lease(
    *,
    patch_unit_id: str,
    scope: tuple[str, ...],
    expiry: str,
) -> PatchUnitLease:
    """Construct a PatchUnitLease value object.

    Pure construction only — callers are responsible for ensuring `expiry` is
    a valid timestamp_utc string and that this is only invoked after a plan
    has reached PlanState.APPROVED (guard_execution/transition enforce that
    upstream; this function does not re-check plan state, it only builds the
    value object task instruction 4 asks for).
    """
    if not patch_unit_id:
        raise ValueError("patch_unit_id must be non-empty")
    return PatchUnitLease(patch_unit_id=patch_unit_id, scope=scope, expiry=expiry)
