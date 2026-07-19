"""`validate-manifest` — structural + semantic manifest checks (no disk skills)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from _manifest_fixtures import (
    REAL_MANIFEST_PATH,
    REAL_SCHEMA_PATH,
    run_cli,
    skill_manifest,
    write_manifest,
)


def _entry(data: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in data["skills"]:
        if entry["name"] == name:
            assert isinstance(entry, dict)
            return entry
    raise AssertionError(f"skill {name} not in manifest fixture")


def _assert_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    data: dict[str, Any],
    expected_code: str,
) -> None:
    path = write_manifest(tmp_path, data)
    code, out = run_cli(capsys, ["validate-manifest", "--manifest", str(path), "--json"])
    assert code == skill_manifest.EXIT_MANIFEST_INVALID
    report = json.loads(out)
    assert report["ok"] is False
    codes = {err["code"] for err in report["errors"]}
    assert expected_code in codes, f"expected `{expected_code}` in {sorted(codes)}"


class TestHappyPath:
    def test_real_manifest_passes_with_schema_cross_check(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = run_cli(
            capsys,
            [
                "validate-manifest",
                "--manifest",
                str(REAL_MANIFEST_PATH),
                "--schema",
                str(REAL_SCHEMA_PATH),
            ],
        )
        assert code == skill_manifest.EXIT_OK
        assert "RESULT: PASS" in out

    def test_real_manifest_has_all_16_mandatory_skills(self) -> None:
        data = json.loads(REAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        names = {entry["name"] for entry in data["skills"]}
        assert names == set(skill_manifest.MANDATORY_SKILLS)
        for entry in data["skills"]:
            assert entry["phase"] == skill_manifest.MANDATORY_SKILLS[entry["name"]]


class TestManifestNegatives:
    def test_duplicate_skill_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["skills"].append(copy.deepcopy(manifest_data["skills"][0]))
        _assert_fails(tmp_path, capsys, manifest_data, "duplicate-name")

    def test_unknown_top_level_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["extra_field"] = True
        _assert_fails(tmp_path, capsys, manifest_data, "unknown-top-level-key")

    def test_unknown_skill_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-intake")["tools"] = "all"
        _assert_fails(tmp_path, capsys, manifest_data, "unknown-skill-key")

    def test_bad_phase(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "ponytail")["phase"] = "deploy"
        _assert_fails(tmp_path, capsys, manifest_data, "bad-phase")

    def test_engine_scope_tamper_lookalike_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        # fa-07 precedent: `chatgpt-search-beta` is NOT the approved engine.
        manifest_data["engine_scope"] = ["chatgpt-search-beta"]
        _assert_fails(tmp_path, capsys, manifest_data, "bad-engine-scope")

    def test_engine_scope_widening_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["engine_scope"] = ["chatgpt-search", "google-gemini"]
        _assert_fails(tmp_path, capsys, manifest_data, "bad-engine-scope")

    def test_skill_engine_not_in_scope(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-intake")["engines"] = ["chatgpt-search-beta"]
        _assert_fails(tmp_path, capsys, manifest_data, "unknown-engine")

    def test_unknown_agent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        # There are exactly 14 defined agents — a 15th must be rejected.
        _entry(manifest_data, "saena-demand-graph")["agents"] = ["growth-hacker-agent"]
        _assert_fails(tmp_path, capsys, manifest_data, "unknown-agent")

    def test_dependency_cycle(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        # saena-security-redteam already depends on saena-intake; close the loop.
        _entry(manifest_data, "saena-intake")["depends_on"] = ["saena-security-redteam"]
        _assert_fails(tmp_path, capsys, manifest_data, "dependency-cycle")

    def test_backward_phase_dependency(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        # bootstrap must never depend on an execute-phase skill.
        _entry(manifest_data, "saena-intake")["depends_on"] = ["ponytail"]
        _assert_fails(tmp_path, capsys, manifest_data, "backward-phase-dependency")

    def test_unknown_dependency(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "ponytail")["depends_on"] = ["not-a-skill"]
        _assert_fails(tmp_path, capsys, manifest_data, "unknown-dependency")

    def test_non_semver_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-rollback")["version"] = "v1.0"
        _assert_fails(tmp_path, capsys, manifest_data, "bad-version")

    def test_wrong_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-rollback")["path"] = ".claude/skills/other/SKILL.md"
        _assert_fails(tmp_path, capsys, manifest_data, "bad-path")

    def test_missing_mandatory_skill(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["skills"] = [
            entry for entry in manifest_data["skills"] if entry["name"] != "ponytail-review"
        ]
        _assert_fails(tmp_path, capsys, manifest_data, "missing-mandatory-skill")

    def test_extra_unregistered_skill_drift(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        rogue = copy.deepcopy(_entry(manifest_data, "ponytail"))
        rogue["name"] = "saena-growth-hacks"
        rogue["path"] = ".claude/skills/saena-growth-hacks/SKILL.md"
        manifest_data["skills"].append(rogue)
        _assert_fails(tmp_path, capsys, manifest_data, "unregistered-skill-drift")

    def test_wrong_mandatory_phase(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-intake")["phase"] = "plan"
        _assert_fails(tmp_path, capsys, manifest_data, "wrong-mandatory-phase")

    def test_engine_swap_flag_only_on_chatgpt_search(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-intake")["adr0007_engine_swap_point"] = True
        _assert_fails(tmp_path, capsys, manifest_data, "misplaced-engine-swap-flag")

    def test_engine_swap_flag_required_on_chatgpt_search(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        del _entry(manifest_data, "saena-chatgpt-search")["adr0007_engine_swap_point"]
        _assert_fails(tmp_path, capsys, manifest_data, "missing-engine-swap-flag")

    def test_failure_behavior_must_be_fail_closed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        _entry(manifest_data, "saena-intake")["failure_behavior"] = "fail-open"
        _assert_fails(tmp_path, capsys, manifest_data, "bad-failure-behavior")

    def test_malformed_manifest_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "manifest.json"
        path.write_text("{not json", encoding="utf-8")
        code, out = run_cli(capsys, ["validate-manifest", "--manifest", str(path), "--json"])
        assert code == skill_manifest.EXIT_MANIFEST_INVALID
        assert {e["code"] for e in json.loads(out)["errors"]} == {"malformed-json"}


class TestSchemaDrift:
    def test_schema_agent_enum_drift_detected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        schema = json.loads(REAL_SCHEMA_PATH.read_text(encoding="utf-8"))
        enum = schema["$defs"]["skill"]["properties"]["agents"]["items"]["enum"]
        enum.append("growth-hacker-agent")
        drifted = tmp_path / "manifest.schema.json"
        drifted.write_text(json.dumps(schema), encoding="utf-8")
        code, out = run_cli(
            capsys,
            [
                "validate-manifest",
                "--manifest",
                str(REAL_MANIFEST_PATH),
                "--schema",
                str(drifted),
                "--json",
            ],
        )
        assert code == skill_manifest.EXIT_MANIFEST_INVALID
        assert "schema-drift" in {e["code"] for e in json.loads(out)["errors"]}
