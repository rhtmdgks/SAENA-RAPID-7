"""pytest fixtures for `tests/integration/bus` (w2-18).

Spec basis: ADR-0017 (testcontainers-python, W2A+), ADR-0004 (Redpanda = data
pool component — this suite runs the REAL `redpandadata/redpanda` image, not
the generic Confluent-Kafka-based `testcontainers.kafka.KafkaContainer`,
since ADR-0004 names Redpanda specifically as this system's broker).

Registers the `integration` marker locally — same rationale as
`tests/integration/orchestrator/conftest.py`'s own docstring: the root
`pyproject.toml` `[tool.pytest.ini_options]` markers list is outside this
patch unit's exclusive write paths, so this conftest's own
`pytest_configure` hook is the only in-scope place to register it.

Honest skip (task spec "probe + honest skip otherwise"): every test in this
package is marked `pytest.mark.integration`. If the Docker daemon is not
reachable, the whole package is skipped via `pytest_collection_modifyitems`
below (probed once via a raw socket connect to the Docker socket/TCP host,
mirroring `tests/integration/persistence_postgres/conftest.py`'s own
`_docker_available` probe exactly) — never by attempting a container start
and swallowing the resulting exception.

One `redpandadata/redpanda` testcontainer per test SESSION (broker startup
is the expensive part). `redpanda_container` is `DockerContainer`-based
(generic testcontainers API, not a dedicated `testcontainers.redpanda`
module — that module does not exist in the pinned `testcontainers` version,
confirmed by import probe) rather than
`testcontainers.kafka.KafkaContainer` — the generic container lets this
fixture run the actual `redpandadata/redpanda` image directly. A fixed,
dynamically-chosen free host port is bound BEFORE container start
(`with_bind_ports`) so the container's `--advertise-kafka-addr` can be set to
the exact host:port aiokafka clients will connect through — Redpanda (like
Kafka) requires the advertised address to match what clients actually dial,
or the initial metadata handshake succeeds but the subsequent produce/fetch
redirect fails.
"""

from __future__ import annotations

import contextlib
import os
import socket
from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs


def _docker_available() -> bool:
    """Probe the Docker daemon socket directly — mirrors
    `tests/integration/persistence_postgres/conftest.py::_docker_available`
    exactly (same rationale: never start a container just to find out)."""
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


_DOCKER_AVAILABLE = _docker_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _DOCKER_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(reason="Docker daemon not reachable — honest skip (ADR-0017)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: real-I/O test requiring a reachable Docker daemon "
        "(ADR-0017) — exercises a real redpandadata/redpanda container.",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def redpanda_bootstrap_servers() -> Iterator[str]:
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker daemon not reachable — honest skip (ADR-0017)")

    kafka_port = _free_port()
    container = DockerContainer("redpandadata/redpanda:latest")
    container.with_bind_ports(9092, kafka_port)
    container.with_command(
        "redpanda start --smp 1 --memory 512M --overprovisioned --node-id 0 "
        "--check=false --kafka-addr PLAINTEXT://0.0.0.0:9092 "
        f"--advertise-kafka-addr PLAINTEXT://127.0.0.1:{kafka_port} "
        "--pandaproxy-addr 0.0.0.0:8082 --schema-registry-addr 0.0.0.0:8081"
    )
    container.start()
    try:
        wait_for_logs(container, "Successfully started Redpanda!", timeout=60)
        yield f"127.0.0.1:{kafka_port}"
    finally:
        with contextlib.suppress(Exception):
            container.stop()
