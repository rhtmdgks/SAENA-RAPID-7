"""Bounded, read-only signal collection over a customer repository (w6-12).

Everything in this module is PURE FILE INSPECTION: no network, no dependency
installation, no execution of anything found in the customer repo. Customer
file contents are untrusted DATA — they are copied into report fields verbatim
(scripts, version specs) or summarized as evidence strings, never interpreted
as instructions.

Hard safety rules enforced here:

- `.env*` files are flagged by NAME only; their contents are NEVER read
  (`read_text_capped` refuses `.env*` basenames as defense in depth).
- Symlinks are never followed (walks) and never read (direct reads) so a
  hostile repo cannot alias host files into the report.
- Every walk/read is capped (bytes, file counts) so pathological trees cannot
  stall the pilot.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: Byte cap for package.json / config / gitignore reads.
MAX_JSON_BYTES = 2 * 1024 * 1024
#: Byte cap for marker scans over individual source files.
MAX_SCAN_BYTES = 512 * 1024
#: Cap on entries reported in a routes inventory.
MAX_ROUTE_ENTRIES = 200
#: Cap on files visited by a single bounded walk.
MAX_WALK_VISITS = 5000
#: Cap on verbatim .gitignore patterns carried into the report.
MAX_GITIGNORE_PATTERNS = 100

#: Directories a walk never descends into (generated/vendored trees).
SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        ".next",
        ".nuxt",
        ".output",
        ".svelte-kit",
        ".astro",
        ".vercel",
        ".netlify",
        ".turbo",
        ".cache",
        "dist",
        "build",
        "out",
        "coverage",
        "vendor",
        "__pycache__",
    }
)

#: Lockfile name → package manager (fixed, deterministic order).
LOCKFILE_MANAGERS: tuple[tuple[str, str], ...] = (
    ("package-lock.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
)

#: Config filename suffixes probed for each framework config stem.
CONFIG_SUFFIXES: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts", ".mts")

#: Deployment marker files (fixed list; presence only).
DEPLOYMENT_FILES: tuple[str, ...] = (
    "vercel.json",
    "netlify.toml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "wrangler.toml",
    "fly.toml",
    "render.yaml",
    "Procfile",
    "app.yaml",
    "amplify.yml",
    "firebase.json",
)

#: Single-file CI markers (``.github/workflows/*`` is listed separately).
CI_FILES: tuple[str, ...] = (
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    "Jenkinsfile",
    "bitbucket-pipelines.yml",
    ".travis.yml",
)

#: Candidate sitemap/robots artifacts (files; presence only).
SITEMAP_ROBOTS_FILES: tuple[str, ...] = (
    "robots.txt",
    "public/robots.txt",
    "static/robots.txt",
    "sitemap.xml",
    "public/sitemap.xml",
    "app/robots.ts",
    "app/robots.js",
    "app/sitemap.ts",
    "app/sitemap.js",
    "app/sitemap.mjs",
    "src/app/robots.ts",
    "src/app/sitemap.ts",
)


@dataclass(frozen=True, slots=True)
class PackageManifest:
    """package.json contents as DECLARED (verbatim strings, never resolved,
    never executed). Only ``str → str`` entries are carried; anything else in
    a hostile manifest is simply not represented (inert)."""

    present: bool
    parse_error: str | None
    dependencies: Mapping[str, str]
    dev_dependencies: Mapping[str, str]
    scripts: Mapping[str, str]
    package_manager_field: str | None

    def dep_spec(self, name: str) -> str | None:
        """Declared version spec for `name` (deps first, then devDeps)."""
        spec = self.dependencies.get(name)
        return spec if spec is not None else self.dev_dependencies.get(name)

    def has_dep(self, name: str) -> bool:
        return self.dep_spec(name) is not None


_EMPTY_MANIFEST = PackageManifest(
    present=False,
    parse_error=None,
    dependencies={},
    dev_dependencies={},
    scripts={},
    package_manager_field=None,
)


def read_text_capped(path: Path, cap: int = MAX_SCAN_BYTES) -> str | None:
    """Read a repo file for inspection, or `None` if it is unreadable, too
    large, a symlink, or a `.env*` file (whose contents are never read)."""
    if path.name.startswith(".env"):
        return None
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > cap:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _str_entries(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def load_package_manifest(root: Path) -> PackageManifest:
    """Parse package.json defensively. Malformed/hostile input never raises —
    it is reported as a parse error or silently reduced to str→str entries."""
    path = root / "package.json"
    try:
        if path.is_symlink():
            return PackageManifest(
                present=True,
                parse_error="package.json is a symlink — refused (not followed)",
                dependencies={},
                dev_dependencies={},
                scripts={},
                package_manager_field=None,
            )
        if not path.is_file():
            return _EMPTY_MANIFEST
        if path.stat().st_size > MAX_JSON_BYTES:
            return PackageManifest(
                present=True,
                parse_error=f"package.json exceeds {MAX_JSON_BYTES} bytes — not parsed",
                dependencies={},
                dev_dependencies={},
                scripts={},
                package_manager_field=None,
            )
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return PackageManifest(
            present=True,
            parse_error=f"package.json unreadable: {type(exc).__name__}",
            dependencies={},
            dev_dependencies={},
            scripts={},
            package_manager_field=None,
        )
    try:
        data = json.loads(raw)
    except ValueError:
        return PackageManifest(
            present=True,
            parse_error="package.json is not valid JSON",
            dependencies={},
            dev_dependencies={},
            scripts={},
            package_manager_field=None,
        )
    if not isinstance(data, dict):
        return PackageManifest(
            present=True,
            parse_error="package.json top level is not an object",
            dependencies={},
            dev_dependencies={},
            scripts={},
            package_manager_field=None,
        )
    manager_field = data.get("packageManager")
    return PackageManifest(
        present=True,
        parse_error=None,
        dependencies=_str_entries(data.get("dependencies")),
        dev_dependencies=_str_entries(data.get("devDependencies")),
        scripts=_str_entries(data.get("scripts")),
        package_manager_field=manager_field if isinstance(manager_field, str) else None,
    )


def find_config_file(root: Path, stem: str) -> str | None:
    """First existing `<stem><suffix>` in fixed suffix order, or None."""
    for suffix in CONFIG_SUFFIXES:
        candidate = root / f"{stem}{suffix}"
        if candidate.is_file() and not candidate.is_symlink():
            return f"{stem}{suffix}"
    return None


def list_lockfiles(root: Path) -> tuple[str, ...]:
    return tuple(name for name, _manager in LOCKFILE_MANAGERS if (root / name).is_file())


def package_manager(manifest: PackageManifest, lockfiles: tuple[str, ...]) -> str | None:
    """`packageManager` field wins; else a single unambiguous lockfile; else
    honestly None (never guessed)."""
    if manifest.package_manager_field:
        name = manifest.package_manager_field.split("@", 1)[0].strip()
        if name in {"npm", "pnpm", "yarn", "bun"}:
            return name
    managers = {dict(LOCKFILE_MANAGERS)[name] for name in lockfiles}
    if len(managers) == 1:
        return next(iter(managers))
    return None


def walk_files(
    root: Path,
    subdir: str = ".",
    *,
    suffixes: tuple[str, ...] | None = None,
    cap: int = MAX_ROUTE_ENTRIES,
) -> tuple[tuple[str, ...], bool]:
    """Bounded, sorted, symlink-free walk. Returns (relative posix paths,
    truncated?). Hidden and generated directories are never entered."""
    top = root if subdir == "." else root / subdir
    if top.is_symlink() or not top.is_dir():
        return (), False
    collected: list[str] = []
    visited = 0
    hit_visit_cap = False
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            visited += 1
            if visited > MAX_WALK_VISITS:
                hit_visit_cap = True
                break
            if suffixes is not None and not name.endswith(suffixes):
                continue
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            collected.append(full.relative_to(root).as_posix())
        if hit_visit_cap:
            break
    collected.sort()
    if len(collected) > cap:
        return tuple(collected[:cap]), True
    return tuple(collected), hit_visit_cap


def scan_markers(
    root: Path,
    rel_paths: tuple[str, ...],
    markers: tuple[str, ...],
    *,
    cap_files: int = 100,
    max_hits: int = 40,
) -> tuple[str, ...]:
    """Grep-style substring scan: `"relpath: marker"` evidence strings.
    Contents are matched as data only — nothing found is ever executed."""
    hits: list[str] = []
    for rel in rel_paths[:cap_files]:
        text = read_text_capped(root / rel)
        if text is None:
            continue
        for marker in markers:
            if marker in text:
                hits.append(f"{rel}: {marker}")
                if len(hits) >= max_hits:
                    return tuple(hits)
    return tuple(hits)


def env_file_names(root: Path) -> tuple[str, ...]:
    """`.env*` file NAMES at the repo root (contents never read)."""
    try:
        names = sorted(
            entry.name
            for entry in root.iterdir()
            if entry.name.startswith(".env") and entry.is_file() and not entry.is_symlink()
        )
    except OSError:
        return ()
    return tuple(names)


def gitignore_patterns(root: Path) -> tuple[str, ...]:
    """Non-comment .gitignore lines, verbatim, capped."""
    text = read_text_capped(root / ".gitignore", MAX_JSON_BYTES)
    if text is None:
        return ()
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return tuple(patterns[:MAX_GITIGNORE_PATTERNS])


def ci_configs(root: Path) -> tuple[str, ...]:
    found: list[str] = []
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and not workflows.is_symlink():
        with contextlib.suppress(OSError):
            found.extend(
                f".github/workflows/{entry.name}"
                for entry in sorted(workflows.iterdir(), key=lambda e: e.name)
                if entry.name.endswith((".yml", ".yaml")) and entry.is_file()
            )
    found.extend(name for name in CI_FILES if (root / name).is_file())
    return tuple(found)


def deployment_hints(root: Path) -> tuple[str, ...]:
    return tuple(name for name in DEPLOYMENT_FILES if (root / name).is_file())


def sitemap_robots_files(root: Path) -> tuple[str, ...]:
    return tuple(name for name in SITEMAP_ROBOTS_FILES if (root / name).is_file())
