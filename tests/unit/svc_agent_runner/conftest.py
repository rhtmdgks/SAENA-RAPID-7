"""pytest fixtures for `tests/unit/svc_agent_runner`.

`tests/` is not a package — this directory is inserted onto `sys.path` so
sibling test modules can `from runner_factories import ...` (same isolation
pattern as `tests/unit/svc_artifact_registry/conftest.py` — factory helpers
live under a uniquely-named module, never a second `conftest.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from runner_factories import TENANT_A, build_job_context  # noqa: E402
from saena_agent_runner.artifact import FakeArtifactRegistryGateway  # noqa: E402
from saena_agent_runner.clock import FakeClock  # noqa: E402
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory  # noqa: E402
from saena_domain.audit import InMemoryAuditChain  # noqa: E402
from saena_domain.execution import JobContext  # noqa: E402


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


@pytest.fixture
def tenant_a() -> str:
    return TENANT_A
