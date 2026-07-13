"""Exception hierarchy for `saena_quality_eval`.

Follows the same shape every `saena_domain`/service exception hierarchy in
this repo already uses (`saena.<category>.<reason>` `error_code` +
structured, log-safe `context` dict, ADR-0015 9-category taxonomy) — see
`saena_domain.execution.errors` / `saena_artifact_registry.errors` for the
precedent this module mirrors. These are raised only at the boundary
(manifest resolution, approved-contract parsing, contract-shape validation
of a built `VerificationResult`) — the gate functions themselves
(`saena_quality_eval.gates`) never raise; they always return a `GateResult`,
pure-function style (`saena_domain.policy`/`saena_domain.execution.lifecycle`
discipline).
"""

from __future__ import annotations

from typing import Any


class QualityEvalError(Exception):
    """Base class for every error raised by `saena_quality_eval`."""

    error_code: str = "saena.quality_eval.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class PatchArtifactReferenceError(QualityEvalError):
    """A `manifest_ref` (`patch_unit_id` + `worktree_commit`) could not be
    resolved into a valid `PatchArtifact` manifest — either nothing is
    stored under that key, the stored manifest does not conform to the
    `domain/patch-artifact/v1` contract, or it belongs to a different
    tenant (`saena_domain.persistence.errors.TenantIsolationError`,
    wrapped rather than propagated so callers only ever catch
    `QualityEvalError` subclasses from this package)."""

    error_code = "saena.not_found.patch_artifact_reference"


class ApprovedContractValidationError(QualityEvalError):
    """The supplied "approved contract" payload does not conform to the
    `domain/change-plan/v1` (`ChangeplanActionContract`) shape this module
    extracts `repo_commit`/`patch_units[].id`/`approved_scope` facts from."""

    error_code = "saena.validation.approved_contract_invalid"


class VerificationResultValidationError(QualityEvalError):
    """A gate's built payload does not conform to the
    `domain/verification-result/v1` contract (`VerificationResult` codegen
    model) — a programming error in this package's own gate wiring, since
    every gate function is constructed to always produce a conformant
    shape; this is a defense-in-depth check, not an expected runtime path.
    """

    error_code = "saena.validation.verification_result_invalid"


__all__ = [
    "ApprovedContractValidationError",
    "PatchArtifactReferenceError",
    "QualityEvalError",
    "VerificationResultValidationError",
]
