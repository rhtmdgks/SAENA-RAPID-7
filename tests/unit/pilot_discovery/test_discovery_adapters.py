"""Per-framework detection: each adapter profile classifies its fixture repo
with the expected typed fields (declared specs verbatim, commands verbatim,
routes from filesystem conventions)."""

from __future__ import annotations

from pathlib import Path

from _discovery_fixtures import (
    make_astro_repo,
    make_nextjs_repo,
    make_nuxt_repo,
    make_remix_repo,
    make_sveltekit_repo,
    write_package_json,
)
from saena_pilot.discovery import (
    FrameworkDetector,
    FrameworkDiscovery,
    SupportStatus,
    default_adapters,
    discover,
)


def _detect(root: Path) -> FrameworkDiscovery:
    result = FrameworkDetector().detect(root)
    assert isinstance(result, FrameworkDiscovery)
    return result


class TestNextjs:
    def test_detected_with_config_specificity(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert result.framework == "nextjs"
        assert result.status is SupportStatus.SUPPORTED
        assert "next.config.mjs present" in result.detail

    def test_version_spec_is_declared_verbatim_never_resolved(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert result.version_spec == "^14.2.3"

    def test_package_manager_from_package_manager_field(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert result.package_manager == "npm"
        assert result.lockfiles == ("package-lock.json",)

    def test_commands_verbatim_from_scripts(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert result.build_command == "next build"
        assert result.test_command == "vitest run"
        assert result.lint_command == "next lint"
        assert result.typecheck_command == "tsc --noEmit"

    def test_routes_from_app_dir(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert "app/page.tsx" in result.routes
        assert "app/about/page.tsx" in result.routes
        # generated output dirs never appear as routes
        assert not any(route.startswith(".next") for route in result.routes)

    def test_metadata_and_structured_data_markers(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert any("export const metadata" in item for item in result.metadata_mechanisms)
        assert any("application/ld+json" in item for item in result.structured_data)

    def test_rendering_hint_from_config_with_evidence(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert any(
            hint.startswith("next.config.mjs") and "SSG hint" in hint
            for hint in result.rendering_hints
        )

    def test_sitemap_robots_and_deployment_and_ci(self, tmp_path: Path) -> None:
        result = _detect(make_nextjs_repo(tmp_path / "repo"))
        assert "public/robots.txt" in result.sitemap_robots_canonical
        assert "vercel.json" in result.deployment_hints
        assert ".github/workflows/ci.yml" in result.ci_configs


class TestRemix:
    def test_detected(self, tmp_path: Path) -> None:
        result = _detect(make_remix_repo(tmp_path / "repo"))
        assert result.framework == "remix"
        assert result.status is SupportStatus.SUPPORTED
        assert result.version_spec == "^2.9.0"

    def test_routes_from_app_routes(self, tmp_path: Path) -> None:
        result = _detect(make_remix_repo(tmp_path / "repo"))
        assert "app/routes/_index.tsx" in result.routes
        assert "app/routes/blog.$slug.tsx" in result.routes

    def test_yarn_lockfile_maps_package_manager(self, tmp_path: Path) -> None:
        result = _detect(make_remix_repo(tmp_path / "repo"))
        assert result.package_manager == "yarn"


class TestAstro:
    def test_detected_with_frontmatter_and_sitemap_plugin(self, tmp_path: Path) -> None:
        result = _detect(make_astro_repo(tmp_path / "repo"))
        assert result.framework == "astro"
        assert result.status is SupportStatus.SUPPORTED
        assert any("frontmatter block" in item for item in result.metadata_mechanisms)
        assert any("@astrojs/sitemap" in item for item in result.sitemap_robots_canonical)

    def test_routes_and_content_sources(self, tmp_path: Path) -> None:
        result = _detect(make_astro_repo(tmp_path / "repo"))
        assert "src/pages/index.astro" in result.routes
        assert "src/pages/blog/post-1.md" in result.routes
        assert any(item.startswith("src/content/") for item in result.content_sources)

    def test_hybrid_rendering_hint(self, tmp_path: Path) -> None:
        result = _detect(make_astro_repo(tmp_path / "repo"))
        assert any("SSR+SSG hint" in hint for hint in result.rendering_hints)

    def test_pnpm_lockfile(self, tmp_path: Path) -> None:
        assert _detect(make_astro_repo(tmp_path / "repo")).package_manager == "pnpm"


class TestNuxt:
    def test_detected(self, tmp_path: Path) -> None:
        result = _detect(make_nuxt_repo(tmp_path / "repo"))
        assert result.framework == "nuxt"
        assert result.status is SupportStatus.SUPPORTED
        assert result.version_spec == "^3.11.0"

    def test_vue_pages_routes(self, tmp_path: Path) -> None:
        result = _detect(make_nuxt_repo(tmp_path / "repo"))
        assert result.routes == ("pages/about.vue", "pages/index.vue")

    def test_spa_hint_from_ssr_false(self, tmp_path: Path) -> None:
        result = _detect(make_nuxt_repo(tmp_path / "repo"))
        assert any("SPA/CSR hint" in hint for hint in result.rendering_hints)


class TestSvelteKit:
    def test_detected_over_plain_svelte(self, tmp_path: Path) -> None:
        result = _detect(make_sveltekit_repo(tmp_path / "repo"))
        assert result.framework == "sveltekit"
        assert result.status is SupportStatus.SUPPORTED
        assert result.version_spec == "^2.5.0"

    def test_routes_from_src_routes(self, tmp_path: Path) -> None:
        result = _detect(make_sveltekit_repo(tmp_path / "repo"))
        assert "src/routes/+page.svelte" in result.routes
        assert "src/routes/docs/+page.svelte" in result.routes

    def test_static_adapter_hint_and_bun_lockfile(self, tmp_path: Path) -> None:
        result = _detect(make_sveltekit_repo(tmp_path / "repo"))
        assert any("static adapter" in hint for hint in result.rendering_hints)
        assert result.package_manager == "bun"


class TestBaseLibraries:
    def test_plain_react_spa(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"react": "^18.3.0"}})
        result = _detect(root)
        assert result.framework == "react"
        assert result.status is SupportStatus.SUPPORTED
        assert result.version_spec == "^18.3.0"
        assert any("CSR" in hint for hint in result.rendering_hints)

    def test_plain_vue_spa(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"dependencies": {"vue": "^3.4.0"}})
        result = _detect(root)
        assert result.framework == "vue"
        assert result.status is SupportStatus.SUPPORTED

    def test_plain_svelte_without_kit(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        write_package_json(root, {"devDependencies": {"svelte": "^4.2.0"}})
        (root / "svelte.config.js").write_text("export default {};\n", encoding="utf-8")
        result = _detect(root)
        assert result.framework == "svelte"
        assert result.status is SupportStatus.SUPPORTED


class TestSeamIntegration:
    def test_default_adapters_flow_through_discover(self, tmp_path: Path) -> None:
        root = make_nextjs_repo(tmp_path / "repo")
        result = discover(root, adapters=default_adapters())
        assert isinstance(result, FrameworkDiscovery)
        assert result.framework == "nextjs"

    def test_to_dict_carries_seam_keys_plus_rich_fields(self, tmp_path: Path) -> None:
        payload = _detect(make_nextjs_repo(tmp_path / "repo")).to_dict()
        for key in (
            "framework",
            "status",
            "detail",
            "version_spec",
            "package_manager",
            "lockfiles",
            "build_command",
            "routes",
            "metadata_mechanisms",
            "structured_data",
            "sitemap_robots_canonical",
            "rendering_hints",
            "deployment_hints",
            "content_sources",
            "ci_configs",
            "protected_paths",
            "env_files",
            "warnings",
            "evidence",
        ):
            assert key in payload
        assert payload["status"] == "SUPPORTED"
