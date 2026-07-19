"""Deterministic framework discovery adapters (w6-12, wave6-plan §1).

Pure file inspection: NO network, NO dependency installation, NO execution of
anything found in the customer repo. Detected commands are VERBATIM strings
from package.json scripts — reported, never run. v1 evaluates and reports
only; dependencies are never installed until the detected lockfile and
repository policy have been evaluated by a human.

Precedence (deterministic, tested):

1. Signals are scored per framework — config file present = specificity 3,
   meta-framework dependency declared = 2, framework CLI referenced in a
   script = 2, base-library dependency (react/vue/svelte) = 1.
2. Base libraries are only considered when NO meta-framework candidate
   exists (a Next.js repo with a `react` dep classifies `nextjs`).
3. The framework holding the single highest specificity wins. A tie between
   distinct frameworks at the top specificity is NEVER guessed — it yields
   `UNSUPPORTED` ("ambiguous") with every candidate's reasons listed.
4. With no JS candidates: WordPress/PHP markers → `UNSUPPORTED`
   (limited-support, report-only), HTML files → `static-html`, a package.json
   with no recognized framework → `UNKNOWN`, an empty tree → `UNKNOWN`.

Every field on `FrameworkDiscovery` is either positively determined or
`None`/empty — honestly not determinable, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saena_pilot.discovery._seam import DiscoveryResult, SupportStatus
from saena_pilot.discovery._signals import (
    LOCKFILE_MANAGERS,
    SKIP_DIRS,
    PackageManifest,
    ci_configs,
    deployment_hints,
    env_file_names,
    find_config_file,
    gitignore_patterns,
    list_lockfiles,
    load_package_manifest,
    package_manager,
    read_text_capped,
    scan_markers,
    sitemap_robots_files,
    walk_files,
)


@dataclass(frozen=True, slots=True)
class FrameworkDiscovery(DiscoveryResult):
    """Rich, typed discovery result. Extends the seam's `DiscoveryResult`
    (framework/status/detail) so it flows through `discover()` unchanged.

    All values are declared/observed facts: version specs verbatim from
    package.json (never resolved), commands verbatim from scripts (NEVER
    executed), hints carrying their evidence strings."""

    version_spec: str | None = None
    package_manager: str | None = None
    lockfiles: tuple[str, ...] = ()
    build_command: str | None = None
    test_command: str | None = None
    lint_command: str | None = None
    typecheck_command: str | None = None
    routes: tuple[str, ...] = ()
    routes_truncated: bool = False
    metadata_mechanisms: tuple[str, ...] = ()
    structured_data: tuple[str, ...] = ()
    sitemap_robots_canonical: tuple[str, ...] = ()
    rendering_hints: tuple[str, ...] = ()
    deployment_hints: tuple[str, ...] = ()
    content_sources: tuple[str, ...] = ()
    ci_configs: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    gitignore_patterns: tuple[str, ...] = ()
    env_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "status": self.status.value,
            "detail": self.detail,
            "version_spec": self.version_spec,
            "package_manager": self.package_manager,
            "lockfiles": list(self.lockfiles),
            "build_command": self.build_command,
            "test_command": self.test_command,
            "lint_command": self.lint_command,
            "typecheck_command": self.typecheck_command,
            "routes": list(self.routes),
            "routes_truncated": self.routes_truncated,
            "metadata_mechanisms": list(self.metadata_mechanisms),
            "structured_data": list(self.structured_data),
            "sitemap_robots_canonical": list(self.sitemap_robots_canonical),
            "rendering_hints": list(self.rendering_hints),
            "deployment_hints": list(self.deployment_hints),
            "content_sources": list(self.content_sources),
            "ci_configs": list(self.ci_configs),
            "protected_paths": list(self.protected_paths),
            "gitignore_patterns": list(self.gitignore_patterns),
            "env_files": list(self.env_files),
            "warnings": list(self.warnings),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class _Profile:
    """Static per-framework detection/inventory profile (data, not code)."""

    name: str
    display: str
    primary_deps: tuple[str, ...]
    config_stem: str | None
    script_tokens: tuple[str, ...]
    route_dirs: tuple[str, ...]
    route_suffixes: tuple[str, ...]
    output_dirs: tuple[str, ...]
    default_rendering: str


_META_PROFILES: tuple[_Profile, ...] = (
    _Profile(
        name="nextjs",
        display="Next.js",
        primary_deps=("next",),
        config_stem="next.config",
        script_tokens=("next build", "next dev", "next start", "next export"),
        route_dirs=("app", "pages", "src/app", "src/pages"),
        route_suffixes=(".js", ".jsx", ".ts", ".tsx", ".md", ".mdx"),
        output_dirs=(".next", "out"),
        default_rendering="hybrid SSR/SSG (Next.js default — framework default, not verified)",
    ),
    _Profile(
        name="remix",
        display="Remix",
        primary_deps=("@remix-run/react", "@remix-run/node", "@remix-run/serve", "@remix-run/dev"),
        config_stem="remix.config",
        script_tokens=("remix build", "remix dev", "remix vite:build"),
        route_dirs=("app/routes",),
        route_suffixes=(".js", ".jsx", ".ts", ".tsx", ".md", ".mdx"),
        output_dirs=("build", "public/build"),
        default_rendering="SSR (Remix default — framework default, not verified)",
    ),
    _Profile(
        name="astro",
        display="Astro",
        primary_deps=("astro",),
        config_stem="astro.config",
        script_tokens=("astro build", "astro dev"),
        route_dirs=("src/pages",),
        route_suffixes=(".astro", ".md", ".mdx", ".html", ".js", ".ts"),
        output_dirs=("dist", ".astro"),
        default_rendering="SSG (Astro default static output — framework default, not verified)",
    ),
    _Profile(
        name="nuxt",
        display="Nuxt",
        primary_deps=("nuxt", "nuxt3"),
        config_stem="nuxt.config",
        script_tokens=("nuxt build", "nuxt dev", "nuxi build"),
        route_dirs=("pages", "src/pages"),
        route_suffixes=(".vue",),
        output_dirs=(".nuxt", ".output", "dist"),
        default_rendering="SSR (Nuxt universal rendering — framework default, not verified)",
    ),
    _Profile(
        name="sveltekit",
        display="SvelteKit",
        primary_deps=("@sveltejs/kit",),
        config_stem="svelte.config",
        script_tokens=("svelte-kit",),
        route_dirs=("src/routes",),
        route_suffixes=(".svelte", ".js", ".ts"),
        output_dirs=(".svelte-kit", "build"),
        default_rendering="SSR with adapter (SvelteKit default — framework default, not verified)",
    ),
)

_BASE_PROFILES: tuple[_Profile, ...] = (
    _Profile(
        name="react",
        display="React (no meta-framework)",
        primary_deps=("react",),
        config_stem=None,
        script_tokens=(),
        route_dirs=("src/pages", "src/routes"),
        route_suffixes=(".js", ".jsx", ".ts", ".tsx"),
        output_dirs=("build", "dist"),
        default_rendering="CSR (client-rendered SPA — no meta-framework detected, not verified)",
    ),
    _Profile(
        name="vue",
        display="Vue (no meta-framework)",
        primary_deps=("vue",),
        config_stem=None,
        script_tokens=(),
        route_dirs=("src/pages", "src/views", "src/routes"),
        route_suffixes=(".vue",),
        output_dirs=("dist",),
        default_rendering="CSR (client-rendered SPA — no meta-framework detected, not verified)",
    ),
    _Profile(
        name="svelte",
        display="Svelte (no SvelteKit)",
        primary_deps=("svelte",),
        config_stem=None,
        script_tokens=(),
        route_dirs=("src/routes",),
        route_suffixes=(".svelte",),
        output_dirs=("dist", "build"),
        default_rendering="CSR (client-rendered SPA — no meta-framework detected, not verified)",
    ),
)

_STATIC_PROFILE = _Profile(
    name="static-html",
    display="static HTML",
    primary_deps=(),
    config_stem=None,
    script_tokens=(),
    route_dirs=(".",),
    route_suffixes=(".html", ".htm"),
    output_dirs=(),
    default_rendering="static files (served as-is)",
)

_PROFILES_BY_NAME: dict[str, _Profile] = {
    profile.name: profile for profile in (*_META_PROFILES, *_BASE_PROFILES, _STATIC_PROFILE)
}

#: Generated dirs always classified protected when present, framework aside.
_ALWAYS_GENERATED = (
    "node_modules",
    ".next",
    ".nuxt",
    ".output",
    ".svelte-kit",
    ".astro",
    ".turbo",
    ".cache",
    ".vercel",
    ".netlify",
    "coverage",
)

_METADATA_MARKERS = (
    "export const metadata",
    "generateMetadata",
    "next/head",
    "next-seo",
    "react-helmet",
    "<svelte:head",
    "useHead(",
    "useSeoMeta(",
    "<Head",
)
_METADATA_DEPS = (
    "next-seo",
    "react-helmet",
    "react-helmet-async",
    "@unhead/vue",
    "@vueuse/head",
    "astro-seo",
    "svelte-meta-tags",
)
_STRUCTURED_MARKERS = ("application/ld+json", "schema.org")
_STRUCTURED_DEPS = ("schema-dts", "next-seo", "astro-seo")
_CANONICAL_MARKERS = ('rel="canonical"', "rel='canonical'")
_SITEMAP_DEPS = ("next-sitemap", "@astrojs/sitemap", "@nuxtjs/sitemap", "sitemap", "svelte-sitemap")
#: (normalized config token, hint text). Config text is normalized to single
#: quotes before matching so both quote styles hit.
_RENDER_CONFIG_TOKENS = (
    ("output: 'export'", "static export configured (SSG hint)"),
    ("output: 'static'", "static output configured (SSG hint)"),
    ("output: 'server'", "server output configured (SSR hint)"),
    ("output: 'hybrid'", "hybrid output configured (SSR+SSG hint)"),
    ("output: 'standalone'", "standalone server build configured (SSR hint)"),
    ("ssr: false", "ssr disabled in config (SPA/CSR hint)"),
    ("adapter-static", "static adapter configured (SSG hint)"),
    ("prerender", "prerender referenced in config (SSG hint)"),
)
_CONTENT_DIRS = ("content", "src/content", "posts", "_posts", "docs")
_CONTENT_DEPS = (
    "contentlayer",
    "@nuxt/content",
    "@astrojs/mdx",
    "gray-matter",
    "contentful",
    "@sanity/client",
    "sanity",
    "@strapi/strapi",
    "decap-cms-app",
    "netlify-cms-app",
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    profile: _Profile
    specificity: int
    evidence: tuple[str, ...]


def _meta_candidates(root: Path, manifest: PackageManifest) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for profile in _META_PROFILES:
        evidence: list[str] = []
        specificity = 0
        config = find_config_file(root, profile.config_stem) if profile.config_stem else None
        dep_evidence = [
            f"package.json dependency {name}@{manifest.dep_spec(name)}"
            for name in profile.primary_deps
            if manifest.has_dep(name)
        ]
        # svelte.config.* is shared with plain Svelte+Vite setups: it only
        # counts as a SvelteKit signal alongside the @sveltejs/kit dep.
        if config is not None and (profile.name != "sveltekit" or dep_evidence):
            evidence.append(f"{config} present")
            specificity = 3
        if dep_evidence:
            evidence.extend(dep_evidence)
            specificity = max(specificity, 2)
        script_hits = [
            f"script {key!r} references {token!r}"
            for key, value in sorted(manifest.scripts.items())
            for token in profile.script_tokens
            if token in value
        ]
        if script_hits:
            evidence.extend(script_hits[:3])
            specificity = max(specificity, 2)
        if specificity > 0:
            candidates.append(_Candidate(profile, specificity, tuple(evidence)))
    return candidates


def _base_candidates(manifest: PackageManifest) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for profile in _BASE_PROFILES:
        evidence = [
            f"package.json dependency {name}@{manifest.dep_spec(name)}"
            for name in profile.primary_deps
            if manifest.has_dep(name)
        ]
        if evidence:
            candidates.append(_Candidate(profile, 1, tuple(evidence)))
    return candidates


def _wordpress_markers(root: Path) -> tuple[str, ...]:
    markers: list[str] = []
    if (root / "wp-content").is_dir():
        markers.append("wp-content/ directory present")
    if (root / "wp-config.php").is_file():
        markers.append("wp-config.php present")
    if (root / "wp-includes").is_dir():
        markers.append("wp-includes/ directory present")
    return tuple(markers)


def _php_markers(root: Path) -> tuple[str, ...]:
    markers: list[str] = []
    try:
        php_files = sorted(
            entry.name
            for entry in root.iterdir()
            if entry.name.endswith(".php") and entry.is_file()
        )
    except OSError:
        php_files = []
    if php_files:
        markers.append(f"root-level PHP files: {', '.join(php_files[:5])}")
    if (root / "composer.json").is_file():
        markers.append("composer.json present")
    return tuple(markers)


def _routes(root: Path, profile: _Profile) -> tuple[tuple[str, ...], bool]:
    collected: list[str] = []
    truncated = False
    for route_dir in profile.route_dirs:
        files, was_truncated = walk_files(root, route_dir, suffixes=profile.route_suffixes)
        collected.extend(files)
        truncated = truncated or was_truncated
    unique = sorted(set(collected))
    if len(unique) > 200:
        return tuple(unique[:200]), True
    return tuple(unique), truncated


def _rendering_hints(root: Path, profile: _Profile, manifest: PackageManifest) -> tuple[str, ...]:
    hints: list[str] = []
    config = find_config_file(root, profile.config_stem) if profile.config_stem else None
    if config is not None:
        text = read_text_capped(root / config)
        if text is not None:
            normalized = text.replace('"', "'")
            hints.extend(
                f"{config}: {hint}" for token, hint in _RENDER_CONFIG_TOKENS if token in normalized
            )
    hints.extend(
        f"script {key!r} runs 'next export' (SSG hint)"
        for key, value in sorted(manifest.scripts.items())
        if "next export" in value
    )
    hints.append(f"default: {profile.default_rendering}")
    return tuple(hints)


def _content_sources(root: Path, manifest: PackageManifest) -> tuple[str, ...]:
    sources: list[str] = []
    for rel in _CONTENT_DIRS:
        directory = root / rel
        if directory.is_dir() and not directory.is_symlink():
            files, truncated = walk_files(root, rel, suffixes=(".md", ".mdx"))
            if files:
                suffix = "+" if truncated else ""
                sources.append(f"{rel}/: {len(files)}{suffix} markdown file(s)")
    sources.extend(
        f"package.json dependency {name}@{manifest.dep_spec(name)} (content/CMS marker)"
        for name in _CONTENT_DEPS
        if manifest.has_dep(name)
    )
    return tuple(sources)


def _protected_paths(
    root: Path, profile: _Profile | None, lockfiles: tuple[str, ...], env_files: tuple[str, ...]
) -> tuple[str, ...]:
    """Paths the pilot must never target for writes: existing generated/build
    output dirs, lockfiles, and .env* files (names only)."""
    protected: set[str] = set(lockfiles) | set(env_files)
    output_candidates = (set(_ALWAYS_GENERATED) | set(SKIP_DIRS)) - {".git"}
    if profile is not None:
        output_candidates |= set(profile.output_dirs)
    protected.update(f"{name}/" for name in output_candidates if (root / name).is_dir())
    return tuple(sorted(protected))


def _scan_targets(root: Path, routes: tuple[str, ...]) -> tuple[str, ...]:
    """Files worth marker-scanning: routes plus common layout/head files and
    root html files (all reads bounded; .env* never read)."""
    extras: list[str] = []
    for rel in (
        "app/layout.tsx",
        "app/layout.jsx",
        "app/layout.js",
        "src/app/layout.tsx",
        "app/root.tsx",
        "src/routes/+layout.svelte",
        "app.vue",
        "src/App.vue",
        "index.html",
        "public/index.html",
    ):
        if (root / rel).is_file():
            extras.append(rel)
    return tuple(dict.fromkeys((*routes, *extras)))


def _astro_frontmatter_evidence(root: Path, routes: tuple[str, ...]) -> tuple[str, ...]:
    hits: list[str] = []
    for rel in routes[:50]:
        if not rel.endswith((".astro", ".md", ".mdx")):
            continue
        text = read_text_capped(root / rel)
        if text is not None and text.startswith("---"):
            hits.append(f"{rel}: frontmatter block")
            if len(hits) >= 10:
                break
    return tuple(hits)


class FrameworkDetector:
    """The composite discovery adapter wired into the pilot CLI. Collects all
    signals once, resolves precedence deterministically, and always returns a
    result (SUPPORTED / UNSUPPORTED / UNKNOWN) — it never raises on hostile
    or unparsable customer content and never guesses."""

    def detect(self, customer_root: Path) -> FrameworkDiscovery | None:
        root = customer_root
        manifest = load_package_manifest(root)
        lockfiles = list_lockfiles(root)
        env_files = env_file_names(root)
        warnings: list[str] = []
        if env_files:
            warnings.append(
                f".env file(s) present ({', '.join(env_files)}) — flagged only; "
                "contents were NOT read and never appear in any pilot artifact"
            )
        if len({dict(LOCKFILE_MANAGERS)[name] for name in lockfiles}) > 1:
            warnings.append(
                f"multiple lockfiles present ({', '.join(lockfiles)}) — package manager "
                "not determinable from lockfiles alone"
            )
        if manifest.parse_error is not None:
            warnings.append(f"package.json: {manifest.parse_error}")

        meta = _meta_candidates(root, manifest)
        base = _base_candidates(manifest) if not meta else []
        candidates = meta or base
        wordpress = _wordpress_markers(root)
        php = _php_markers(root)

        if candidates:
            top = max(candidate.specificity for candidate in candidates)
            winners = [candidate for candidate in candidates if candidate.specificity == top]
            if len(winners) > 1:
                reasons = "; ".join(
                    f"{candidate.profile.name} (specificity {candidate.specificity}: "
                    f"{', '.join(candidate.evidence)})"
                    for candidate in sorted(winners, key=lambda c: c.profile.name)
                )
                return self._build(
                    root,
                    manifest,
                    lockfiles,
                    env_files,
                    profile=None,
                    framework="ambiguous",
                    status=SupportStatus.UNSUPPORTED,
                    detail=(
                        "ambiguous framework signals — tie at highest specificity is never "
                        f"guessed; limited support (report-only). Candidates: {reasons}"
                    ),
                    evidence=tuple(e for candidate in winners for e in candidate.evidence),
                    warnings=tuple(warnings),
                )
            winner = winners[0]
            if wordpress or php:
                warnings.append(
                    "WordPress/PHP markers also present alongside the detected JS framework: "
                    + "; ".join((*wordpress, *php))
                )
            version_spec = next(
                (
                    manifest.dep_spec(name)
                    for name in winner.profile.primary_deps
                    if manifest.has_dep(name)
                ),
                None,
            )
            return self._build(
                root,
                manifest,
                lockfiles,
                env_files,
                profile=winner.profile,
                framework=winner.profile.name,
                status=SupportStatus.SUPPORTED,
                detail=(
                    f"{winner.profile.display} detected (specificity {winner.specificity}): "
                    + "; ".join(winner.evidence)
                ),
                evidence=winner.evidence,
                warnings=tuple(warnings),
                version_spec=version_spec,
            )

        if wordpress:
            return self._build(
                root,
                manifest,
                lockfiles,
                env_files,
                profile=None,
                framework="wordpress",
                status=SupportStatus.UNSUPPORTED,
                detail=(
                    "WordPress markers found — limited support: report-only; WordPress/PHP "
                    "runtimes are outside pilot v1 write scope. Markers: " + "; ".join(wordpress)
                ),
                evidence=wordpress,
                warnings=tuple(warnings),
            )
        if php:
            return self._build(
                root,
                manifest,
                lockfiles,
                env_files,
                profile=None,
                framework="php",
                status=SupportStatus.UNSUPPORTED,
                detail=(
                    "PHP project markers found — limited support: report-only; PHP runtimes "
                    "are outside pilot v1 write scope. Markers: " + "; ".join(php)
                ),
                evidence=php,
                warnings=tuple(warnings),
            )

        html_files, html_truncated = walk_files(root, ".", suffixes=_STATIC_PROFILE.route_suffixes)
        if html_files:
            return self._build(
                root,
                manifest,
                lockfiles,
                env_files,
                profile=_STATIC_PROFILE,
                framework="static-html",
                status=SupportStatus.SUPPORTED,
                detail=(
                    f"static HTML site — {len(html_files)}"
                    f"{'+' if html_truncated else ''} .html file(s), no framework signals"
                ),
                evidence=(f"{len(html_files)} html file(s), e.g. {html_files[0]}",),
                warnings=tuple(warnings),
            )

        if manifest.present:
            return self._build(
                root,
                manifest,
                lockfiles,
                env_files,
                profile=None,
                framework="unknown",
                status=SupportStatus.UNKNOWN,
                detail=(
                    "package.json present but no recognized framework dependency, config "
                    "file, or html tree — framework unknown (not guessed)"
                ),
                evidence=("package.json present without recognized framework signals",),
                warnings=tuple(warnings),
            )
        return self._build(
            root,
            manifest,
            lockfiles,
            env_files,
            profile=None,
            framework="unknown",
            status=SupportStatus.UNKNOWN,
            detail=(
                "no framework signals found (no package.json, no config files, no html, "
                "no php markers) — framework unknown (not guessed)"
            ),
            evidence=(),
            warnings=tuple(warnings),
        )

    def _build(
        self,
        root: Path,
        manifest: PackageManifest,
        lockfiles: tuple[str, ...],
        env_files: tuple[str, ...],
        *,
        profile: _Profile | None,
        framework: str,
        status: SupportStatus,
        detail: str,
        evidence: tuple[str, ...],
        warnings: tuple[str, ...],
        version_spec: str | None = None,
    ) -> FrameworkDiscovery:
        routes: tuple[str, ...] = ()
        routes_truncated = False
        rendering: tuple[str, ...] = ()
        if profile is not None:
            routes, routes_truncated = _routes(root, profile)
            rendering = _rendering_hints(root, profile, manifest)
        targets = _scan_targets(root, routes)
        metadata = list(scan_markers(root, targets, _METADATA_MARKERS))
        metadata.extend(
            f"package.json dependency {name}@{manifest.dep_spec(name)} (metadata marker)"
            for name in _METADATA_DEPS
            if manifest.has_dep(name)
        )
        metadata.extend(_astro_frontmatter_evidence(root, routes))
        structured = list(scan_markers(root, targets, _STRUCTURED_MARKERS))
        structured.extend(
            f"package.json dependency {name}@{manifest.dep_spec(name)} (structured-data marker)"
            for name in _STRUCTURED_DEPS
            if manifest.has_dep(name)
        )
        seo = list(sitemap_robots_files(root))
        seo.extend(scan_markers(root, targets, _CANONICAL_MARKERS, max_hits=10))
        seo.extend(
            f"package.json dependency {name}@{manifest.dep_spec(name)} (sitemap plugin)"
            for name in _SITEMAP_DEPS
            if manifest.has_dep(name)
        )
        return FrameworkDiscovery(
            framework=framework,
            status=status,
            detail=detail,
            version_spec=version_spec,
            package_manager=package_manager(manifest, lockfiles),
            lockfiles=lockfiles,
            build_command=manifest.scripts.get("build"),
            test_command=manifest.scripts.get("test"),
            lint_command=manifest.scripts.get("lint"),
            typecheck_command=(
                manifest.scripts.get("typecheck")
                if manifest.scripts.get("typecheck") is not None
                else manifest.scripts.get("type-check")
            ),
            routes=routes,
            routes_truncated=routes_truncated,
            metadata_mechanisms=tuple(dict.fromkeys(metadata)),
            structured_data=tuple(dict.fromkeys(structured)),
            sitemap_robots_canonical=tuple(dict.fromkeys(seo)),
            rendering_hints=rendering,
            deployment_hints=deployment_hints(root),
            content_sources=_content_sources(root, manifest),
            ci_configs=ci_configs(root),
            protected_paths=_protected_paths(root, profile, lockfiles, env_files),
            gitignore_patterns=gitignore_patterns(root),
            env_files=env_files,
            warnings=warnings,
            evidence=evidence,
        )


def default_adapters() -> tuple[FrameworkDetector, ...]:
    """The adapter chain the pilot CLI wires into `discover()`."""
    return (FrameworkDetector(),)
