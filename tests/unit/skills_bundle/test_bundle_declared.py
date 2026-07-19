"""Declared-bundle set equality: subset, superset, duplicates, malformation."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from bundle_fixtures import (
    run_cli,
    skill_bundle,
    write_bundle,
    write_declared,
    write_manifest,
)


def _names(manifest_data: dict[str, Any]) -> list[str]:
    return [entry["name"] for entry in manifest_data["skills"]]


@pytest.fixture
def green_tree(tmp_path: Path, manifest_data: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    manifest_path = write_manifest(tmp_path, manifest_data)
    skills_root = write_bundle(tmp_path / "skills", manifest_data)
    return manifest_path, skills_root, manifest_data


def _enforce_declared(
    capsys: pytest.CaptureFixture[str],
    green_tree: tuple[Path, Path, dict[str, Any]],
    declared_arg: str,
    *extra: str,
) -> tuple[int, str]:
    manifest_path, skills_root, _ = green_tree
    return run_cli(
        capsys,
        [
            "enforce",
            "--manifest",
            str(manifest_path),
            "--skills-root",
            str(skills_root),
            "--declared",
            declared_arg,
            *extra,
        ],
    )


class TestDeclaredGreen:
    def test_exact_list_passes(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, _names(green_tree[2]))
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_OK
        assert "RESULT: PASS" in out

    def test_skills_object_form_passes(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, {"skills": _names(green_tree[2])})
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_OK

    def test_stdin_declaration_passes(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_names(green_tree[2]))))
        code, out = _enforce_declared(capsys, green_tree, "-")
        assert code == skill_bundle.EXIT_OK

    def test_order_does_not_matter(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, sorted(_names(green_tree[2]), reverse=True))
        code, _ = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_OK


class TestDeclaredFailClosed:
    def test_subset_fails_listing_missing(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        """(d) Subset declaration: FAIL and list every missing skill."""
        names = _names(green_tree[2])
        declared = write_declared(tmp_path, [n for n in names if n != "ponytail-review"])
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-missing-skill" in out
        assert "ponytail-review" in out

    def test_superset_fails_listing_unknown(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        """(e) Superset declaration: FAIL and list the unknown name."""
        declared = write_declared(tmp_path, [*_names(green_tree[2]), "saena-extra-skill"])
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-unknown-skill" in out
        assert "saena-extra-skill" in out

    def test_swap_reports_both_directions(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        names = _names(green_tree[2])
        swapped = [n for n in names if n != "saena-intake"] + ["saena-imposter"]
        declared = write_declared(tmp_path, swapped)
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-missing-skill" in out and "saena-intake" in out
        assert "declared-unknown-skill" in out and "saena-imposter" in out

    def test_duplicate_declaration_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, [*_names(green_tree[2]), "ponytail"])
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-duplicate" in out

    def test_empty_declared_list_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, [])
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-missing-skill" in out

    def test_malformed_declared_json_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        path = tmp_path / "declared.json"
        path.write_text("{oops", encoding="utf-8")
        code, out = _enforce_declared(capsys, green_tree, str(path))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "malformed-declared" in out

    def test_declared_wrong_type_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, "just-a-string")
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "malformed-declared" in out

    def test_declared_unknown_key_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(
            tmp_path, {"skills": _names(green_tree[2]), "allow_partial": True}
        )
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "unknown-declared-key" in out

    def test_declared_non_string_entry_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, [*_names(green_tree[2])[:-1], 42])
        code, out = _enforce_declared(capsys, green_tree, str(declared))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "malformed-declared" in out

    def test_missing_declared_file_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        code, out = _enforce_declared(capsys, green_tree, str(tmp_path / "absent.json"))
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert "declared-unreadable" in out

    def test_declared_failure_emits_no_fingerprint(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        green_tree: tuple[Path, Path, dict[str, Any]],
    ) -> None:
        declared = write_declared(tmp_path, _names(green_tree[2])[:3])
        code, out = _enforce_declared(capsys, green_tree, str(declared), "--json")
        report = json.loads(out)
        assert code == skill_bundle.EXIT_BUNDLE_VIOLATION
        assert report["fingerprint"] is None
        assert report["ok"] is False
        assert all(err["stage"] == "bundle" for err in report["errors"])
