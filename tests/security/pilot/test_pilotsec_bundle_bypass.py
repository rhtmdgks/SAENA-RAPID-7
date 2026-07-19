"""Attack 10, 11 & 12 — skill/manifest tampering, hook disabling, bundle bypass.

The pilot refuses to start unless a positively-validated skill bundle exists,
fail-closed with NO bypass path. Claims proven:
- A tampered manifest (bad schema / empty skills / unnamed entry / missing
  file) -> `EXIT_BUNDLE_INVALID` (4).
- A missing validator script -> `EXIT_BUNDLE_INVALID`.
- A validator that reports a skill-quality failure (injected runner) ->
  `EXIT_BUNDLE_INVALID` — the pilot cannot start.
- `SAENA_SKIP_BUNDLE=1` does NOT bypass enforcement.
- The real `skill_bundle.py enforce` gate fails-closed on a declared subset
  and on an unknown-skill superset, and ignores `SAENA_SKIP_BUNDLE`.
- Hook disabling (`.claude/hooks/DISABLED`) — currently NOT surfaced by the
  pilot: documented as an xfail FINDING for the Integrator.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from saena_pilot.bundle import enforce_bundle
from saena_pilot.cli import EXIT_BUNDLE_INVALID, EXIT_OK, main
from saena_pilot.errors import BundleInvalidError

DOMAIN = "https://customer.example"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILL_BUNDLE = _REPO_ROOT / "tools" / "validation" / "skill_bundle.py"
_CANONICAL_SKILLS = [
    "saena-intake",
    "saena-security-redteam",
    "saena-site-discovery",
    "saena-demand-graph",
    "saena-b2b-saas-entity",
    "saena-claim-evidence",
    "saena-chatgpt-search",
    "saena-technical-aeo",
    "saena-answer-capsule",
    "saena-schema-fidelity",
    "ponytail",
    "saena-content-fidelity",
    "saena-accessibility-visual",
    "saena-patch-review",
    "saena-rollback",
    "ponytail-review",
]


def _audit(customer: Path) -> list[str]:
    return ["--customer-repo", str(customer), "--domain", DOMAIN, "--mode", "audit", "--dry-run"]


def _manifest_path(rapid7_root: Path) -> Path:
    return rapid7_root / ".claude" / "skills" / "manifest.json"


class TestTamperedManifestFailsClosed:
    def test_bad_schema_version(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mp = _manifest_path(rapid7_root)
        data = json.loads(mp.read_text(encoding="utf-8"))
        data["schema_version"] = "saena.skill-manifest/v999"
        mp.write_text(json.dumps(data), encoding="utf-8")
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_empty_skills_list(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mp = _manifest_path(rapid7_root)
        data = json.loads(mp.read_text(encoding="utf-8"))
        data["skills"] = []
        mp.write_text(json.dumps(data), encoding="utf-8")
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_skill_without_name(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mp = _manifest_path(rapid7_root)
        data = json.loads(mp.read_text(encoding="utf-8"))
        data["skills"] = [{"version": "0.1.0"}]  # no name
        mp.write_text(json.dumps(data), encoding="utf-8")
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_unparsable_manifest(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _manifest_path(rapid7_root).write_text("{not json", encoding="utf-8")
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_missing_manifest(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _manifest_path(rapid7_root).unlink()
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_missing_validator_script(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (rapid7_root / "tools" / "validation" / "skill_manifest.py").unlink()
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_removed_skill_md_directory(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # SKILL.md declared in the manifest but missing on disk -> validate-skills
        # subprocess fails -> BundleInvalid.
        (rapid7_root / ".claude" / "skills" / "ponytail" / "SKILL.md").unlink()
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()


class TestValidatorQualityFailureFailsClosed:
    def test_injected_validator_failure_blocks_start(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def failing_runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            # Stand in for a skill-quality failure from the real validator.
            return subprocess.CompletedProcess(list(argv), 2, "skill quality FAIL", "")

        exit_code = main(_audit(customer_repo), bundle_runner=failing_runner)
        assert exit_code == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_enforce_bundle_raises_on_validator_failure(self, rapid7_root: Path) -> None:
        def failing_runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(list(argv), 1, "nope", "")

        with pytest.raises(BundleInvalidError):
            enforce_bundle(rapid7_root, runner=failing_runner)


class TestNoBypassEnvVar:
    def test_skip_env_does_not_bypass_tampered_bundle(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("SAENA_SKIP_BUNDLE", "1")
        mp = _manifest_path(rapid7_root)
        data = json.loads(mp.read_text(encoding="utf-8"))
        data["schema_version"] = "bogus"
        mp.write_text(json.dumps(data), encoding="utf-8")
        # Env var is ignored — the tampered bundle still fails closed.
        assert main(_audit(customer_repo)) == EXIT_BUNDLE_INVALID
        capsys.readouterr()

    def test_skip_env_does_not_bypass_valid_bundle_flow(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("SAENA_SKIP_BUNDLE", "1")
        # A valid bundle still runs the full enforcement (env has no effect).
        assert main(_audit(customer_repo)) == EXIT_OK
        capsys.readouterr()

    def test_pilot_bundle_source_consults_no_bypass_env(self) -> None:
        import saena_pilot.bundle as bundle_mod

        src = Path(bundle_mod.__file__).read_text(encoding="utf-8")
        # No environment read anywhere in the enforcement module.
        assert "os.environ" not in src
        assert "getenv" not in src


class TestRealSkillBundleGateFailsClosed:
    """Attack 12 — reuse the canonical `skill_bundle.py enforce` behavior."""

    def _enforce(self, declared: str | None, env: dict[str, str] | None = None):
        argv = [sys.executable, str(_SKILL_BUNDLE), "enforce"]
        stdin = None
        if declared is not None:
            argv += ["--declared", "-"]
            stdin = declared
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            env={**os.environ, **(env or {})},
            check=False,
        )

    def test_canonical_declared_set_passes(self) -> None:
        result = self._enforce(json.dumps(_CANONICAL_SKILLS))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_declared_subset_fails_closed(self) -> None:
        result = self._enforce(json.dumps(_CANONICAL_SKILLS[:3]))
        assert result.returncode == 4  # EXIT_BUNDLE_VIOLATION

    def test_declared_superset_unknown_skill_fails_closed(self) -> None:
        result = self._enforce(json.dumps([*_CANONICAL_SKILLS, "EXTRA-UNKNOWN"]))
        assert result.returncode == 4
        assert "EXTRA-UNKNOWN" in result.stdout + result.stderr

    def test_skip_env_ignored_and_reported(self) -> None:
        result = self._enforce(None, env={"SAENA_SKIP_BUNDLE": "1"})
        assert result.returncode == 0  # still fully enforced
        assert "SAENA_SKIP_BUNDLE" in result.stderr
        assert "IGNORED" in result.stderr


class TestHookDisablingSurfaced:
    def test_disabled_hooks_marker_surfaces_as_finding(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # FINDING-HOOKS-DISABLED (w6-13) FIXED at integration: the pilot's
        # report now includes `assess_hooks_health`, which surfaces a
        # `.claude/hooks/DISABLED` marker as a WARN in preflight/audit output.
        hooks_dir = rapid7_root / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "DISABLED").write_text("disabled\n", encoding="utf-8")
        result = main(_audit(customer_repo) + ["--json"])
        assert result == EXIT_OK
        report = json.loads(capsys.readouterr().out)["report"]
        assert report["hooks_health"]["hooks_disabled"] is True
        assert any("DISABLED" in w for w in report["hooks_health"]["warnings"])
