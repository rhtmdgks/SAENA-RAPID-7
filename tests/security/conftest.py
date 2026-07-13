"""pytest fixtures for `tests/security` (w3-09).

`tests/` is not a package. This directory's tests wire directly against the
REAL W3 job/hook/domain code (`saena_hooks_runtime`, `saena_quality_eval`,
`saena_agent_runner`, `saena_repository_intake`, `saena_domain`) — every one
of those is already an installed `[tool.uv.workspace]` member (root
`pyproject.toml`), so no `sys.path` insertion is needed to import THEM.

What DOES need a `sys.path` insertion is this suite's reuse of sibling test
directories' own factory-helper modules (never their `conftest.py` — see
`tests/integration/orchestrator/conftest.py`'s identical precedent for why:
a bare `from conftest import ...` collides across directories once the full
suite is collected together, but a uniquely-named factory module does not).
This is a READ-ONLY cross-import: `tests/unit/**` is outside this patch
unit's exclusive write paths (`tests/security/**`,
`tests/integration/failure_modes/**`) and is never modified here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_FACTORY_DIRS = (
    _REPO_ROOT / "tests" / "unit" / "hooks_runtime",
    _REPO_ROOT / "tests" / "unit" / "svc_agent_runner",
    _REPO_ROOT / "tests" / "unit" / "svc_quality_eval",
    _REPO_ROOT / "tests" / "unit" / "svc_repository_intake",
)

for _path in _FACTORY_DIRS:
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from runner_factories import build_job_context  # noqa: E402
from saena_agent_runner.artifact import FakeArtifactRegistryGateway  # noqa: E402
from saena_agent_runner.clock import FakeClock  # noqa: E402
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory  # noqa: E402
from saena_domain.audit import InMemoryAuditChain  # noqa: E402
from saena_domain.execution import JobContext  # noqa: E402

# --- shared `saena_agent_runner` fixtures (mirrors tests/unit/svc_agent_runner/
# conftest.py's own fixture set exactly — this suite reuses the SAME real
# collaborator doubles, not a second parallel set, so a rollback/failure-mode
# scenario proven here exercises identical wiring to that unit's own tests). ---


@pytest.fixture
def job_context() -> JobContext:
    return build_job_context()


@pytest.fixture
def worktree_factory() -> FakeWorktreeFactory:
    factory = FakeWorktreeFactory()
    yield factory
    factory.cleanup()


@pytest.fixture
def command_executor() -> FakeCommandExecutor:
    return FakeCommandExecutor()


@pytest.fixture
def artifact_gateway() -> FakeArtifactRegistryGateway:
    return FakeArtifactRegistryGateway()


@pytest.fixture
def audit_chain() -> InMemoryAuditChain:
    return InMemoryAuditChain()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
