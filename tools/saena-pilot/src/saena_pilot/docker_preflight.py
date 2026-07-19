"""Docker availability + daemon-health preflight (w6-12, wave6-plan §1).

Honesty contract:

- The probe reports exactly what was observed: CLI present or not, daemon
  answering or not, the server version string the daemon itself returned.
- Container-backed verification is claimed available ONLY when the CLI is
  present AND the daemon answered — never inferred, never assumed.
- v1 pilot lanes are container-free by design (wave6-plan §5 R-4): no lane
  in `LANE_DOCKER_REQUIREMENTS` requires Docker. The table is data-driven so
  a future lane that genuinely needs containers flips one boolean and
  `require_docker()` starts failing closed for it.

The probe is a fixed list-argv subprocess (`docker info --format
'{{json .ServerVersion}}'`) with a timeout — never a shell, never influenced
by customer-repo content.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from saena_pilot.errors import ValidationFailedError

#: Probe timeout — a hung daemon must never stall pilot preflight.
DEFAULT_TIMEOUT_SECONDS = 3.0
_MAX_ERROR_DETAIL = 400

#: Pilot lane → does it require a healthy Docker daemon? v1: every pilot
#: lane is container-free by design; stated honestly rather than implied.
LANE_DOCKER_REQUIREMENTS: Mapping[str, bool] = MappingProxyType(
    {
        "preflight": False,
        "audit": False,
        "plan": False,
        "implement": False,
        "verify": False,
        "resume": False,
        "status": False,
    }
)


class DockerUnavailableError(ValidationFailedError):
    """A lane that genuinely requires Docker was requested while Docker is
    absent or the daemon is unhealthy. Fail-closed: the lane must not run
    and must not pretend container-backed verification happened."""

    error_code = "saena.pilot.docker_unavailable"


class UnknownLaneError(ValidationFailedError):
    """A lane name outside `LANE_DOCKER_REQUIREMENTS` — fail-closed rather
    than assuming the unknown lane needs nothing."""

    error_code = "saena.pilot.docker_lane_unknown"


@dataclass(frozen=True, slots=True)
class DockerStatus:
    """Observed Docker state. `server_version` is only ever the string the
    daemon itself reported — None whenever the daemon did not answer."""

    cli_present: bool
    daemon_healthy: bool
    server_version: str | None
    error_detail: str | None

    @property
    def container_verification_available(self) -> bool:
        """True ONLY with a present CLI and an answering daemon."""
        return self.cli_present and self.daemon_healthy

    def to_dict(self) -> dict[str, Any]:
        return {
            "cli_present": self.cli_present,
            "daemon_healthy": self.daemon_healthy,
            "server_version": self.server_version,
            "error_detail": self.error_detail,
            "container_verification_available": self.container_verification_available,
            "note": "v1 pilot lanes are container-free; Docker status is reported for honesty",
        }


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _MAX_ERROR_DETAIL:
        return text[:_MAX_ERROR_DETAIL] + "… (truncated)"
    return text


def probe_docker(*, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> DockerStatus:
    """Detect the docker CLI on PATH and probe daemon health with a bounded
    `docker info` call (list argv, no shell). Never raises."""
    docker = shutil.which("docker")
    if docker is None:
        return DockerStatus(
            cli_present=False,
            daemon_healthy=False,
            server_version=None,
            error_detail="docker CLI not found on PATH",
        )
    argv = [docker, "info", "--format", "{{json .ServerVersion}}"]
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DockerStatus(
            cli_present=True,
            daemon_healthy=False,
            server_version=None,
            error_detail=f"docker info timed out after {timeout_seconds}s",
        )
    except OSError as exc:
        return DockerStatus(
            cli_present=True,
            daemon_healthy=False,
            server_version=None,
            error_detail=f"docker info failed to execute: {type(exc).__name__}",
        )
    if completed.returncode != 0:
        detail = _truncate(completed.stderr or completed.stdout) or (
            f"docker info exited {completed.returncode}"
        )
        return DockerStatus(
            cli_present=True,
            daemon_healthy=False,
            server_version=None,
            error_detail=detail,
        )
    try:
        version = json.loads(completed.stdout.strip())
    except ValueError:
        version = None
    if not isinstance(version, str) or not version:
        return DockerStatus(
            cli_present=True,
            daemon_healthy=False,
            server_version=None,
            error_detail=(
                "docker info returned an unparsable server version: " + _truncate(completed.stdout)
            ),
        )
    return DockerStatus(
        cli_present=True,
        daemon_healthy=True,
        server_version=version,
        error_detail=None,
    )


def lane_requires_docker(
    lane: str, requirements: Mapping[str, bool] = LANE_DOCKER_REQUIREMENTS
) -> bool:
    """Data-driven lane classification. Unknown lanes fail closed."""
    if lane not in requirements:
        raise UnknownLaneError(
            f"unknown pilot lane {lane!r} — not classified in LANE_DOCKER_REQUIREMENTS; "
            "refusing to assume it is container-free",
            context={"lane": lane, "known_lanes": sorted(requirements)},
        )
    return requirements[lane]


def lanes_requiring_docker(
    requirements: Mapping[str, bool] = LANE_DOCKER_REQUIREMENTS,
) -> tuple[str, ...]:
    return tuple(sorted(lane for lane, needed in requirements.items() if needed))


def require_docker(
    lane: str,
    status: DockerStatus,
    requirements: Mapping[str, bool] = LANE_DOCKER_REQUIREMENTS,
) -> None:
    """Fail closed for lanes that genuinely require Docker. For v1's
    container-free lanes this never raises — but it also never upgrades the
    reported status: absence stays visible in the preflight report."""
    if not lane_requires_docker(lane, requirements):
        return
    if not status.container_verification_available:
        raise DockerUnavailableError(
            f"pilot lane {lane!r} requires a healthy Docker daemon; observed "
            f"cli_present={status.cli_present} daemon_healthy={status.daemon_healthy} "
            f"({status.error_detail or 'no detail'}) — refusing to run and refusing to "
            "claim container-backed verification",
            context={"lane": lane, "docker": status.to_dict()},
        )
