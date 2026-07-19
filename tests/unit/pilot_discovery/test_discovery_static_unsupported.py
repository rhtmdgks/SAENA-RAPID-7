"""Static HTML, WordPress/PHP limited-support fallback, and honest UNKNOWN —
the adapter never crashes and never guesses."""

from __future__ import annotations

from pathlib import Path

from _discovery_fixtures import (
    make_nextjs_repo,
    make_php_repo,
    make_static_repo,
    make_wordpress_repo,
    write_package_json,
)
from saena_pilot.discovery import FrameworkDetector, FrameworkDiscovery, SupportStatus


def _detect(root: Path) -> FrameworkDiscovery:
    result = FrameworkDetector().detect(root)
    assert isinstance(result, FrameworkDiscovery)
    return result


class TestStaticHtml:
    def test_index_html_tree_classifies_static(self, tmp_path: Path) -> None:
        result = _detect(make_static_repo(tmp_path / "site"))
        assert result.framework == "static-html"
        assert result.status is SupportStatus.SUPPORTED

    def test_html_files_are_the_routes_inventory(self, tmp_path: Path) -> None:
        result = _detect(make_static_repo(tmp_path / "site"))
        assert "index.html" in result.routes
        assert "about.html" in result.routes
        assert "blog/post.html" in result.routes

    def test_canonical_and_robots_signals_found(self, tmp_path: Path) -> None:
        result = _detect(make_static_repo(tmp_path / "site"))
        assert "robots.txt" in result.sitemap_robots_canonical
        assert any('rel="canonical"' in item for item in result.sitemap_robots_canonical)

    def test_no_version_or_commands_are_invented(self, tmp_path: Path) -> None:
        result = _detect(make_static_repo(tmp_path / "site"))
        assert result.version_spec is None
        assert result.build_command is None
        assert result.package_manager is None


class TestUnsupported:
    def test_wordpress_is_limited_support_never_a_crash(self, tmp_path: Path) -> None:
        result = _detect(make_wordpress_repo(tmp_path / "wp"))
        assert result.framework == "wordpress"
        assert result.status is SupportStatus.UNSUPPORTED
        assert "report-only" in result.detail
        assert "wp-content/ directory present" in result.evidence

    def test_wp_config_alone_flags_wordpress(self, tmp_path: Path) -> None:
        root = tmp_path / "wp"
        root.mkdir()
        (root / "wp-config.php").write_text("<?php\n", encoding="utf-8")
        result = _detect(root)
        assert result.framework == "wordpress"
        assert result.status is SupportStatus.UNSUPPORTED

    def test_bare_php_is_limited_support(self, tmp_path: Path) -> None:
        result = _detect(make_php_repo(tmp_path / "php"))
        assert result.framework == "php"
        assert result.status is SupportStatus.UNSUPPORTED
        assert "report-only" in result.detail

    def test_composer_json_alone_flags_php(self, tmp_path: Path) -> None:
        root = tmp_path / "php"
        root.mkdir()
        (root / "composer.json").write_text("{}\n", encoding="utf-8")
        result = _detect(root)
        assert result.framework == "php"

    def test_js_framework_wins_over_coexisting_wp_markers_with_warning(
        self, tmp_path: Path
    ) -> None:
        root = make_nextjs_repo(tmp_path / "hybrid")
        (root / "wp-content").mkdir()
        result = _detect(root)
        assert result.framework == "nextjs"
        assert any("WordPress/PHP markers also present" in w for w in result.warnings)


class TestUnknown:
    def test_empty_dir_is_unknown(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        result = _detect(root)
        assert result.framework == "unknown"
        assert result.status is SupportStatus.UNKNOWN
        assert "not guessed" in result.detail

    def test_plain_git_style_repo_is_unknown(self, tmp_path: Path) -> None:
        root = tmp_path / "plain"
        root.mkdir()
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        result = _detect(root)
        assert result.status is SupportStatus.UNKNOWN

    def test_package_json_without_framework_deps_is_unknown_not_guessed(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "tooling"
        write_package_json(root, {"name": "just-tooling", "dependencies": {"lodash": "^4.17.0"}})
        result = _detect(root)
        assert result.framework == "unknown"
        assert result.status is SupportStatus.UNKNOWN
        assert "package.json present" in result.detail

    def test_unknown_still_reports_honest_inventory(self, tmp_path: Path) -> None:
        root = tmp_path / "tooling"
        write_package_json(root, {"scripts": {"build": "make all"}})
        (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
        result = _detect(root)
        assert result.build_command == "make all"  # verbatim, never executed
        assert result.lockfiles == ("package-lock.json",)
        assert result.package_manager == "npm"
