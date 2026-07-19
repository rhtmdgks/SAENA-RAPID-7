"""Drift gate (`check`) tests: real-tree regression + fail-closed mutations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT, load_json, run_cli, skill_pack_sync


def _check(capsys: pytest.CaptureFixture[str], root: Path) -> tuple[int, str]:
    return run_cli(capsys, ["check", "--repo-root", str(root)])


def _codes(out: str) -> set[str]:
    report = json.loads(out)
    return {error["code"] for error in report["errors"]}


def _check_json(capsys: pytest.CaptureFixture[str], root: Path) -> tuple[int, dict[str, Any]]:
    code, out = run_cli(capsys, ["check", "--repo-root", str(root), "--json"])
    report = json.loads(out)
    assert isinstance(report, dict)
    return code, report


class TestRealTree:
    def test_check_passes_on_real_tree(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _check(capsys, REPO_ROOT)
        assert code == skill_pack_sync.EXIT_OK, out
        assert "RESULT: PASS" in out

    def test_check_json_contract_on_real_tree(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, report = _check_json(capsys, REPO_ROOT)
        assert code == skill_pack_sync.EXIT_OK
        assert report["schema_version"] == skill_pack_sync.REPORT_SCHEMA_VERSION
        assert report["command"] == "check"
        assert report["ok"] is True
        assert report["exit_code"] == 0
        assert report["errors"] == []


class TestMutationsFailClosed:
    def test_edited_plugin_copy_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        copy = pack_repo / "plugins" / "saena-skill-pack" / "skills" / "ponytail" / "SKILL.md"
        copy.write_text(copy.read_text(encoding="utf-8") + "\ndrifted\n", encoding="utf-8")
        code, report = _check_json(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert {"content-mismatch"} == {e["code"] for e in report["errors"]}

    def test_deleted_plugin_skill_file_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (
            pack_repo / "plugins" / "saena-skill-pack" / "skills" / "saena-intake" / "SKILL.md"
        ).unlink()
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "missing-copy" in _codes(out)

    def test_deleted_plugin_skill_dir_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import shutil

        shutil.rmtree(pack_repo / "plugins" / "saena-skill-pack" / "skills" / "saena-rollback")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "missing-copy" in _codes(out)

    def test_extra_skill_dir_in_plugin_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rogue = pack_repo / "plugins" / "saena-skill-pack" / "skills" / "rogue-skill"
        rogue.mkdir()
        (rogue / "SKILL.md").write_text("---\nname: rogue-skill\n---\n", encoding="utf-8")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "extra-copy" in _codes(out)

    def test_extra_file_inside_plugin_skill_dir_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        extra = pack_repo / "plugins" / "saena-skill-pack" / "skills" / "ponytail" / "NOTES.md"
        extra.write_text("not canonical\n", encoding="utf-8")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "extra-copy" in _codes(out)

    def test_stray_file_at_plugin_skills_root_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stray = pack_repo / "plugins" / "saena-skill-pack" / "skills" / "README.md"
        stray.write_text("stray\n", encoding="utf-8")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "extra-copy" in _codes(out)

    def test_edited_canonical_without_sync_fails_then_sync_heals(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        canonical = pack_repo / ".claude" / "skills" / "saena-intake" / "SKILL.md"
        canonical.write_text(
            canonical.read_text(encoding="utf-8") + "\ncanonical edit\n", encoding="utf-8"
        )
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "content-mismatch" in _codes(out)

        sync_code, _ = run_cli(capsys, ["sync", "--repo-root", str(pack_repo)])
        assert sync_code == skill_pack_sync.EXIT_OK
        heal_code, heal_out = _check(capsys, pack_repo)
        assert heal_code == skill_pack_sync.EXIT_OK, heal_out

    def test_missing_plugin_skills_tree_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import shutil

        shutil.rmtree(pack_repo / "plugins" / "saena-skill-pack" / "skills")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "plugin-skills-missing" in _codes(out)

    def test_invalid_manifest_makes_check_exit_manifest_invalid(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest_path = pack_repo / ".claude" / "skills" / "manifest.json"
        data = load_json(manifest_path)
        data["skills"] = data["skills"][:-1]  # drop a mandatory skill
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_MANIFEST_INVALID
        assert any(c.startswith("manifest:") for c in _codes(out))

    def test_findings_report_per_file_locations(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        copy = pack_repo / "plugins" / "saena-skill-pack" / "skills" / "ponytail" / "SKILL.md"
        copy.write_text("tampered\n", encoding="utf-8")
        code, out = run_cli(capsys, ["check", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_DRIFT
        report = json.loads(out)
        wheres = {e["where"] for e in report["errors"]}
        assert "ponytail/SKILL.md" in wheres
