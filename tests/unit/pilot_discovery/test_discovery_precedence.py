"""Deterministic precedence/ambiguity matrix: config beats dep, meta beats
base, ties are never guessed."""

from __future__ import annotations

from pathlib import Path

from _discovery_fixtures import make_nextjs_repo, write_package_json
from saena_pilot.discovery import FrameworkDetector, FrameworkDiscovery, SupportStatus


def _detect(root: Path) -> FrameworkDiscovery:
    result = FrameworkDetector().detect(root)
    assert isinstance(result, FrameworkDiscovery)
    return result


def test_nextjs_repo_with_react_dep_classifies_nextjs_not_react(tmp_path: Path) -> None:
    # The mission's canonical case: `react` is in dependencies but the meta
    # framework must win.
    result = _detect(make_nextjs_repo(tmp_path / "repo"))
    assert result.framework == "nextjs"
    assert result.framework != "react"


def test_meta_dep_beats_base_dep_without_config(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_package_json(
        root, {"dependencies": {"next": "^14.0.0", "react": "^18.0.0", "vue": "^3.0.0"}}
    )
    result = _detect(root)
    assert result.framework == "nextjs"


def test_config_file_beats_foreign_dependency(tmp_path: Path) -> None:
    # astro dep (specificity 2) vs next.config.js (specificity 3): the
    # higher-specificity config file wins deterministically.
    root = tmp_path / "repo"
    write_package_json(root, {"dependencies": {"astro": "^4.0.0"}})
    (root / "next.config.js").write_text("module.exports = {};\n", encoding="utf-8")
    result = _detect(root)
    assert result.framework == "nextjs"
    assert "next.config.js present" in result.detail


def test_two_configs_tie_is_unsupported_with_reasons(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "next.config.js").write_text("module.exports = {};\n", encoding="utf-8")
    (root / "nuxt.config.ts").write_text("export default {};\n", encoding="utf-8")
    result = _detect(root)
    assert result.status is SupportStatus.UNSUPPORTED
    assert result.framework == "ambiguous"
    assert "never" in result.detail and "guessed" in result.detail
    assert "nextjs" in result.detail and "nuxt" in result.detail
    assert "next.config.js present" in result.detail
    assert "nuxt.config.ts present" in result.detail


def test_two_base_deps_tie_is_unsupported(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_package_json(root, {"dependencies": {"react": "^18.0.0", "vue": "^3.0.0"}})
    result = _detect(root)
    assert result.status is SupportStatus.UNSUPPORTED
    assert result.framework == "ambiguous"
    assert "react" in result.detail and "vue" in result.detail


def test_two_meta_deps_tie_is_unsupported(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_package_json(root, {"dependencies": {"next": "^14.0.0", "nuxt": "^3.11.0"}})
    result = _detect(root)
    assert result.status is SupportStatus.UNSUPPORTED
    assert result.framework == "ambiguous"


def test_script_reference_counts_as_meta_signal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_package_json(
        root,
        {"scripts": {"build": "next build"}, "dependencies": {"react": "^18.0.0"}},
    )
    result = _detect(root)
    assert result.framework == "nextjs"
    assert any("references" in item for item in result.evidence)


def test_svelte_config_alone_is_not_sveltekit(tmp_path: Path) -> None:
    # svelte.config.* is shared with plain Svelte+Vite; without the
    # @sveltejs/kit dep it must NOT be claimed as SvelteKit.
    root = tmp_path / "repo"
    write_package_json(root, {"devDependencies": {"svelte": "^4.2.0"}})
    (root / "svelte.config.js").write_text("export default {};\n", encoding="utf-8")
    assert _detect(root).framework == "svelte"


def test_detection_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    root = make_nextjs_repo(tmp_path / "repo")
    first = _detect(root)
    second = _detect(root)
    assert first == second
    assert first.to_dict() == second.to_dict()
