"""Adversarial bypass corpus: env overrides, direct calls, unknown flags.

The gate must have NO bypass path — identical behavior with hostile env vars
set, full validation even via the library entry point, and usage errors for
any flag argparse does not know.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bundle_fixtures import (
    run_cli,
    skill_bundle,
    write_bundle,
    write_manifest,
)

_BYPASS_ENV = {
    "SAENA_SKIP_BUNDLE": "1",
    "SKILL_BUNDLE_ALLOW_PARTIAL": "1",
    "SAENA_BUNDLE_BYPASS": "true",
    "SKILL_BUNDLE_SKIP": "yes",
}


def _set_bypass_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _BYPASS_ENV.items():
        monkeypatch.setenv(key, value)


def _argv(manifest_path: Path, skills_root: Path) -> list[str]:
    return ["enforce", "--manifest", str(manifest_path), "--skills-root", str(skills_root)]


class TestEnvOverrideIsIgnored:
    def test_bad_tree_still_fails_with_bypass_env(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        manifest_data: dict[str, Any],
    ) -> None:
        """(f) Hostile env vars must not rescue a partial bundle."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data, skip={"saena-intake"})
        baseline_code, baseline_out = run_cli(capsys, _argv(manifest_path, skills_root))
        _set_bypass_env(monkeypatch)
        code, out = run_cli(capsys, _argv(manifest_path, skills_root))
        assert baseline_code == skill_bundle.EXIT_SKILLS_INVALID
        assert code == baseline_code
        assert out == baseline_out  # stdout byte-identical: env changes nothing

    def test_good_tree_still_passes_with_bypass_env(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        manifest_data: dict[str, Any],
    ) -> None:
        """(f) ...and must not corrupt a green run either (prove both ways)."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        baseline_code, baseline_out = run_cli(capsys, _argv(manifest_path, skills_root))
        _set_bypass_env(monkeypatch)
        code, out = run_cli(capsys, _argv(manifest_path, skills_root))
        assert baseline_code == skill_bundle.EXIT_OK
        assert code == baseline_code
        assert out == baseline_out

    def test_bypass_env_is_reported_as_ignored_on_stderr(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        manifest_data: dict[str, Any],
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        _set_bypass_env(monkeypatch)
        code = skill_bundle.main(_argv(manifest_path, skills_root))
        captured = capsys.readouterr()
        assert code == skill_bundle.EXIT_OK
        for key in _BYPASS_ENV:
            assert key in captured.err
        assert "IGNORED" in captured.err

    def test_module_never_branches_on_environment(self) -> None:
        """Source-level guard: no os.getenv anywhere; os.environ appears only
        in the stderr reporting helper (which cannot change behavior)."""
        source = Path(skill_bundle.__file__).read_text(encoding="utf-8")
        assert "os.getenv" not in source
        assert source.count("os.environ") == 1
        helper = source.split("def _report_ignored_bypass_env", 1)[1]
        assert "os.environ" in helper.split("def ", 1)[0]


class TestDirectLibraryCall:
    def test_direct_call_on_tampered_tree_fails(
        self, tmp_path: Path, manifest_data: dict[str, Any]
    ) -> None:
        """(g) enforce_bundle() itself runs full validation — no CLI-only checks."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data, skip={"ponytail"})
        report = skill_bundle.enforce_bundle(manifest_path, skills_root)
        assert not report.ok
        assert report.exit_code == skill_bundle.EXIT_SKILLS_INVALID
        assert report.fingerprint is None
        assert any(f.where == "ponytail" for f in report.findings)

    def test_direct_call_on_tampered_manifest_fails(
        self, tmp_path: Path, manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["skills"] = manifest_data["skills"][:4]
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        report = skill_bundle.enforce_bundle(manifest_path, skills_root)
        assert report.exit_code == skill_bundle.EXIT_MANIFEST_INVALID
        assert report.fingerprint is None

    def test_direct_call_with_declared_subset_fails(
        self, tmp_path: Path, manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        names = [entry["name"] for entry in manifest_data["skills"]]
        report = skill_bundle.enforce_bundle(manifest_path, skills_root, names[:5])
        assert report.exit_code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert report.fingerprint is None

    def test_direct_call_on_green_tree_yields_fingerprint(
        self, tmp_path: Path, manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        report = skill_bundle.enforce_bundle(manifest_path, skills_root)
        assert report.ok
        assert report.exit_code == skill_bundle.EXIT_OK
        assert isinstance(report.fingerprint, str) and len(report.fingerprint) == 64

    def test_enforce_bundle_has_no_skip_parameter(self) -> None:
        """API-surface guard: no argument of enforce_bundle can disable checks."""
        import inspect

        params = set(inspect.signature(skill_bundle.enforce_bundle).parameters)
        assert params == {"manifest", "skills_root", "declared"}


class TestUsageErrors:
    def test_unknown_flag_is_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """(k) There is no --skip-checks; unknown flags exit EXIT_USAGE."""
        code, _ = run_cli(capsys, ["enforce", "--skip-checks"])
        assert code == skill_bundle.EXIT_USAGE

    def test_allow_partial_flag_does_not_exist(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = run_cli(capsys, ["enforce", "--allow-partial"])
        assert code == skill_bundle.EXIT_USAGE

    def test_unknown_subcommand_is_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = run_cli(capsys, ["bypass"])
        assert code == skill_bundle.EXIT_USAGE

    def test_no_arguments_is_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = run_cli(capsys, [])
        assert code == skill_bundle.EXIT_USAGE

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = run_cli(capsys, ["--help"])
        assert code == skill_bundle.EXIT_OK

    def test_exit_codes_are_distinct(self) -> None:
        codes = {
            skill_bundle.EXIT_OK,
            skill_bundle.EXIT_MANIFEST_INVALID,
            skill_bundle.EXIT_SKILLS_INVALID,
            skill_bundle.EXIT_USAGE,
            skill_bundle.EXIT_BUNDLE_VIOLATION,
        }
        assert codes == {0, 1, 2, 3, 4}
