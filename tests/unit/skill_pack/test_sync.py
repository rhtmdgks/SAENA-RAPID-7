"""`sync` tests: regeneration, pruning, idempotence, manifest refusal."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import load_json, run_cli, skill_pack_sync


def _plugin_skills(root: Path) -> Path:
    return root / "plugins" / "saena-skill-pack" / "skills"


def _snapshot(root: Path) -> dict[str, bytes]:
    tree = _plugin_skills(root)
    return {
        str(p.relative_to(tree)): p.read_bytes() for p in sorted(tree.rglob("*")) if p.is_file()
    }


class TestSync:
    def test_sync_is_idempotent_on_clean_tree(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_OK
        report = json.loads(out)
        assert report["ok"] is True
        assert report["actions"] == []  # tree already byte-identical: no-op

    def test_sync_regenerates_from_empty_plugin_tree(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _snapshot(pack_repo)
        shutil.rmtree(_plugin_skills(pack_repo))
        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_OK
        assert len(json.loads(out)["actions"]) == 16
        assert _snapshot(pack_repo) == before
        check_code, check_out = run_cli(capsys, ["check", "--repo-root", str(pack_repo)])
        assert check_code == skill_pack_sync.EXIT_OK, check_out

    def test_sync_prunes_stale_skill_dir(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stale = _plugin_skills(pack_repo) / "stale-skill"
        stale.mkdir()
        (stale / "SKILL.md").write_text("stale\n", encoding="utf-8")
        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_OK
        assert not stale.exists()
        assert any("prune" in action for action in json.loads(out)["actions"])

    def test_sync_prunes_stray_file_at_skills_root(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stray = _plugin_skills(pack_repo) / "README.md"
        stray.write_text("stray\n", encoding="utf-8")
        code, _ = run_cli(capsys, ["sync", "--repo-root", str(pack_repo)])
        assert code == skill_pack_sync.EXIT_OK
        assert not stray.exists()

    def test_sync_refuses_invalid_manifest_and_writes_nothing(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest_path = pack_repo / ".claude" / "skills" / "manifest.json"
        data = load_json(manifest_path)
        data["skills"][0]["engines"] = ["chatgpt-search-beta"]  # closed-enum violation
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        # Plant drift that a (forbidden) sync WOULD have repaired.
        drifted = _plugin_skills(pack_repo) / "ponytail" / "SKILL.md"
        drifted.write_text("drift\n", encoding="utf-8")
        before = _snapshot(pack_repo)

        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_MANIFEST_INVALID
        report = json.loads(out)
        assert report["ok"] is False
        assert any(e["code"] == "manifest:unknown-engine" for e in report["errors"])
        assert _snapshot(pack_repo) == before  # refusal means zero writes

    def test_sync_refuses_malformed_manifest_json(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (pack_repo / ".claude" / "skills" / "manifest.json").write_text("{", encoding="utf-8")
        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_MANIFEST_INVALID
        assert any(e["code"] == "malformed-json" for e in json.loads(out)["errors"])

    def test_sync_refuses_when_canonical_skill_md_missing(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (pack_repo / ".claude" / "skills" / "saena-rollback" / "SKILL.md").unlink()
        before = _snapshot(pack_repo)
        code, out = run_cli(capsys, ["sync", "--repo-root", str(pack_repo), "--json"])
        assert code == skill_pack_sync.EXIT_MANIFEST_INVALID
        assert any(e["code"] == "canonical-missing" for e in json.loads(out)["errors"])
        assert _snapshot(pack_repo) == before

    def test_usage_error_exits_3(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert skill_pack_sync.main(["no-such-command"]) == skill_pack_sync.EXIT_USAGE
        assert skill_pack_sync.main([]) == skill_pack_sync.EXIT_USAGE
        capsys.readouterr()
