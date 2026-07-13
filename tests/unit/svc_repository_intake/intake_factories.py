"""Factory helpers + test-only fakes for `saena_repository_intake` unit
tests.

Deliberately NOT named `conftest.py` (import-collision precedent —
see `tests/unit/svc_artifact_registry/registry_factories.py`'s own
docstring). `FakeContentHashVerifier`/`FakeSecretScanner` live here, not
under `services/.../src/saena_repository_intake/`, because a fake standing
in for real Git-content-hash/secret-scanning-tool logic is test-only by
nature (`protocols.py`'s own module docstring) — real implementations are
W3-later/integration, out of this patch unit's scope.
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobContext
from saena_repository_intake.protocols import SecretScanResult

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_TRACE_ID_A = "a" * 32


def build_job_context(
    *,
    tenant_id: str = TENANT_A,
    workspace_id: str = "workspace-0001",
    project_id: str = "project-0001",
    run_id: str = "run-0001",
    trace_id: str = _TRACE_ID_A,
    idempotency_key: str = "acme-co:run-0001:intake",
    actor_id: str = "actor-orchestrator",
) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
    )


def build_snapshot_payload(
    *,
    tenant_id: str = TENANT_A,
    run_id: str = "run-0001",
    repo_commit: str = "a" * 40,
    content_hash: str = "sha256:" + "b" * 64,
    snapshot_uri: str = "git://source-host.example/acme-co/repo",
    source_type: str = "git",
    sbom_uri: str = "https://sbom-host.example/acme-co/repo/sbom.json",
    captured_at: str = "2026-07-13T00:00:00Z",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "repo_commit": repo_commit,
        "content_hash": content_hash,
        "snapshot_uri": snapshot_uri,
        "source_type": source_type,
        "sbom_uri": sbom_uri,
        "captured_at": captured_at,
    }


class FakeContentHashVerifier:
    """Test-only `ContentHashVerifier` — passes by default; a snapshot_uri
    explicitly `mark_mismatch`-ed always reports a hash mismatch."""

    def __init__(self) -> None:
        self._mismatched: set[str] = set()

    def mark_mismatch(self, snapshot_uri: str) -> None:
        self._mismatched.add(snapshot_uri)

    def verify(self, *, snapshot_uri: str, expected_hash: str) -> bool:
        return snapshot_uri not in self._mismatched


class FakeSecretScanner:
    """Test-only `SecretScanner` — passes by default; a snapshot_uri
    explicitly `flag`-ged always reports a (redacted, no-secret-echoed)
    finding."""

    def __init__(self) -> None:
        self._flagged: set[str] = set()

    def flag(self, snapshot_uri: str) -> None:
        self._flagged.add(snapshot_uri)

    def scan(self, *, snapshot_uri: str, content_hash: str) -> SecretScanResult:
        if snapshot_uri in self._flagged:
            return SecretScanResult(
                passed=False,
                finding_count=1,
                redacted_summary="secret pattern detected (redacted)",
            )
        return SecretScanResult(passed=True)


__all__ = [
    "TENANT_A",
    "TENANT_B",
    "FakeContentHashVerifier",
    "FakeSecretScanner",
    "build_job_context",
    "build_snapshot_payload",
]
