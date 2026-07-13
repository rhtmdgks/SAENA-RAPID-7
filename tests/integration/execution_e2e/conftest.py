"""pytest fixtures for `tests/integration/execution_e2e`.

Docker-daemon probe: mirrors `tests/integration/persistence_postgres/
conftest.py::_docker_available` / `tests/integration/bus/conftest.py::
_docker_available` EXACTLY (same rationale — never start a container just
to find out; a raw socket probe is the only honest-skip signal). Duplicated
here rather than imported: each of those two directories' own probe is
inside that OTHER patch unit's exclusive-write path, and this repo's
existing precedent (both of those modules already duplicate the same probe
from each other) is to keep each integration subdirectory's own honest-skip
probe self-contained.

`sys.path` insertions: `tests/unit/svc_orchestrator` (for `orchestrator_
factories` — the Temporal signal-path test's own fixture-payload builders,
same reuse `tests/integration/orchestrator/conftest.py` itself performs)
and every directory `tests/e2e/execution/conftest.py` itself inserts (this
package reuses that suite's `GitSyntheticRepo`/`GitWorktreeFactory`/
`execution_e2e_harness` pieces for the Redpanda/Postgres scenarios' fixture
data, rather than re-deriving a second synthetic tenant/repo/plan fixture
set).
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_ORCHESTRATOR_UNIT_TEST_DIR = _REPO_ROOT / "tests" / "unit" / "svc_orchestrator"
_E2E_EXECUTION_DIR = _REPO_ROOT / "tests" / "e2e" / "execution"
_APPROVAL_FLOW_DIR = _REPO_ROOT / "tests" / "integration" / "approval_flow"
_REPO_INTAKE_TEST_DIR = _REPO_ROOT / "tests" / "unit" / "svc_repository_intake"
_REPOSITORY_INTAKE_SRC = (
    _REPO_ROOT / "services" / "acquisition" / "repository-intake-service" / "src"
)

for _path in (
    _ORCHESTRATOR_UNIT_TEST_DIR,
    _E2E_EXECUTION_DIR,
    _APPROVAL_FLOW_DIR,
    _REPO_INTAKE_TEST_DIR,
    _REPOSITORY_INTAKE_SRC,
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _docker_available() -> bool:
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        host_port = docker_host.removeprefix("tcp://")
        host, _, port_str = host_port.partition(":")
        port = int(port_str) if port_str else 2375
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            return False
    for candidate in (
        "/var/run/docker.sock",
        os.path.expanduser("~/.docker/run/docker.sock"),
        os.path.expanduser("~/.colima/default/docker.sock"),
    ):
        if os.path.exists(candidate):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(candidate)
                return True
            except OSError:
                continue
    return False


DOCKER_AVAILABLE = _docker_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DOCKER_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(
        reason="Docker daemon not reachable — honest skip (ADR-0017), "
        "tests/integration/execution_e2e requires Docker for Redpanda/Postgres containers"
    )
    for item in items:
        item_path = Path(str(item.fspath)).resolve()
        # Only the Docker-container-backed modules are skipped — the
        # Temporal test-server module has its OWN independent honest-skip
        # probe (binary download, not Docker) and must not be swept up here.
        if item_path.name in {
            "test_event_bus_round_trip_e2e.py",
            "test_postgres_persistence_e2e.py",
        }:
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises a real external test-server/container process "
        "(Temporal time-skipping server, testcontainers postgres/redpanda) — "
        "excluded from the blocking `just verify` unit lane.",
    )
