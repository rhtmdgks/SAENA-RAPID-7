"""`validate-skills` — both-direction disk<->manifest cross-check + SKILL.md
quality contract, on synthetic `tmp_path` trees only (the real `.claude/skills`
has no SKILL.md files in this worktree and must not be depended on)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _manifest_fixtures import (
    make_skill_md,
    run_cli,
    skill_manifest,
    write_bundle,
    write_manifest,
    write_skill,
)


@pytest.fixture
def green_tree(tmp_path: Path, manifest_data: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    """(manifest_path, skills_root, manifest_data) with a fully green bundle."""
    manifest_path = write_manifest(tmp_path, manifest_data)
    skills_root = write_bundle(tmp_path / "skills", manifest_data)
    return manifest_path, skills_root, manifest_data


def _run(
    capsys: pytest.CaptureFixture[str], manifest_path: Path, skills_root: Path
) -> tuple[int, dict[str, Any]]:
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
    return code, json.loads(out)


def _assert_skill_fail(
    capsys: pytest.CaptureFixture[str],
    manifest_path: Path,
    skills_root: Path,
    expected_code: str,
) -> None:
    code, report = _run(capsys, manifest_path, skills_root)
    assert code == skill_manifest.EXIT_SKILLS_INVALID
    codes = {err["code"] for err in report["errors"]}
    assert expected_code in codes, f"expected `{expected_code}` in {sorted(codes)}"


class TestHappyPath:
    def test_full_synthetic_bundle_passes(
        self,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        manifest_path, skills_root, _ = green_tree
        code, report = _run(capsys, manifest_path, skills_root)
        assert code == skill_manifest.EXIT_OK
        assert report["ok"] is True
        assert report["errors"] == []
        assert report["checked_skills"] == 16

    def test_non_skill_files_in_root_are_ignored(
        self,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        manifest_path, skills_root, _ = green_tree
        # README.md / manifest.json siblings must not count as skill dirs.
        (skills_root / "README.md").write_text("readme", encoding="utf-8")
        (skills_root / "manifest.json").write_text("{}", encoding="utf-8")
        code, report = _run(capsys, manifest_path, skills_root)
        assert code == skill_manifest.EXIT_OK
        assert report["ok"] is True


class TestCrossCheck:
    def test_manifest_skill_missing_on_disk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data, skip={"saena-rollback"})
        _assert_skill_fail(capsys, manifest_path, skills_root, "skill-missing-on-disk")

    def test_unregistered_skill_dir_on_disk(
        self,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        manifest_path, skills_root, _ = green_tree
        write_skill(skills_root, "rogue-skill", make_skill_md("rogue-skill"))
        _assert_skill_fail(capsys, manifest_path, skills_root, "skill-not-in-manifest")

    def test_invalid_manifest_yields_manifest_exit_code(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_data["engine_scope"] = ["chatgpt-search-beta"]
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, report = _run(capsys, manifest_path, skills_root)
        assert code == skill_manifest.EXIT_MANIFEST_INVALID
        assert report["exit_code"] == skill_manifest.EXIT_MANIFEST_INVALID

    def test_missing_skills_root_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        _assert_skill_fail(capsys, manifest_path, tmp_path / "nope", "bad-skills-root")


class TestSkillFileQuality:
    def _tree_with(
        self,
        tmp_path: Path,
        manifest_data: dict[str, Any],
        name: str,
        content: str,
    ) -> tuple[Path, Path]:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data, contents={name: content})
        return manifest_path, skills_root

    def test_malformed_frontmatter_yaml(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-intake", raw_frontmatter="name: [unclosed\n")
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "malformed-frontmatter")

    def test_missing_frontmatter_fence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = "# no frontmatter\n" + make_skill_md("saena-intake")
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "malformed-frontmatter")

    def test_frontmatter_name_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-intake", fm_name="saena-outtake")
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "frontmatter-name-mismatch")

    def test_frontmatter_extra_key_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-intake", extra_frontmatter="tools: all\n")
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "bad-frontmatter-keys")

    def test_description_overlength(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-intake", description="x" * 1025)
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "description-too-long")

    def test_missing_required_section(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("ponytail", drop_section="Secrets & PII")
        mp, root = self._tree_with(tmp_path, manifest_data, "ponytail", content)
        _assert_skill_fail(capsys, mp, root, "missing-section")

    def test_trivial_section_content(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("ponytail", section_overrides={"Non-goals": "single line only"})
        mp, root = self._tree_with(tmp_path, manifest_data, "ponytail", content)
        _assert_skill_fail(capsys, mp, root, "trivial-section")

    def test_workflow_too_few_numbered_steps(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-rollback", workflow_steps=3)
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-rollback", content)
        _assert_skill_fail(capsys, mp, root, "workflow-too-few-steps")

    def test_body_too_short(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-rollback", section_lines=2)
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-rollback", content)
        _assert_skill_fail(capsys, mp, root, "body-too-short")

    def test_missing_engine_scope_statement(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md("saena-intake", include_engine_statement=False)
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "missing-engine-scope-statement")

    @pytest.mark.parametrize(
        "secret",
        [
            # Built by concatenation so repo-wide secret scanners never match
            # this test source itself.
            "sk-" + "live-" + "Ab1" * 5,
            "sk_" + "live_" + "Ab1" * 5,
            "AKIA" + "IOSFODNN7EXAMPLE",
            "ghp_" + "Abcd1234" * 4,
            "eyJ" + "a1b2c3d4e5" + "." + "f6g7h8i9j0" + "." + "k1l2m3n4o5",
        ],
        ids=["sk-live-hyphen", "sk-underscore-shape", "akia", "ghp", "jwt"],
    )
    def test_secret_shaped_string_rejected(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        manifest_data: dict[str, Any],
        secret: str,
    ) -> None:
        content = make_skill_md("saena-intake", body_extra=f"Never commit {secret} anywhere.\n")
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-intake", content)
        _assert_skill_fail(capsys, mp, root, "secret-shaped-string")

    def test_real_domain_in_examples_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        content = make_skill_md(
            "saena-answer-capsule",
            examples_extra="Customer demo: https://acme-rocketry.io/pricing\n",
        )
        mp, root = self._tree_with(tmp_path, manifest_data, "saena-answer-capsule", content)
        _assert_skill_fail(capsys, mp, root, "real-domain-in-examples")

    def test_reserved_domains_and_fixture_paths_allowed(
        self,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        # The default green bundle already uses example.com/example.org/
        # site.example and fixture paths in Examples — must stay green.
        manifest_path, skills_root, _ = green_tree
        code, report = _run(capsys, manifest_path, skills_root)
        assert code == skill_manifest.EXIT_OK
        assert report["errors"] == []
