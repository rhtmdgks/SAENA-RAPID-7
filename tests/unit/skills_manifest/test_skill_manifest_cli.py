"""CLI surface: exit-code map, usage handling, and the --json report shape."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _manifest_fixtures import (
    REAL_MANIFEST_PATH,
    run_cli,
    skill_manifest,
    write_bundle,
    write_manifest,
)

_REPORT_KEYS = {
    "schema_version",
    "command",
    "manifest",
    "skills_root",
    "ok",
    "exit_code",
    "checked_skills",
    "errors",
}


class TestUsageExitCode:
    def test_no_arguments(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert skill_manifest.main([]) == skill_manifest.EXIT_USAGE

    def test_unknown_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert skill_manifest.main(["frobnicate"]) == skill_manifest.EXIT_USAGE

    def test_missing_required_option(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert skill_manifest.main(["validate-manifest"]) == skill_manifest.EXIT_USAGE

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert skill_manifest.main(["--help"]) == skill_manifest.EXIT_OK

    def test_exit_codes_are_distinct(self) -> None:
        codes = {
            skill_manifest.EXIT_OK,
            skill_manifest.EXIT_MANIFEST_INVALID,
            skill_manifest.EXIT_SKILLS_INVALID,
            skill_manifest.EXIT_USAGE,
        }
        assert codes == {0, 1, 2, 3}


class TestJsonShape:
    def test_validate_manifest_success_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run_cli(
            capsys, ["validate-manifest", "--manifest", str(REAL_MANIFEST_PATH), "--json"]
        )
        report = json.loads(out)
        assert code == 0
        assert set(report) == _REPORT_KEYS
        assert report["schema_version"] == skill_manifest.REPORT_SCHEMA_VERSION
        assert report["command"] == "validate-manifest"
        assert report["ok"] is True
        assert report["exit_code"] == 0
        assert report["skills_root"] is None
        assert report["errors"] == []

    def test_validate_manifest_failure_shape(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["bundle_name"] = "not-the-bundle"
        path = write_manifest(tmp_path, manifest_data)
        code, out = run_cli(capsys, ["validate-manifest", "--manifest", str(path), "--json"])
        report = json.loads(out)
        assert code == skill_manifest.EXIT_MANIFEST_INVALID
        assert set(report) == _REPORT_KEYS
        assert report["ok"] is False
        assert report["exit_code"] == skill_manifest.EXIT_MANIFEST_INVALID
        assert report["errors"], "failure report must carry at least one error"
        for err in report["errors"]:
            assert set(err) == {"code", "where", "message"}

    def test_validate_skills_success_shape(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = run_cli(
            capsys,
            [
                "validate-skills",
                "--manifest",
                str(manifest_path),
                "--skills-root",
                str(skills_root),
                "--json",
            ],
        )
        report = json.loads(out)
        assert code == 0
        assert set(report) == _REPORT_KEYS
        assert report["command"] == "validate-skills"
        assert report["skills_root"] == str(skills_root)
        assert report["checked_skills"] == 16

    def test_human_report_mentions_result(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run_cli(capsys, ["validate-manifest", "--manifest", str(REAL_MANIFEST_PATH)])
        assert code == 0
        assert "RESULT: PASS" in out
