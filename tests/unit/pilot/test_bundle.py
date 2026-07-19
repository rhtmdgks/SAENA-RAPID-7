"""Skill-bundle enforcement — fail-closed, no bypass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pilot_fixtures import run_git
from saena_pilot.bundle import enforce_bundle
from saena_pilot.cli import EXIT_BUNDLE_INVALID, EXIT_USAGE, main
from saena_pilot.errors import BundleInvalidError

MANIFEST = Path(".claude") / "skills" / "manifest.json"
VALIDATOR = Path("tools") / "validation" / "skill_manifest.py"


def _commit_all(root: Path) -> None:
    assert run_git(root, "add", "-A").returncode == 0
    assert run_git(root, "commit", "-q", "-m", "mutate fixture").returncode == 0


class TestEnforceBundle:
    def test_valid_fixture_bundle_passes(self, rapid7_root: Path) -> None:
        info = enforce_bundle(rapid7_root)
        assert info.bundle_name == "saena-forge-core"
        assert info.skill_names == ("saena-intake", "saena-security-redteam", "ponytail")
        assert len(info.manifest_sha256) == 64
        assert len(info.validator_invocations) == 2

    def test_missing_manifest_invalid(self, rapid7_root: Path) -> None:
        (rapid7_root / MANIFEST).unlink()
        with pytest.raises(BundleInvalidError, match="manifest missing"):
            enforce_bundle(rapid7_root)

    def test_unparsable_manifest_invalid(self, rapid7_root: Path) -> None:
        (rapid7_root / MANIFEST).write_text("{broken", encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="unparsable"):
            enforce_bundle(rapid7_root)

    def test_wrong_schema_version_invalid(self, rapid7_root: Path) -> None:
        manifest = json.loads((rapid7_root / MANIFEST).read_text(encoding="utf-8"))
        manifest["schema_version"] = "saena.skill-manifest/v0"
        (rapid7_root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="schema_version"):
            enforce_bundle(rapid7_root)

    def test_empty_skill_list_invalid(self, rapid7_root: Path) -> None:
        manifest = json.loads((rapid7_root / MANIFEST).read_text(encoding="utf-8"))
        manifest["skills"] = []
        (rapid7_root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="no skills"):
            enforce_bundle(rapid7_root)

    def test_validator_script_absent_invalid(self, rapid7_root: Path) -> None:
        (rapid7_root / VALIDATOR).unlink()
        with pytest.raises(BundleInvalidError, match="validator missing"):
            enforce_bundle(rapid7_root)

    def test_validator_rejects_missing_skill_dir(self, rapid7_root: Path) -> None:
        # Manifest lists a skill whose SKILL.md does not exist on disk →
        # the fixture validator's validate-skills leg exits nonzero.
        manifest = json.loads((rapid7_root / MANIFEST).read_text(encoding="utf-8"))
        manifest["skills"].append({"name": "saena-ghost", "version": "0.1.0"})
        (rapid7_root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="validator rejected"):
            enforce_bundle(rapid7_root)


class TestNoBypass:
    def _audit_argv(self, customer_repo: Path) -> list[str]:
        return [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            "https://customer.example",
            "--mode",
            "audit",
            "--dry-run",
        ]

    @pytest.mark.parametrize(
        "flag", ["--skip-bundle", "--no-bundle", "--skip-bundle-check", "--bundle-bypass"]
    )
    def test_parser_rejects_skip_bundle_ish_flags(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        flag: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main([*self._audit_argv(customer_repo), flag])
        assert exit_code == EXIT_USAGE
        capsys.readouterr()

    def test_env_var_bypass_has_no_effect(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (rapid7_root / MANIFEST).unlink()
        _commit_all(rapid7_root)
        monkeypatch.setenv("SAENA_SKIP_BUNDLE", "1")
        monkeypatch.setenv("SAENA_PILOT_SKIP_BUNDLE", "1")
        exit_code = main(self._audit_argv(customer_repo))
        assert exit_code == EXIT_BUNDLE_INVALID
        assert "manifest missing" in capsys.readouterr().err

    def test_cli_fails_closed_when_validator_missing(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (rapid7_root / VALIDATOR).unlink()
        _commit_all(rapid7_root)
        exit_code = main(self._audit_argv(customer_repo))
        assert exit_code == EXIT_BUNDLE_INVALID
        assert "validator missing" in capsys.readouterr().err
