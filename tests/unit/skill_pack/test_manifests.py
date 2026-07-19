"""Structural checks of the real plugin.json / marketplace.json + their gates."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import (
    CANONICAL_SKILLS,
    MARKETPLACE_JSON,
    PLUGIN_DIR,
    load_json,
    run_cli,
    skill_pack_sync,
    write_json,
)

_SEMVER_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


def _codes(out: str) -> set[str]:
    return {error["code"] for error in json.loads(out)["errors"]}


class TestRealPluginJson:
    def test_parses_with_required_fields(self) -> None:
        data = load_json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")
        assert data["name"] == "saena-skill-pack"
        assert _SEMVER_RE.match(data["version"])
        assert data["author"]["name"] == "SAENA Labs"
        assert data["repository"] == "https://github.com/SAENA-Labs/SAENA-RAPID-7"
        assert data["license"] == "UNLICENSED"  # repo ships no LICENSE file
        missing = skill_pack_sync.PLUGIN_JSON_REQUIRED_KEYS - set(data)
        assert not missing

    def test_version_matches_every_manifest_skill_version(self) -> None:
        plugin = load_json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")
        manifest = load_json(CANONICAL_SKILLS / "manifest.json")
        versions = {entry["version"] for entry in manifest["skills"]}
        assert versions == {plugin["version"]}

    def test_description_states_forge_and_engine_scope(self) -> None:
        data = load_json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")
        assert "SAENA FORGE" in data["description"]
        assert "ChatGPT Search" in data["description"]


class TestRealMarketplaceJson:
    def test_parses_with_required_fields(self) -> None:
        data = load_json(MARKETPLACE_JSON)
        assert data["name"] == "saena-rapid-7"
        assert data["owner"]["name"] == "SAENA Labs"
        assert data["metadata"]["pluginRoot"] == "./plugins"

    def test_lists_exactly_the_skill_pack_plugin(self) -> None:
        data = load_json(MARKETPLACE_JSON)
        assert len(data["plugins"]) == 1
        entry = data["plugins"][0]
        assert entry["name"] == "saena-skill-pack"
        assert entry["source"] == "./plugins/saena-skill-pack"

    def test_source_resolves_from_marketplace_root(self) -> None:
        # claude CLI 2.1.205 resolves `./` sources against the marketplace
        # root (NOT metadata.pluginRoot) — verified by a sandboxed install.
        data = load_json(MARKETPLACE_JSON)
        entry = data["plugins"][0]
        resolved = (MARKETPLACE_JSON.parent.parent / entry["source"]).resolve()
        assert (resolved / ".claude-plugin" / "plugin.json").is_file()


class TestManifestGates:
    def _check(self, capsys: pytest.CaptureFixture[str], root: Path) -> tuple[int, str]:
        return run_cli(capsys, ["check", "--repo-root", str(root), "--json"])

    def test_plugin_json_missing_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (pack_repo / "plugins" / "saena-skill-pack" / ".claude-plugin" / "plugin.json").unlink()
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "unreadable" in _codes(out)

    def test_plugin_json_wrong_name_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = pack_repo / "plugins" / "saena-skill-pack" / ".claude-plugin" / "plugin.json"
        data = load_json(path)
        data["name"] = "other-pack"
        write_json(path, data)
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "bad-plugin-json" in _codes(out)

    def test_plugin_json_version_drift_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = pack_repo / "plugins" / "saena-skill-pack" / ".claude-plugin" / "plugin.json"
        data = load_json(path)
        data["version"] = "9.9.9"
        write_json(path, data)
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "version-drift" in _codes(out)

    def test_marketplace_missing_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (pack_repo / ".claude-plugin" / "marketplace.json").unlink()
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "unreadable" in _codes(out)

    def test_marketplace_wrong_plugin_root_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = pack_repo / ".claude-plugin" / "marketplace.json"
        data = load_json(path)
        data["metadata"]["pluginRoot"] = "./elsewhere"
        write_json(path, data)
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "bad-marketplace-json" in _codes(out)

    def test_marketplace_extra_plugin_entry_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = pack_repo / ".claude-plugin" / "marketplace.json"
        data = load_json(path)
        data["plugins"].append({"name": "rogue", "source": "./rogue"})
        write_json(path, data)
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "bad-marketplace-json" in _codes(out)

    def test_marketplace_wrong_source_fails(
        self, pack_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = pack_repo / ".claude-plugin" / "marketplace.json"
        data = load_json(path)
        data["plugins"][0]["source"] = "./saena-skill-pack"  # install-broken form
        write_json(path, data)
        code, out = self._check(capsys, pack_repo)
        assert code == skill_pack_sync.EXIT_DRIFT
        assert "bad-marketplace-json" in _codes(out)
