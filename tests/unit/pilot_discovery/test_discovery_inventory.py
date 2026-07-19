"""Protected/generated classification and the .env flagged-NOT-read
guarantee: a planted secret-shaped value must never appear in any output."""

from __future__ import annotations

import json
from pathlib import Path

from _discovery_fixtures import PLANTED_ENV_SECRET, make_nextjs_repo, write_package_json
from saena_pilot.discovery import FrameworkDetector, FrameworkDiscovery


def _detect(root: Path) -> FrameworkDiscovery:
    result = FrameworkDetector().detect(root)
    assert isinstance(result, FrameworkDiscovery)
    return result


def _with_env(root: Path) -> Path:
    (root / ".env").write_text(
        f"OPENAI_API_KEY={PLANTED_ENV_SECRET}\nDB_PASSWORD=hunter2hunter2\n", encoding="utf-8"
    )
    (root / ".env.local").write_text(f"TOKEN={PLANTED_ENV_SECRET}\n", encoding="utf-8")
    return root


class TestEnvFlaggedNotRead:
    def test_env_files_flagged_by_name(self, tmp_path: Path) -> None:
        result = _detect(_with_env(make_nextjs_repo(tmp_path / "repo")))
        assert result.env_files == (".env", ".env.local")
        assert any(".env file(s) present" in warning for warning in result.warnings)
        assert any("NOT read" in warning for warning in result.warnings)

    def test_planted_secret_value_never_appears_in_any_output(self, tmp_path: Path) -> None:
        result = _detect(_with_env(make_nextjs_repo(tmp_path / "repo")))
        serialized = json.dumps(result.to_dict(), ensure_ascii=False)
        assert PLANTED_ENV_SECRET not in serialized
        assert "hunter2hunter2" not in serialized
        assert "OPENAI_API_KEY" not in serialized
        assert "DB_PASSWORD" not in serialized

    def test_env_files_are_classified_protected(self, tmp_path: Path) -> None:
        result = _detect(_with_env(make_nextjs_repo(tmp_path / "repo")))
        assert ".env" in result.protected_paths
        assert ".env.local" in result.protected_paths


class TestProtectedGenerated:
    def test_existing_build_output_dirs_are_protected(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert ".next/" in result.protected_paths

    def test_lockfiles_are_protected(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert "package-lock.json" in result.protected_paths

    def test_node_modules_protected_when_present(self, tmp_path: Path) -> None:
        root = make_nextjs_repo(tmp_path / "repo")
        (root / "node_modules" / "next").mkdir(parents=True)
        result = _detect(root)
        assert "node_modules/" in result.protected_paths

    def test_absent_output_dirs_are_not_listed(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"astro": "^4.0.0"}})
        result = _detect(root)
        assert not any(entry.endswith("/") for entry in result.protected_paths)

    def test_gitignore_patterns_carried_verbatim(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert ".next/" in result.gitignore_patterns
        assert ".env" in result.gitignore_patterns
        assert "# outputs" not in result.gitignore_patterns  # comments dropped

    def test_generated_dirs_never_scanned_for_routes(self, tmp_path: Path) -> None:
        root = make_nextjs_repo(tmp_path / "repo")
        deep = root / "app" / "node_modules" / "evil"
        deep.mkdir(parents=True)
        (deep / "page.tsx").write_text("nope\n", encoding="utf-8")
        result = _detect(root)
        assert not any("node_modules" in route for route in result.routes)


class TestInventoryBreadth:
    def test_multiple_lockfiles_warns_and_leaves_manager_undetermined(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"nuxt": "^3.11.0"}})
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
        result = _detect(root)
        assert result.package_manager is None
        assert any("multiple lockfiles" in warning for warning in result.warnings)
        assert set(result.lockfiles) == {"yarn.lock", "pnpm-lock.yaml"}

    def test_package_manager_field_beats_foreign_lockfile(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(
            root, {"packageManager": "pnpm@9.1.0", "dependencies": {"nuxt": "^3.11.0"}}
        )
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        result = _detect(root)
        assert result.package_manager == "pnpm"

    def test_metadata_dep_markers_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(
            root,
            {"dependencies": {"react": "^18.0.0", "react-helmet": "^6.1.0"}},
        )
        result = _detect(root)
        assert any("react-helmet" in item for item in result.metadata_mechanisms)

    def test_structured_data_dep_markers_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(
            root,
            {"dependencies": {"next": "^14.0.0", "schema-dts": "^1.1.0"}},
        )
        result = _detect(root)
        assert any("schema-dts" in item for item in result.structured_data)

    def test_deployment_hints_dockerfile_and_wrangler(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"react": "^18.0.0"}})
        (root / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")
        (root / "wrangler.toml").write_text("name = 'x'\n", encoding="utf-8")
        result = _detect(root)
        assert set(result.deployment_hints) == {"Dockerfile", "wrangler.toml"}

    def test_ci_inventory_lists_workflow_files_and_gitlab(self, tmp_path: Path) -> None:
        root = make_nextjs_repo(tmp_path / "repo")
        (root / ".gitlab-ci.yml").write_text("stages: []\n", encoding="utf-8")
        result = _detect(root)
        assert ".github/workflows/ci.yml" in result.ci_configs
        assert ".gitlab-ci.yml" in result.ci_configs

    def test_content_sources_markdown_counts(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"astro": "^4.0.0"}})
        for name in ("a.md", "b.mdx"):
            target = root / "content" / name
            target.parent.mkdir(exist_ok=True)
            target.write_text("---\n---\nbody\n", encoding="utf-8")
        result = _detect(root)
        assert any(item.startswith("content/") and "2" in item for item in result.content_sources)

    def test_routes_inventory_is_capped_and_flagged(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"next": "^14.0.0"}})
        pages = root / "pages"
        pages.mkdir()
        for index in range(230):
            (pages / f"page-{index:03d}.tsx").write_text("x\n", encoding="utf-8")
        result = _detect(root)
        assert len(result.routes) == 200
        assert result.routes_truncated is True
