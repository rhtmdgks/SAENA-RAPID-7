"""Shared typed models for `saena_pilot`.

Dataclasses (frozen, slots) + closed enums, mirroring `saena_forgectl.models`.
Anything serialized here is log-safe: paths, hashes, reason strings — never
customer file content, never secret material.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """Deterministic JSON used everywhere a hash is computed over a payload
    (evidence chain, contract hash). Sorted keys, no whitespace, unicode
    preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Mode(str, Enum):
    """The seven pilot modes (wave6-plan §3.3). Capability properties below
    are the single source of truth for what a mode may do — enforcement code
    consults these rather than re-listing mode names."""

    PREFLIGHT = "preflight"
    AUDIT = "audit"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    RESUME = "resume"
    STATUS = "status"

    @property
    def starts_run(self) -> bool:
        """Modes that begin a new pilot run against a customer repo."""
        return self in (Mode.PREFLIGHT, Mode.AUDIT, Mode.PLAN, Mode.IMPLEMENT)

    @property
    def launches_claude(self) -> bool:
        """Modes that render/execute a Claude Code launch."""
        return self in (Mode.AUDIT, Mode.PLAN, Mode.IMPLEMENT)

    @property
    def writes_customer(self) -> bool:
        """The ONLY mode that carries customer-side write capability (via a
        dedicated worktree). Every other mode is read-only with respect to
        the customer repository — no code path may create the worktree or
        write under the customer root for them."""
        return self is Mode.IMPLEMENT

    @property
    def requires_complete_contract(self) -> bool:
        """Modes refused outright while the action contract has open
        questions."""
        return self in (Mode.PLAN, Mode.IMPLEMENT)


class Severity(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"


@dataclass(frozen=True, slots=True)
class Finding:
    """One boundary/preflight finding, already classified for the current
    mode (write modes BLOCK on dirty/detached/nested; read modes WARN)."""

    code: str
    severity: Severity
    detail: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "detail": self.detail,
            "context": self.context,
        }


@dataclass(frozen=True, slots=True)
class BoundaryReport:
    """Result of customer-repo boundary validation for one mode. Hard shape/
    containment failures never reach this report — they raise. What remains
    are state findings (dirty, detached, nested repos) classified per mode."""

    customer_root: Path
    head_sha: str
    findings: tuple[Finding, ...]

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.BLOCK for f in self.findings)

    @property
    def block_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.BLOCK)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_root": str(self.customer_root),
            "head_sha": self.head_sha,
            "findings": [f.to_dict() for f in self.findings],
            "blocked": self.blocked,
        }


@dataclass(frozen=True, slots=True)
class BundleInfo:
    """Positive proof of skill-bundle validation, bound into evidence."""

    manifest_path: Path
    manifest_schema_version: str
    manifest_sha256: str
    bundle_name: str
    skill_names: tuple[str, ...]
    validator_invocations: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "manifest_schema_version": self.manifest_schema_version,
            "manifest_sha256": self.manifest_sha256,
            "bundle_name": self.bundle_name,
            "skill_names": list(self.skill_names),
            "validator_invocations": [list(argv) for argv in self.validator_invocations],
        }


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    """A fully rendered Claude Code launch: discrete argv elements (quoting is
    structural — never a shell string), launch cwd pinned to the RAPID-7 root
    so hooks/agents/settings stay active, plus a small env overlay."""

    argv: tuple[str, ...]
    cwd: Path
    env_overlay: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "env_overlay": dict(self.env_overlay),
        }
