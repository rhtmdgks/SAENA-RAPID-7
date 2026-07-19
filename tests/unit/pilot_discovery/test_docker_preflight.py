"""Docker preflight: PATH-shim matrix (present-healthy / present-sick /
absent / garbage / timeout), lane classification, fail-closed require_docker.
No real Docker is required — one opportunistic test uses it only if it
answers quickly."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from _discovery_fixtures import make_docker_shim
from saena_pilot.docker_preflight import (
    LANE_DOCKER_REQUIREMENTS,
    DockerStatus,
    DockerUnavailableError,
    UnknownLaneError,
    lane_requires_docker,
    lanes_requiring_docker,
    probe_docker,
    require_docker,
)


@pytest.fixture
def shim_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def _install(kind: str) -> None:
        bin_dir = tmp_path / f"bin-{kind}"
        make_docker_shim(bin_dir, kind)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")

    return _install


class TestProbe:
    def test_absent_cli(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        status = probe_docker()
        assert status.cli_present is False
        assert status.daemon_healthy is False
        assert status.server_version is None
        assert "not found on PATH" in (status.error_detail or "")

    def test_present_healthy(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("healthy")
        status = probe_docker()
        assert status.cli_present is True
        assert status.daemon_healthy is True
        assert status.server_version == "28.1.1"
        assert status.error_detail is None

    def test_present_sick_daemon(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("sick")
        status = probe_docker()
        assert status.cli_present is True
        assert status.daemon_healthy is False
        assert status.server_version is None
        assert "Cannot connect to the Docker daemon" in (status.error_detail or "")

    def test_garbage_output_is_unhealthy_not_a_crash(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("garbage")
        status = probe_docker()
        assert status.cli_present is True
        assert status.daemon_healthy is False
        assert "unparsable server version" in (status.error_detail or "")

    def test_empty_version_is_unhealthy(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("empty")
        status = probe_docker()
        assert status.daemon_healthy is False

    def test_hung_daemon_times_out(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("slow")
        status = probe_docker(timeout_seconds=0.4)
        assert status.cli_present is True
        assert status.daemon_healthy is False
        assert "timed out" in (status.error_detail or "")


class TestHonestClaims:
    def test_never_claims_container_verification_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        status = probe_docker()
        assert status.container_verification_available is False
        assert status.to_dict()["container_verification_available"] is False

    def test_never_claims_container_verification_when_sick(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("sick")
        assert probe_docker().container_verification_available is False

    def test_claims_only_when_cli_and_daemon_agree(self) -> None:
        healthy = DockerStatus(True, True, "28.0.0", None)
        assert healthy.container_verification_available is True
        assert DockerStatus(True, False, None, "down").container_verification_available is False
        assert DockerStatus(False, False, None, "gone").container_verification_available is False

    def test_to_dict_shape(self, shim_path) -> None:  # type: ignore[no-untyped-def]
        shim_path("healthy")
        payload = probe_docker().to_dict()
        assert set(payload) == {
            "cli_present",
            "daemon_healthy",
            "server_version",
            "error_detail",
            "container_verification_available",
            "note",
        }
        assert "container-free" in payload["note"]


class TestLanes:
    def test_v1_pilot_lanes_are_container_free(self) -> None:
        assert set(LANE_DOCKER_REQUIREMENTS) == {
            "preflight",
            "audit",
            "plan",
            "implement",
            "verify",
            "resume",
            "status",
        }
        assert not any(LANE_DOCKER_REQUIREMENTS.values())
        assert lanes_requiring_docker() == ()

    def test_known_lane_classification(self) -> None:
        assert lane_requires_docker("audit") is False
        assert lane_requires_docker("verify") is False

    def test_unknown_lane_fails_closed(self) -> None:
        with pytest.raises(UnknownLaneError):
            lane_requires_docker("container-verify")

    def test_require_docker_passes_for_container_free_lane_even_when_absent(self) -> None:
        absent = DockerStatus(False, False, None, "docker CLI not found on PATH")
        require_docker("audit", absent)  # must not raise — lane is container-free

    def test_require_docker_fails_closed_for_docker_lane_when_unhealthy(self) -> None:
        requirements = {"container-verify": True}
        sick = DockerStatus(True, False, None, "daemon down")
        with pytest.raises(DockerUnavailableError) as excinfo:
            require_docker("container-verify", sick, requirements)
        assert "refusing" in str(excinfo.value)

    def test_require_docker_allows_docker_lane_when_healthy(self) -> None:
        requirements = {"container-verify": True}
        healthy = DockerStatus(True, True, "28.0.0", None)
        require_docker("container-verify", healthy, requirements)  # no raise

    def test_require_docker_unknown_lane_fails_closed(self) -> None:
        healthy = DockerStatus(True, True, "28.0.0", None)
        with pytest.raises(UnknownLaneError):
            require_docker("mystery-lane", healthy)


class TestOpportunisticRealDocker:
    def test_real_docker_parse_if_it_answers_fast(self) -> None:
        """Integration-free opportunistic check: only runs against real Docker
        when the CLI is on PATH; the probe is bounded at 3s either way and its
        result invariants must hold whatever the daemon state is."""
        if shutil.which("docker") is None:
            pytest.skip("real docker CLI not on PATH — shim matrix covers this")
        status = probe_docker(timeout_seconds=3.0)
        assert status.cli_present is True
        if status.daemon_healthy:
            assert isinstance(status.server_version, str) and status.server_version
            assert status.error_detail is None
        else:
            assert status.server_version is None
            assert status.error_detail
