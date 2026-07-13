"""Dedicated skill-bundle content-integrity verification (failure-mode F-5,
k3s spec §10 "skill compromise": *third-party skill changes commands →
pinned hash mismatch → run blocked*).

This is DISTINCT from, and does NOT replace, the whole-ActionContract
`contract_hash` check (`saena_hooks_runtime.contract.compute_contract_hash`).
That check proves the approved *plan document* was not altered; it says
nothing about whether the *actual skill bundle files* an agent will execute
match what was approved. A tampered skill file inside an otherwise-identical
contract sails through the contract-hash gate. F-5 needs a gate over the
bundle's own bytes — this module.

Canonical field / format reuse (no new normative decision): the pinned value
is the k3s spec §9.1 run-trace-envelope `skill_bundle_hash` and the Helm
values `skillBundle.digest` — both `sha256:<hex>`. `compute_skill_bundle_hash`
emits exactly that shape. The hashing *philosophy* mirrors
`saena_hooks_runtime.contract.compute_contract_hash` (sorted, compact,
unambiguous framing, sha256) — the two are independent implementations of the
same house rule, not a shared import (hooks-runtime is a stdlib-only leaf and
may not import this package; agent-runner imports this directly; hooks-runtime
reaches it only through an injected Port — see `hooks/session_start.py`).

Determinism guarantees (verified by tests):
- entries sorted by their normalized relative path (bytes-wise, stable)
- each entry framed length-prefixed so no path/content byte-run can be
  reinterpreted as a boundary (`<pathlen>:<path>\n<contentlen>:<sha256(content)>\n`)
- content is hashed (not embedded) so the manifest is bounded and secret
  file contents never enter the manifest string
- no wall-clock, no randomness, no filesystem-iteration-order dependence
- identical logical bundle -> byte-identical hash; any path or content change
  -> different hash

Everything here is pure: it operates on an already-read, in-memory
`SkillBundle` (a mapping of normalized relative path -> raw bytes). Reading a
bundle off a real filesystem — and rejecting symlinks / path traversal while
doing so — is `read_skill_bundle`, which is the ONE I/O-touching helper and
is itself fail-closed.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from saena_domain.execution.errors import ExecutionError

_SHA256_PREFIX = "sha256:"
_HEX = frozenset("0123456789abcdef")


class SkillBundleIntegrityError(ExecutionError):
    """Base for every fail-closed F-5 skill-bundle rejection."""

    error_code = "saena.policy_denied.skill_bundle_integrity"


class SkillBundleHashMissingError(SkillBundleIntegrityError):
    error_code = "saena.policy_denied.skill_bundle_hash_missing"


class SkillBundleHashMalformedError(SkillBundleIntegrityError):
    error_code = "saena.policy_denied.skill_bundle_hash_malformed"


class SkillBundleMissingError(SkillBundleIntegrityError):
    error_code = "saena.policy_denied.skill_bundle_missing"


class SkillBundleHashMismatchError(SkillBundleIntegrityError):
    error_code = "saena.policy_denied.skill_bundle_hash_mismatch"


class SkillBundleUnreadableError(SkillBundleIntegrityError):
    """Read / canonicalization / path-safety failure — fail closed."""

    error_code = "saena.policy_denied.skill_bundle_unreadable"


def _normalize_relpath(raw: str) -> str:
    """Deterministic, traversal-safe relative-path normalization.

    Rejects (raises `SkillBundleUnreadableError`) absolute paths, `..`
    segments, and anything that would escape the bundle root. Collapses `.`
    segments and backslashes so the same logical file always frames identically.
    """
    if not raw or not isinstance(raw, str):
        raise SkillBundleUnreadableError(
            "skill-bundle entry has an empty or non-string path", context={}
        )
    candidate = raw.replace("\\", "/")
    if candidate.startswith("/"):
        raise SkillBundleUnreadableError(
            "skill-bundle entry path is absolute (must be bundle-relative)",
            context={"path": raw},
        )
    parts: list[str] = []
    for segment in candidate.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise SkillBundleUnreadableError(
                "skill-bundle entry path escapes the bundle root ('..')",
                context={"path": raw},
            )
        parts.append(segment)
    if not parts:
        raise SkillBundleUnreadableError(
            "skill-bundle entry path normalizes to empty", context={"path": raw}
        )
    return "/".join(parts)


#: An already-read bundle: normalized-relative-path -> raw file bytes.
SkillBundle = Mapping[str, bytes]


def compute_skill_bundle_hash(bundle: SkillBundle) -> str:
    """Deterministic `sha256:<hex>` over `bundle`'s framed manifest.

    Pure. Same logical bundle -> identical output on every call and process;
    any added/removed/renamed/mutated file changes the output.
    """
    if not isinstance(bundle, Mapping):
        raise SkillBundleUnreadableError("skill bundle must be a path->bytes mapping", context={})
    framed: list[str] = []
    normalized: dict[str, bytes] = {}
    for raw_path, content in bundle.items():
        norm = _normalize_relpath(raw_path)
        if norm in normalized:
            raise SkillBundleUnreadableError(
                "skill-bundle has two entries normalizing to the same path",
                context={"path": norm},
            )
        if not isinstance(content, (bytes, bytearray)):
            raise SkillBundleUnreadableError(
                "skill-bundle entry content is not bytes", context={"path": norm}
            )
        normalized[norm] = bytes(content)
    for norm in sorted(normalized):
        content_digest = hashlib.sha256(normalized[norm]).hexdigest()
        path_bytes = norm.encode("utf-8")
        # length-prefixed framing: neither a path nor a digest can contain a
        # byte-run that reproduces the next field's frame.
        framed.append(f"{len(path_bytes)}:{norm}\n{len(content_digest)}:{content_digest}\n")
    manifest = "".join(framed)
    digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return _SHA256_PREFIX + digest


def _require_well_formed_expected(expected_hash: str | None) -> str:
    if expected_hash is None or expected_hash == "":
        raise SkillBundleHashMissingError(
            "no expected skill_bundle_hash was pinned for this run — fail closed",
            context={},
        )
    if not isinstance(expected_hash, str) or not expected_hash.startswith(_SHA256_PREFIX):
        raise SkillBundleHashMalformedError(
            "expected skill_bundle_hash is not a 'sha256:<hex>' value",
            context={},
        )
    hexpart = expected_hash[len(_SHA256_PREFIX) :]
    if len(hexpart) != 64 or any(c not in _HEX for c in hexpart):
        raise SkillBundleHashMalformedError(
            "expected skill_bundle_hash digest is not 64 lowercase hex chars",
            context={},
        )
    return expected_hash


def verify_skill_bundle(*, expected_hash: str | None, bundle: SkillBundle | None) -> str:
    """Fail-closed F-5 gate. Returns the verified `sha256:<hex>` on success;
    raises a `SkillBundleIntegrityError` subclass on ANY of: missing/malformed
    expected hash, missing bundle, unreadable/traversal-unsafe entry, or
    expected≠actual mismatch (which covers file add/delete/rename/content
    change, since all of those move the computed hash).

    Never echoes raw file contents into the exception/`.context` — only paths
    and digests appear, so a secret-bearing skill file cannot leak through an
    F-5 denial (verified by tests).
    """
    verified_expected = _require_well_formed_expected(expected_hash)
    if bundle is None:
        raise SkillBundleMissingError(
            "expected skill_bundle_hash pinned but no bundle was provided — fail closed",
            context={},
        )
    actual = compute_skill_bundle_hash(bundle)
    if actual != verified_expected:
        # Include only the two digests (never file contents) so the audit
        # trail can prove a mismatch without leaking bundle bytes.
        raise SkillBundleHashMismatchError(
            "skill bundle content hash does not match the approved pin — run blocked",
            context={"expected": verified_expected, "actual": actual},
        )
    return actual


def read_skill_bundle(root: str, *, relpaths: Iterable[str]) -> dict[str, bytes]:
    """Read the named `relpaths` under `root` into an in-memory bundle,
    fail-closed on any symlink, traversal, missing file, or read error.

    This is the ONE I/O helper. It resolves the real path of `root` once and
    requires every entry's real path to stay within it (defeating symlink
    escape and `..` traversal even if the OS would follow them).
    """
    try:
        real_root = os.path.realpath(root)
    except OSError as exc:
        raise SkillBundleUnreadableError(
            "skill-bundle root is unreadable", context={"root": root}
        ) from exc
    if not os.path.isdir(real_root):
        raise SkillBundleMissingError(
            "skill-bundle root does not exist or is not a directory",
            context={"root": root},
        )
    out: dict[str, bytes] = {}
    for raw in relpaths:
        norm = _normalize_relpath(raw)
        target = os.path.join(real_root, *norm.split("/"))
        # Reject symlinks along the final component explicitly...
        if os.path.islink(target):
            raise SkillBundleUnreadableError(
                "skill-bundle entry is a symlink (not allowed)", context={"path": norm}
            )
        real_target = os.path.realpath(target)
        # ...and require the resolved real path to stay inside the root
        # (defeats symlinked parent dirs / traversal).
        if real_target != real_root and not real_target.startswith(real_root + os.sep):
            raise SkillBundleUnreadableError(
                "skill-bundle entry resolves outside the bundle root",
                context={"path": norm},
            )
        if not os.path.isfile(real_target):
            raise SkillBundleMissingError(
                "skill-bundle entry file is missing", context={"path": norm}
            )
        try:
            with open(real_target, "rb") as fh:
                out[norm] = fh.read()
        except OSError as exc:
            raise SkillBundleUnreadableError(
                "skill-bundle entry could not be read", context={"path": norm}
            ) from exc
    return out


@dataclass(frozen=True, slots=True)
class SkillBundleVerification:
    """Structured result surface for callers that prefer a value over an
    exception (the agent-runner and the hooks-runtime Port both raise, but a
    caller may want to record this)."""

    verified_hash: str


__all__ = [
    "SkillBundle",
    "SkillBundleHashMalformedError",
    "SkillBundleHashMismatchError",
    "SkillBundleHashMissingError",
    "SkillBundleIntegrityError",
    "SkillBundleMissingError",
    "SkillBundleUnreadableError",
    "SkillBundleVerification",
    "compute_skill_bundle_hash",
    "read_skill_bundle",
    "verify_skill_bundle",
]
