"""`build_verification_result` — renders a `GateResult` into the
`domain/verification-result/v1` wire shape, validated against that
contract's generated pydantic model (`saena_schemas.domain.
verification_result_v1.VerificationResult`) before being returned as a
plain `dict`.

Determinism (mission item 8): this function is pure — no wall-clock read
(`evaluated_at` is caller-supplied, never `datetime.utcnow()`), no
randomness, no I/O. Given equal arguments, it returns an equal dict on every
call; `canonical.canonical_json` (this package's own thin re-export of
`saena_domain.audit.canonical.canonical_json`) turns that dict into the
byte-identical string form `test_determinism_and_idempotency.py` asserts
equality over.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_schemas.domain.verification_result_v1 import VerificationResult

from saena_quality_eval.errors import VerificationResultValidationError
from saena_quality_eval.gate_result import GateResult


def build_verification_result(
    *,
    tenant_id: str,
    run_id: str,
    patch_unit_id: str,
    worktree_commit: str,
    evaluated_at: str,
    gate_result: GateResult,
    report_uri: str | None = None,
) -> dict[str, Any]:
    """Build and validate one `domain/verification-result/v1` row for
    `gate_result`.

    Raises `VerificationResultValidationError` if the assembled payload does
    not conform to the contract — a defensive check; every `gates.py`
    function is constructed to always produce a conformant `GateResult`
    (Ruling R4 enforced structurally by `GateResult.__post_init__` itself),
    so this should never fire in practice.
    """
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "patch_unit_id": patch_unit_id,
        "gate_id": str(gate_result.gate_id),
        "status": "passed" if gate_result.passed else "failed",
        "worktree_commit": worktree_commit,
        "evaluated_at": evaluated_at,
    }
    if gate_result.failures:
        payload["failures"] = [f.to_error_detail_payload() for f in gate_result.failures]
    if report_uri is not None:
        payload["report_uri"] = report_uri

    try:
        instance = VerificationResult.model_validate(payload)
    except ValidationError as exc:
        raise VerificationResultValidationError(
            "built VerificationResult payload failed domain/verification-result/v1 validation",
            context={"gate_id": str(gate_result.gate_id)},
        ) from exc
    return instance.model_dump(mode="json", exclude_none=True)


__all__ = ["build_verification_result"]
