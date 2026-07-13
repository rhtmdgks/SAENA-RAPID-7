"""Agent-runner F-5 skill-bundle integrity boundary.

The pure hash/verify logic lives in `saena_domain.execution.skill_bundle`
(imported directly — services may import saena_domain). This module adds the
runner-side seam: a `SkillBundleSource` Protocol the runner reads the actual
bundle through (real deployments back it with `read_skill_bundle` over the
mounted skill bundle; tests use `InMemorySkillBundleSource`), and
`enforce_skill_bundle_integrity`, the single fail-closed call the runner makes
BEFORE it creates any worktree or invokes any executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from saena_domain.execution import JobContext
from saena_domain.execution.skill_bundle import (
    SkillBundle,
    SkillBundleMissingError,
    verify_skill_bundle,
)


@runtime_checkable
class SkillBundleSource(Protocol):
    """Read-only source of the skill bundle a run will execute. Returns the
    already-read `path -> bytes` mapping, or `None` if no bundle exists for
    this run (which the verifier treats as fail-closed when a hash is pinned)."""

    def load_bundle(self, *, job_context: JobContext) -> SkillBundle | None: ...


@dataclass(slots=True)
class InMemorySkillBundleSource:
    """Test/reference source: a fixed in-memory bundle (or None)."""

    bundle: SkillBundle | None = None

    def load_bundle(self, *, job_context: JobContext) -> SkillBundle | None:
        return self.bundle


@dataclass(slots=True)
class RecordingSkillBundleSource:
    """Wraps a source and records whether `load_bundle` was ever called — used
    by tests to prove the runner attempted verification before any worktree."""

    inner: SkillBundleSource
    loaded: bool = field(default=False)

    def load_bundle(self, *, job_context: JobContext) -> SkillBundle | None:
        self.loaded = True
        return self.inner.load_bundle(job_context=job_context)


def enforce_skill_bundle_integrity(
    *,
    expected_skill_bundle_hash: str | None,
    source: SkillBundleSource | None,
    job_context: JobContext,
) -> str:
    """Fail-closed F-5 gate for the agent-runner. Returns the verified
    `sha256:<hex>` on success; raises a `SkillBundleIntegrityError` subclass
    otherwise. Loads the bundle only to hash it (no execution side effect).

    A pinned expected hash with NO configured source is a fail-closed
    condition (we cannot prove integrity), not an implicit pass.
    """
    if source is None:
        raise SkillBundleMissingError(
            "a skill_bundle_hash is pinned but no SkillBundleSource is wired — fail closed",
            context={},
        )
    bundle = source.load_bundle(job_context=job_context)
    return verify_skill_bundle(expected_hash=expected_skill_bundle_hash, bundle=bundle)


__all__ = [
    "InMemorySkillBundleSource",
    "RecordingSkillBundleSource",
    "SkillBundleSource",
    "enforce_skill_bundle_integrity",
]
