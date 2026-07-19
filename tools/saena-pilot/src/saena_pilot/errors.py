"""Exception hierarchy for `saena_pilot`.

Mirrors the `error_code` + structured `context` convention used by
`saena_forgectl.errors`. Every failure family the CLI must map to a distinct
exit code (wave6-plan §3.3) gets its own exception class; `saena_pilot.cli`
owns the class → exit-code mapping so library callers see typed exceptions,
not process exits.

Context dicts are log-safe by construction: no secret material, no customer
file content — paths, hashes, and reason strings only (secret-shaped values
are refused upstream by `saena_pilot.secretguard`).
"""

from __future__ import annotations

from typing import Any


class PilotError(Exception):
    """Base class for every error raised by `saena_pilot`."""

    error_code: str = "saena.pilot.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}


class ValidationFailedError(PilotError):
    """An input was evaluated and rejected (path shape, git state, domain,
    resume-state mismatch, evidence integrity, ...). Maps to
    `EXIT_VALIDATION_FAILED` unless a subclass narrows it further."""

    error_code = "saena.pilot.validation_failed"


class BoundaryViolationError(ValidationFailedError):
    """A *containment* violation between the customer repository and the
    RAPID-7 repository: same repo, customer nested inside RAPID-7, RAPID-7
    nested inside customer, or a symlink that resolves across the boundary.
    Deliberately its own class/exit code — this is the failure family the
    pilot exists to make impossible to ignore."""

    error_code = "saena.pilot.boundary_violation"


class ContractIncompleteError(PilotError):
    """The action contract is missing critical inputs. Carries every missing
    input as a numbered human question — the pilot never invents business
    claims, credentials, consent, KPIs, or legal approval."""

    error_code = "saena.pilot.contract_incomplete"

    def __init__(self, questions: list[str], *, context: dict[str, Any] | None = None) -> None:
        self.questions = list(questions)
        joined = "\n".join(self.questions)
        super().__init__(
            f"action contract incomplete — answer these before proceeding:\n{joined}",
            context=context,
        )


class BundleInvalidError(PilotError):
    """The mandatory skill bundle could not be positively validated: manifest
    missing/unparsable/wrong schema, validator script missing, or validator
    subprocess reported failure. Fail-closed — there is deliberately no flag,
    env var, or alternate entry point that bypasses this check."""

    error_code = "saena.pilot.bundle_invalid"


class ResumeMismatchError(ValidationFailedError):
    """Recorded run state does not match the current world (RAPID-7 HEAD or
    customer HEAD moved) — refuses resume to defeat stale-run substitution."""

    error_code = "saena.pilot.resume_mismatch"


class EvidenceIntegrityError(ValidationFailedError):
    """The evidence chain failed verification: mutation, truncation, splice,
    reorder, or missing binding fields."""

    error_code = "saena.pilot.evidence_integrity"


class WorktreeCollisionError(ValidationFailedError):
    """The dedicated customer worktree directory or branch for this run
    already exists. Never resolved with `--force` — a human must inspect."""

    error_code = "saena.pilot.worktree_collision"


class SecretShapedValueError(ValidationFailedError):
    """A value destined for a contract, report, or evidence record looks
    secret-shaped. The value itself is never echoed — only the field path."""

    error_code = "saena.pilot.secret_shaped_value"
