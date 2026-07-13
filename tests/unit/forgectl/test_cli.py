"""`saena_forgectl.cli.main` — argparse dispatch, exit codes, `--json`,
clean error handling for a malformed values file (no traceback surfaced).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import fixture_path
from saena_forgectl.cli import (
    EXIT_CHECKS_FAILED,
    EXIT_OK,
    EXIT_VALUES_FILE_INVALID,
    main,
)


class TestPreflightExitCodes:
    def test_passing_fixture_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["preflight", "--values", str(fixture_path("values-passing.yaml"))])
        assert exit_code == EXIT_OK
        captured = capsys.readouterr()
        assert "all checks passed" in captured.out

    def test_google_flag_fixture_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            ["preflight", "--values", str(fixture_path("values-fail-google-flag.yaml"))]
        )
        assert exit_code == EXIT_CHECKS_FAILED
        captured = capsys.readouterr()
        assert "engine_flags" in captured.out
        assert "FAILED" in captured.out

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "values-fail-google-flag.yaml",
            "values-fail-plaintext-secret.yaml",
            "values-fail-missing-digest.yaml",
            "values-fail-no-network-policy.yaml",
            "values-fail-sa-cluster-admin.yaml",
            "values-fail-irreversible-migration.yaml",
        ],
    )
    def test_every_fail_fixture_exits_nonzero(
        self, fixture_name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["preflight", "--values", str(fixture_path(fixture_name))])
        assert exit_code == EXIT_CHECKS_FAILED

    def test_malformed_values_file_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["preflight", "--values", str(fixture_path("values-malformed.yaml"))])
        assert exit_code == EXIT_VALUES_FILE_INVALID
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "Traceback" not in captured.out

    def test_missing_file_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["preflight", "--values", "/nonexistent/path/values.yaml"])
        assert exit_code == EXIT_VALUES_FILE_INVALID
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err


class TestJsonOutput:
    def test_json_flag_produces_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["preflight", "--values", str(fixture_path("values-passing.yaml")), "--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["passed"] is True
        assert len(payload["checks"]) == 6

    def test_json_flag_on_failing_fixture(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(
            [
                "preflight",
                "--values",
                str(fixture_path("values-fail-google-flag.yaml")),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["passed"] is False
        assert "engine_flags" in payload["failed_check_names"]

    def test_json_flag_on_malformed_values_is_still_valid_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            ["preflight", "--values", str(fixture_path("values-malformed.yaml")), "--json"]
        )
        assert exit_code == EXIT_VALUES_FILE_INVALID
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error_code"] == "saena.forgectl.values_file_invalid"


class TestLiveFlagsAcceptedAsNoop:
    """The §8.1 example invocation passes --verify-signatures
    --check-network-policy --check-external-secrets --check-registry —
    these must not be rejected as unknown flags even though this
    implementation is static-only."""

    def test_example_invocation_flags_accepted(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(
            [
                "preflight",
                "--values",
                str(fixture_path("values-passing.yaml")),
                "--verify-signatures",
                "--check-network-policy",
                "--check-external-secrets",
                "--check-registry",
            ]
        )
        assert exit_code == EXIT_OK
        captured = capsys.readouterr()
        assert "static preflight" in captured.out

    def test_json_records_live_flags_as_noop(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(
            [
                "preflight",
                "--values",
                str(fixture_path("values-passing.yaml")),
                "--verify-signatures",
                "--json",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "--verify-signatures" in payload["live_flags_accepted_as_noop"]


class TestVersionFlag:
    def test_version_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestNoSubcommandPrintsHelp:
    def test_returns_ok_and_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([])
        assert exit_code == EXIT_OK
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()


class TestModuleEntryPoint:
    """`python -m saena_forgectl preflight ...` end-to-end, exercised as a
    real subprocess against the shared venv's interpreter — proves the
    packaging/sys.path story actually works outside the pytest process,
    not merely via direct `main()` calls."""

    def test_module_invocation_passing_fixture(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        forgectl_src = str(repo_root / "tools" / "forgectl" / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "saena_forgectl",
                "preflight",
                "--values",
                str(fixture_path("values-passing.yaml")),
            ],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": forgectl_src, **_minimal_env()},
        )
        assert result.returncode == EXIT_OK, result.stderr
        assert "all checks passed" in result.stdout


def _minimal_env() -> dict[str, str]:
    import os

    # Keep the real PATH/venv-selecting env vars so `sys.executable`
    # resolves the same interpreter pytest itself is running under (with
    # pyyaml/saena-schemas already installed), only adding PYTHONPATH.
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
