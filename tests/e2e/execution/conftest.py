"""pytest fixtures for `tests/e2e/execution` — the Wave 3 synthetic-tenant
E2E (Plan -> approval -> patch -> verify -> handoff).

Reuses two OTHER patch units' own test harnesses (read-only imports, never
modifications — this unit's exclusive-write paths are `tests/e2e/execution/**`
and `tests/integration/execution_e2e/**` only):

- `tests/integration/approval_flow/{approval_harness,approval_factories}.py`
  — the real plan-contract-service + policy-gate-service + audit-ledger-service
  wiring (`PlanContractHttpGateAdapter`, `AuditChainRelay`), the SAME
  approach `tests/e2e/approval/conftest.py` already takes for the W2A E2E
  suite.
- `tests/unit/svc_repository_intake/intake_factories.py` — `FakeContentHashVerifier`/
  `FakeSecretScanner` (real Git-content-hash/secret-scan tool integration is
  explicitly out of repository-intake-service's OWN exclusive-write scope
  per that package's `protocols.py` docstring — these fakes are the
  documented substitute, not a workaround this unit invented).

`PlanApprovalHarness` + shared tenant/run/patch-unit constants live in
`execution_e2e_harness.py`, NOT here — see that module's own docstring for
why (a `from conftest import ...` collision this repo has already hit
elsewhere).

`tests/` is not a package — every directory this conftest inserts onto
`sys.path` follows the SAME uniquely-named-module discipline documented in
each of those directories' own `conftest.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_APPROVAL_FLOW_DIR = _REPO_ROOT / "tests" / "integration" / "approval_flow"
_REPO_INTAKE_TEST_DIR = _REPO_ROOT / "tests" / "unit" / "svc_repository_intake"
_REPOSITORY_INTAKE_SRC = (
    _REPO_ROOT / "services" / "acquisition" / "repository-intake-service" / "src"
)

for _path in (_THIS_DIR, _APPROVAL_FLOW_DIR, _REPO_INTAKE_TEST_DIR, _REPOSITORY_INTAKE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from approval_factories import load_change_plan_fixture  # noqa: E402
from execution_e2e_harness import TENANT_1, PlanApprovalHarness  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from git_worktree_adapter import GitSyntheticRepo, GitWorktreeFactory  # noqa: E402
from intake_factories import (  # noqa: E402
    FakeContentHashVerifier,
    FakeSecretScanner,
)
from saena_artifact_registry.app import create_app as create_artifact_registry_app  # noqa: E402
from saena_artifact_registry.blobstore import InMemoryBlobStore  # noqa: E402
from saena_domain.persistence import (  # noqa: E402
    InMemoryArtifactManifestStore,
    InMemoryOutbox,
    InMemoryTenantRepository,
)
from saena_repository_intake.app import create_app as create_repository_intake_app  # noqa: E402
from saena_repository_intake.memory import (  # noqa: E402
    InMemoryAuditSink,
    InMemoryIntakeManifestStore,
    InMemoryWorkspaceStaging,
)
from saena_tenant_control.app import create_app as create_tenant_control_app  # noqa: E402


@pytest.fixture
def tenant_control() -> TestClient:
    repo = InMemoryTenantRepository()
    outbox = InMemoryOutbox()
    app = create_tenant_control_app(repo, outbox)
    return TestClient(app)


@pytest.fixture
def repository_intake() -> TestClient:
    app = create_repository_intake_app(
        manifest_store=InMemoryIntakeManifestStore(),
        hash_verifier=FakeContentHashVerifier(),
        secret_scanner=FakeSecretScanner(),
        audit_sink=InMemoryAuditSink(),
        workspace=InMemoryWorkspaceStaging(),
    )
    return TestClient(app)


@pytest.fixture
def artifact_manifests() -> InMemoryArtifactManifestStore:
    return InMemoryArtifactManifestStore()


@pytest.fixture
def artifact_registry(artifact_manifests: InMemoryArtifactManifestStore) -> TestClient:
    app = create_artifact_registry_app(manifests=artifact_manifests, blobs=InMemoryBlobStore())
    return TestClient(app)


@pytest.fixture
def plan_approval_harness(monkeypatch: pytest.MonkeyPatch):
    # policy-gate-service (like tenant-control-service) reconciles
    # `X-Saena-Tenant-Id` against the process `SAENA_TENANT_ID` env var at
    # REQUEST time (ADR-0014) — set explicitly here (never relying on an
    # incidental earlier `monkeypatch.setenv` call elsewhere in a test
    # function body) so this fixture is correct in isolation.
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_1)
    harness = PlanApprovalHarness(tenant_id=TENANT_1)
    yield harness
    harness.close()


@pytest.fixture
def change_plan() -> dict:
    return load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_1)


@pytest.fixture
def git_synthetic_repo(tmp_path: Path):
    repo = GitSyntheticRepo.init(
        tmp_path / "synthetic-source-repo",
        seed_files={"apps/web/docs/existing.md": b"# existing docs\n"},
    )
    yield repo
    repo.cleanup()


@pytest.fixture
def git_worktree_factory(git_synthetic_repo: GitSyntheticRepo, tmp_path: Path):
    factory = GitWorktreeFactory(repo=git_synthetic_repo, _tmp_root=tmp_path / "worktrees")
    yield factory
    factory.cleanup()
