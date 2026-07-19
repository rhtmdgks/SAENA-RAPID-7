"""Canonical bundle enforcement: fail-closed on empty/partial/unknown/tamper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from bundle_fixtures import (
    REAL_MANIFEST_PATH,
    REAL_SKILLS_ROOT,
    make_skill_md,
    run_cli,
    skill_bundle,
    write_bundle,
    write_manifest,
)

_REPORT_KEYS = {
    "schema_version",
    "command",
    "manifest",
    "skills_root",
    "declared",
    "ok",
    "exit_code",
    "checked_skills",
    "fingerprint",
    "errors",
}


def _enforce(
    capsys: pytest.CaptureFixture[str],
    manifest_path: Path,
    skills_root: Path,
    *extra: str,
) -> tuple[int, str]:
    return run_cli(
        capsys,
        [
            "enforce",
            "--manifest",
            str(manifest_path),
            "--skills-root",
            str(skills_root),
            *extra,
        ],
    )


class TestGreenPath:
    def test_synthetic_tree_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_OK
        assert "RESULT: PASS" in out
        assert "bundle fingerprint: " in out

    def test_real_repo_tree_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """(l) The real checked-in tree is itself regression-tested green."""
        code, out = _enforce(capsys, REAL_MANIFEST_PATH, REAL_SKILLS_ROOT)
        assert code == skill_bundle.EXIT_OK
        assert "RESULT: PASS" in out

    def test_real_repo_tree_fingerprint_stable_across_runs(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code1, out1 = _enforce(capsys, REAL_MANIFEST_PATH, REAL_SKILLS_ROOT, "--json")
        code2, out2 = _enforce(capsys, REAL_MANIFEST_PATH, REAL_SKILLS_ROOT, "--json")
        assert code1 == code2 == skill_bundle.EXIT_OK
        fp1 = json.loads(out1)["fingerprint"]
        fp2 = json.loads(out2)["fingerprint"]
        assert fp1 == fp2
        assert isinstance(fp1, str) and len(fp1) == 64
        int(fp1, 16)  # 64 hex chars

    def test_json_report_shape_on_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root, "--json")
        report = json.loads(out)
        assert code == 0
        assert set(report) == _REPORT_KEYS
        assert report["schema_version"] == "saena.skill-bundle-report/v1"
        assert report["command"] == "enforce"
        assert report["ok"] is True
        assert report["exit_code"] == 0
        assert report["checked_skills"] == 16
        assert report["declared"] is None
        assert report["errors"] == []
        assert isinstance(report["fingerprint"], str) and len(report["fingerprint"]) == 64


class TestSkillsStageFailClosed:
    def test_empty_bundle_dir_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(a) An existing but empty skills root: every mandatory skill missing."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert "skill-missing-on-disk" in out
        assert "RESULT: FAIL" in out

    def test_missing_bundle_dir_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        code, out = _enforce(capsys, manifest_path, tmp_path / "no-such-dir")
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert "RESULT: FAIL" in out

    def test_partial_bundle_names_the_missing_skill(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(b) One SKILL.md removed: FAIL and the report names it."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data, skip={"saena-rollback"})
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert "saena-rollback" in out
        assert "skill-missing-on-disk" in out

    def test_unknown_extra_skill_dir_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(c) A 17th on-disk skill not in the manifest: FAIL naming it."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        rogue = skills_root / "saena-rogue-skill"
        rogue.mkdir()
        (rogue / "SKILL.md").write_text(make_skill_md("saena-rogue-skill"), encoding="utf-8")
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert "saena-rogue-skill" in out
        assert "skill-not-in-manifest" in out

    def test_quality_tampered_skill_file_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """A SKILL.md gutted below the quality contract fails the skills stage."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(
            tmp_path / "skills",
            manifest_data,
            contents={"ponytail": "---\nname: ponytail\ndescription: stub\n---\n\n## Purpose\nx\n"},
        )
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert "RESULT: FAIL" in out


class TestManifestStageFailClosed:
    def test_manifest_tampered_name_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(h) Renaming one manifest entry breaks the mandatory 16-skill set."""
        manifest_data["skills"][0]["name"] = "saena-intake-evil"
        manifest_data["skills"][0]["path"] = ".claude/skills/saena-intake-evil/SKILL.md"
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert "missing-mandatory-skill" in out

    def test_manifest_tampered_phase_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(h) Moving a skill to the wrong phase is manifest tamper."""
        for entry in manifest_data["skills"]:
            if entry["name"] == "saena-patch-review":
                entry["phase"] = "plan"
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert "wrong-mandatory-phase" in out

    def test_emptied_phase_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(j) Deleting every bootstrap skill empties a phase_order phase."""
        manifest_data["skills"] = [
            entry for entry in manifest_data["skills"] if entry["phase"] != "bootstrap"
        ]
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert "missing-mandatory-skill" in out

    def test_malformed_manifest_json_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("{not json", encoding="utf-8")
        code, out = _enforce(capsys, manifest_path, tmp_path)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert "malformed-json" in out

    def test_missing_manifest_file_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _enforce(capsys, tmp_path / "nope.json", tmp_path)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert "unreadable" in out

    def test_json_report_shape_on_fail_has_no_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["bundle_name"] = "not-the-bundle"
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _enforce(capsys, manifest_path, skills_root, "--json")
        report = json.loads(out)
        assert code == skill_bundle.EXIT_MANIFEST_INVALID
        assert set(report) == _REPORT_KEYS
        assert report["ok"] is False
        assert report["fingerprint"] is None
        assert report["errors"]
        for err in report["errors"]:
            assert set(err) == {"stage", "code", "where", "message"}
            assert err["stage"] == "manifest"
