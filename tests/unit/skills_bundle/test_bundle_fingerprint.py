"""Fingerprint semantics: stability, tamper-evidence, validate-before-print."""

from __future__ import annotations

import hashlib
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
    write_skill,
)


def _fingerprint_cli(
    capsys: pytest.CaptureFixture[str], manifest_path: Path, skills_root: Path
) -> tuple[int, str]:
    return run_cli(
        capsys,
        ["fingerprint", "--manifest", str(manifest_path), "--skills-root", str(skills_root)],
    )


class TestFingerprintSubcommand:
    def test_prints_single_hex_line_on_green_tree(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code, out = _fingerprint_cli(capsys, manifest_path, skills_root)
        assert code == skill_bundle.EXIT_OK
        lines = out.strip().splitlines()
        assert len(lines) == 1
        assert len(lines[0]) == 64
        int(lines[0], 16)

    def test_stable_across_two_runs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        _, out1 = _fingerprint_cli(capsys, manifest_path, skills_root)
        _, out2 = _fingerprint_cli(capsys, manifest_path, skills_root)
        assert out1 == out2

    def test_invalid_tree_prints_no_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """Validate-first: an invalid tree exits nonzero with EMPTY stdout."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(
            tmp_path / "skills", manifest_data, skip={"saena-content-fidelity"}
        )
        code = skill_bundle.main(
            ["fingerprint", "--manifest", str(manifest_path), "--skills-root", str(skills_root)]
        )
        captured = capsys.readouterr()
        assert code == skill_bundle.EXIT_SKILLS_INVALID
        assert captured.out == ""
        assert "saena-content-fidelity" in captured.err

    def test_matches_enforce_json_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        _, fp_out = _fingerprint_cli(capsys, manifest_path, skills_root)
        _, enforce_out = run_cli(
            capsys,
            [
                "enforce",
                "--manifest",
                str(manifest_path),
                "--skills-root",
                str(skills_root),
                "--json",
            ],
        )
        assert fp_out.strip() == json.loads(enforce_out)["fingerprint"]

    def test_real_repo_tree_fingerprint(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _fingerprint_cli(capsys, REAL_MANIFEST_PATH, REAL_SKILLS_ROOT)
        assert code == skill_bundle.EXIT_OK
        assert len(out.strip()) == 64


class TestTamperEvidence:
    def test_skill_md_edit_changes_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """(i) A content change in ANY SKILL.md must move the fingerprint."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        code1, before = _fingerprint_cli(capsys, manifest_path, skills_root)
        write_skill(
            skills_root,
            "saena-intake",
            make_skill_md("saena-intake", body_extra="One appended provenance line.\n"),
        )
        code2, after = _fingerprint_cli(capsys, manifest_path, skills_root)
        assert code1 == code2 == skill_bundle.EXIT_OK  # still a VALID tree
        assert before != after

    def test_manifest_byte_change_changes_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], manifest_data: dict[str, Any]
    ) -> None:
        """Fingerprint covers raw manifest BYTES — even reformatting moves it."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        _, before = _fingerprint_cli(capsys, manifest_path, skills_root)
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        _, after = _fingerprint_cli(capsys, manifest_path, skills_root)
        assert before != after

    def test_fingerprint_formula_is_the_documented_one(
        self, tmp_path: Path, manifest_data: dict[str, Any]
    ) -> None:
        """sha256(manifest bytes + `<name>\\0<sha256(SKILL.md)>\\n` sorted)."""
        manifest_path = write_manifest(tmp_path, manifest_data)
        skills_root = write_bundle(tmp_path / "skills", manifest_data)
        report = skill_bundle.enforce_bundle(manifest_path, skills_root)
        assert report.ok

        expected = hashlib.sha256()
        expected.update(manifest_path.read_bytes())
        names = sorted(entry["name"] for entry in manifest_data["skills"])
        for name in names:
            digest = hashlib.sha256((skills_root / name / "SKILL.md").read_bytes()).hexdigest()
            expected.update(f"{name}\x00{digest}\n".encode())
        assert report.fingerprint == expected.hexdigest()

    def test_fingerprint_has_no_unknown_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = run_cli(capsys, ["fingerprint", "--declared", "x.json"])
        assert code == skill_bundle.EXIT_USAGE
