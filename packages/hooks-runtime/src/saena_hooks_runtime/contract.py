"""Action Contract model (task instructions):

"Action Contract model: run_id, customer_id (tenant), repo_commit,
approved_scope (file/glob allowlist), engine_scope (must equal
["chatgpt-search"]), patch_units (files, allowed transformations, tests,
rollback method), approval_required + contract_hash. Write of any path
outside approved_scope ⇒ DENY. Missing/hash-mismatched contract ⇒ DENY
(fail-closed)."

`compute_contract_hash` is the SSOT for what "the hash" means here: sha256
over a canonical (sorted-key, compact-separator) JSON encoding of every
contract field EXCEPT `contract_hash` itself. `validate_contract` is the
single fail-closed gate every hook that needs a live contract calls before
doing anything else — `session_start.verify_run_context` and
`pre_tool_use.require_action_contract_for_write` both call it rather than
each re-implementing "missing or hash-mismatched or wrong engine scope"
independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .models import ReasonCode

#: v1 closed engine scope (CLAUDE.md "Engine scope (v1): Target: ChatGPT
#: Search only" — mirrors `packages/schemas/saena_schemas/common/engine_id_v1`
#: at the contract level; this package does not depend on `saena_schemas`
#: (kept dependency-free per task instructions), so the literal is
#: reproduced here rather than imported).
REQUIRED_ENGINE_SCOPE: tuple[str, ...] = ("chatgpt-search",)


@dataclass(frozen=True, slots=True)
class PatchUnit:
    """One patch unit inside an `ActionContract` — "files, allowed
    transformations, tests, rollback method" (task instructions)."""

    unit_id: str
    files: tuple[str, ...]
    allowed_transformations: tuple[str, ...]
    tests: tuple[str, ...]
    rollback_method: str


@dataclass(frozen=True, slots=True)
class ActionContract:
    """The signed scope-of-work document every write-capable hook call is
    checked against. Exact field set per task instructions: "run_id,
    customer_id (tenant), repo_commit, approved_scope (file/glob
    allowlist), engine_scope (must equal ["chatgpt-search"]), patch_units
    (...), approval_required + contract_hash"."""

    run_id: str
    customer_id: str
    repo_commit: str
    approved_scope: tuple[str, ...]
    engine_scope: tuple[str, ...]
    patch_units: tuple[PatchUnit, ...]
    approval_required: bool
    contract_hash: str


def _canonical_payload(contract: ActionContract) -> dict[str, object]:
    payload = asdict(contract)
    del payload["contract_hash"]
    return payload


def compute_contract_hash(contract: ActionContract) -> str:
    """sha256 hex digest of `contract`'s canonical JSON encoding, excluding
    `contract_hash` itself. Deterministic: field order does not matter
    (`sort_keys=True`), tuples serialize as JSON arrays via `asdict`."""
    canonical = json.dumps(_canonical_payload(contract), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_contract(contract: ActionContract | None) -> ReasonCode | None:
    """Fail-closed contract gate — returns the first violated `ReasonCode`,
    or `None` if `contract` is present, hash-valid, and engine-scope-valid.

    Check order (first failure wins, matches task instructions' ordering
    "Missing/hash-mismatched contract ⇒ DENY (fail-closed)"):
    1. `contract is None` -> `CONTRACT_MISSING`
    2. `contract.contract_hash != compute_contract_hash(contract)` ->
       `CONTRACT_HASH_MISMATCH`
    3. `contract.engine_scope != REQUIRED_ENGINE_SCOPE` ->
       `ENGINE_SCOPE_VIOLATION` (CLAUDE.md "Engine scope (v1)" / task
       instructions "engine_scope (must equal [\"chatgpt-search\"])")
    """
    if contract is None:
        return ReasonCode.CONTRACT_MISSING
    if contract.contract_hash != compute_contract_hash(contract):
        return ReasonCode.CONTRACT_HASH_MISMATCH
    if tuple(contract.engine_scope) != REQUIRED_ENGINE_SCOPE:
        return ReasonCode.ENGINE_SCOPE_VIOLATION
    return None


__all__ = [
    "REQUIRED_ENGINE_SCOPE",
    "ActionContract",
    "PatchUnit",
    "compute_contract_hash",
    "validate_contract",
]
