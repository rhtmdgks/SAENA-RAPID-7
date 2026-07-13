"""pytest fixtures for `tests/unit/svc_repository_intake`.

Two `sys.path` insertions, both required because `saena-repository-intake`
is NOT YET a registered `[tool.uv.workspace]` member (Integrator action —
see this patch unit's final report) — unlike `tests/unit/svc_artifact_registry/
conftest.py` (which only needs the local test-factory-module insertion,
since `saena_artifact_registry` is already `uv`-workspace-installed):

1. This directory itself, so sibling test modules can
   `from intake_factories import ...` (uniquely-named module, never a
   second `conftest.py` — same collision-avoidance precedent
   `registry_factories.py`'s own docstring documents).
2. `services/acquisition/repository-intake-service/src`, so
   `import saena_repository_intake` resolves at all — every OTHER
   dependency it imports (`fastapi`, `saena_domain`, `saena_observability`,
   `saena_schemas`) is already installed in the shared workspace venv via
   already-registered packages, so only this one unregistered package's own
   source tree needs the extra path entry.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_SERVICE_SRC = _REPO_ROOT / "services" / "acquisition" / "repository-intake-service" / "src"

for _path in (_THIS_DIR, _SERVICE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from intake_factories import (  # noqa: E402
    TENANT_A,
    TENANT_B,
    FakeContentHashVerifier,
    FakeSecretScanner,
    build_job_context,
    build_snapshot_payload,
)
from saena_domain.identity.http import TENANT_HEADER_NAME  # noqa: E402
from saena_repository_intake.app import create_app  # noqa: E402
from saena_repository_intake.memory import (  # noqa: E402
    InMemoryAuditSink,
    InMemoryIntakeManifestStore,
    InMemoryWorkspaceStaging,
)


@pytest.fixture
def manifest_store() -> InMemoryIntakeManifestStore:
    return InMemoryIntakeManifestStore()


@pytest.fixture
def audit_sink() -> InMemoryAuditSink:
    return InMemoryAuditSink()


@pytest.fixture
def workspace() -> InMemoryWorkspaceStaging:
    return InMemoryWorkspaceStaging()


@pytest.fixture
def hash_verifier() -> FakeContentHashVerifier:
    return FakeContentHashVerifier()


@pytest.fixture
def secret_scanner() -> FakeSecretScanner:
    return FakeSecretScanner()


@pytest.fixture
def job_context():
    return build_job_context()


@pytest.fixture
def snapshot_payload() -> dict[str, object]:
    return build_snapshot_payload()


@pytest.fixture
def client(
    manifest_store: InMemoryIntakeManifestStore,
    hash_verifier: FakeContentHashVerifier,
    secret_scanner: FakeSecretScanner,
    audit_sink: InMemoryAuditSink,
    workspace: InMemoryWorkspaceStaging,
) -> TestClient:
    app = create_app(
        manifest_store=manifest_store,
        hash_verifier=hash_verifier,
        secret_scanner=secret_scanner,
        audit_sink=audit_sink,
        workspace=workspace,
    )
    return TestClient(app)


@pytest.fixture
def tenant_headers() -> dict[str, str]:
    return {TENANT_HEADER_NAME: TENANT_A}


__all__ = [
    "TENANT_A",
    "TENANT_B",
]
