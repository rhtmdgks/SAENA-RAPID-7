"""Fixture builders for w6-12 discovery/docker-preflight tests.

Deliberately self-contained: NOTHING is imported from `tests/unit/pilot`
(non-package test dirs insert themselves on sys.path — cross-directory module
imports are a name-collision footgun in full-suite runs). The small git/rapid7
helpers are an intentional local copy of the `_pilot_fixtures.py` style.

Framework fixture repos are minimal but real: package.json + config +
lockfile + a routes tree, exactly the signals the adapters classify.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

#: Secret-shaped-looking value planted in fixture `.env` files. Tests assert
#: it NEVER appears in any discovery output (contents are never read).
PLANTED_ENV_SECRET = "sk-live-" + "f0" * 12


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """List-argv git helper (never a shell, never chdir), hermetic identity."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "discovery-test",
            "GIT_AUTHOR_EMAIL": "discovery-test@example.com",
            "GIT_COMMITTER_NAME": "discovery-test",
            "GIT_COMMITTER_EMAIL": "discovery-test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )


def make_git_repo(path: Path, *, filename: str = "README.md") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    assert run_git(path, "init", "-q", "-b", "main").returncode == 0
    (path / filename).write_text("fixture\n", encoding="utf-8")
    commit_all(path)
    return path


def commit_all(repo: Path) -> None:
    assert run_git(repo, "add", "-A").returncode == 0
    result = run_git(repo, "commit", "-q", "-m", "fixture commit")
    assert result.returncode == 0, result.stderr


_VALIDATOR_SOURCE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    \"\"\"Fixture skill-manifest validator (local copy for w6-12 tests).\"\"\"
    import argparse
    import json
    import pathlib
    import sys


    def load(path):
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"manifest unreadable: {exc}")
            raise SystemExit(1)
        if not isinstance(data, dict):
            print("manifest is not an object")
            raise SystemExit(1)
        return data


    def main():
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        vm = sub.add_parser("validate-manifest")
        vm.add_argument("--manifest", required=True)
        vs = sub.add_parser("validate-skills")
        vs.add_argument("--manifest", required=True)
        vs.add_argument("--skills-root", required=True)
        args = parser.parse_args()

        if args.command == "validate-manifest":
            data = load(args.manifest)
            if data.get("schema_version") != "saena.skill-manifest/v1":
                print("bad schema_version")
                return 1
            skills = data.get("skills")
            if not isinstance(skills, list) or not skills:
                print("no skills")
                return 1
            if any(not isinstance(s, dict) or not s.get("name") for s in skills):
                print("unnamed skill")
                return 1
            return 0

        root = pathlib.Path(args.skills_root)
        data = load(root / "manifest.json")
        for skill in data.get("skills", []):
            name = skill.get("name", "")
            if not (root / name / "SKILL.md").is_file():
                print(f"missing SKILL.md for {name}")
                return 1
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    """
)

_FIXTURE_SKILLS = ("saena-intake", "saena-security-redteam", "ponytail")


def make_rapid7_fixture(path: Path) -> Path:
    """Fixture RAPID-7 root: git repo + valid fixture skill bundle."""
    make_git_repo(path)
    skills_root = path / ".claude" / "skills"
    skills_root.mkdir(parents=True)
    manifest = {
        "schema_version": "saena.skill-manifest/v1",
        "engine_scope": ["chatgpt-search"],
        "bundle_name": "saena-forge-core",
        "phase_order": ["bootstrap", "plan", "execute", "verify"],
        "skills": [
            {"name": name, "version": "0.1.0", "failure_behavior": "fail-closed"}
            for name in _FIXTURE_SKILLS
        ],
    }
    (skills_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for name in _FIXTURE_SKILLS:
        skill_dir = skills_root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: fixture\n---\n# {name}\n", encoding="utf-8"
        )
    validator = path / "tools" / "validation" / "skill_manifest.py"
    validator.parent.mkdir(parents=True)
    validator.write_text(_VALIDATOR_SOURCE, encoding="utf-8")
    commit_all(path)
    return path


def write_package_json(root: Path, payload: dict) -> None:  # type: ignore[type-arg]
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _touch(root: Path, rel: str, content: str = "// fixture\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_nextjs_repo(path: Path, *, lockfile: str = "package-lock.json") -> Path:
    write_package_json(
        path,
        {
            "name": "fixture-next",
            "packageManager": "npm@10.5.0",
            "scripts": {
                "build": "next build",
                "test": "vitest run",
                "lint": "next lint",
                "typecheck": "tsc --noEmit",
            },
            "dependencies": {"next": "^14.2.3", "react": "^18.3.0", "react-dom": "^18.3.0"},
        },
    )
    _touch(
        path,
        "next.config.mjs",
        "const nextConfig = { output: 'export' };\nexport default nextConfig;\n",
    )
    _touch(path, lockfile, "{}\n" if lockfile.endswith(".json") else "# lock\n")
    _touch(
        path,
        "app/layout.tsx",
        "export const metadata = { title: 'fixture' };\n"
        "export default function Layout({ children }) { return children; }\n",
    )
    _touch(path, "app/page.tsx", "export default function Page() { return null; }\n")
    _touch(path, "app/about/page.tsx", "export default function About() { return null; }\n")
    _touch(
        path,
        "app/jsonld.tsx",
        '// <script type="application/ld+json"> per schema.org\n',
    )
    _touch(path, "public/robots.txt", "User-agent: *\n")
    _touch(path, "vercel.json", "{}\n")
    _touch(path, ".github/workflows/ci.yml", "name: ci\n")
    _touch(path, ".gitignore", "# outputs\n.next/\nnode_modules/\n.env\n")
    (path / ".next").mkdir(exist_ok=True)
    _touch(path, ".next/BUILD_ID", "fixture\n")
    return path


def make_remix_repo(path: Path) -> Path:
    write_package_json(
        path,
        {
            "name": "fixture-remix",
            "scripts": {"build": "remix build", "dev": "remix dev"},
            "dependencies": {
                "@remix-run/node": "^2.9.0",
                "@remix-run/react": "^2.9.0",
                "react": "^18.3.0",
            },
        },
    )
    _touch(path, "remix.config.js", "module.exports = {};\n")
    _touch(path, "yarn.lock", "# lock\n")
    _touch(path, "app/root.tsx", "export default function Root() { return null; }\n")
    _touch(path, "app/routes/_index.tsx", "export default function Index() { return null; }\n")
    _touch(path, "app/routes/blog.$slug.tsx", "export default function Post() { return null; }\n")
    return path


def make_astro_repo(path: Path) -> Path:
    write_package_json(
        path,
        {
            "name": "fixture-astro",
            "scripts": {"build": "astro build"},
            "dependencies": {"astro": "^4.8.0", "@astrojs/sitemap": "^3.1.0"},
        },
    )
    _touch(path, "astro.config.mjs", "export default { output: 'hybrid' };\n")
    _touch(path, "pnpm-lock.yaml", "lockfileVersion: 9\n")
    _touch(path, "src/pages/index.astro", "---\ntitle: fixture\n---\n<html></html>\n")
    _touch(path, "src/pages/blog/post-1.md", "---\ntitle: post\n---\nbody\n")
    _touch(path, "src/content/notes/note.md", "---\nt: n\n---\nnote\n")
    return path


def make_nuxt_repo(path: Path) -> Path:
    write_package_json(
        path,
        {
            "name": "fixture-nuxt",
            "scripts": {"build": "nuxt build"},
            "dependencies": {"nuxt": "^3.11.0", "vue": "^3.4.0"},
        },
    )
    _touch(path, "nuxt.config.ts", "export default defineNuxtConfig({ ssr: false });\n")
    _touch(path, "package-lock.json", "{}\n")
    _touch(path, "pages/index.vue", "<template><div/></template>\n")
    _touch(path, "pages/about.vue", "<template><div/></template>\n")
    return path


def make_sveltekit_repo(path: Path) -> Path:
    write_package_json(
        path,
        {
            "name": "fixture-sveltekit",
            "scripts": {"build": "vite build", "check": "svelte-kit sync"},
            "devDependencies": {
                "@sveltejs/kit": "^2.5.0",
                "@sveltejs/adapter-static": "^3.0.0",
                "svelte": "^4.2.0",
            },
        },
    )
    _touch(path, "svelte.config.js", "import adapter from '@sveltejs/adapter-static';\n")
    _touch(path, "bun.lockb", "binary-lock\n")
    _touch(path, "src/routes/+page.svelte", "<h1>fixture</h1>\n")
    _touch(path, "src/routes/docs/+page.svelte", "<h1>docs</h1>\n")
    return path


def make_static_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _touch(path, "index.html", '<html><head><link rel="canonical" href="/"/></head></html>\n')
    _touch(path, "about.html", "<html><body>about</body></html>\n")
    _touch(path, "blog/post.html", "<html><body>post</body></html>\n")
    _touch(path, "robots.txt", "User-agent: *\n")
    return path


def make_wordpress_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "wp-content").mkdir()
    _touch(path, "wp-config.php", "<?php // config\n")
    _touch(path, "index.php", "<?php // entry\n")
    return path


def make_php_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _touch(path, "index.php", "<?php echo 'hi';\n")
    _touch(path, "composer.json", "{}\n")
    return path


def make_docker_shim(bin_dir: Path, kind: str) -> Path:
    """A `docker` PATH shim: 'healthy' | 'sick' | 'garbage' | 'empty' |
    'slow'. Tests prepend `bin_dir` to PATH so no real Docker is needed."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "docker"
    bodies = {
        "healthy": "#!/bin/sh\nprintf '\"28.1.1\"\\n'\nexit 0\n",
        "sick": (
            "#!/bin/sh\n"
            "echo 'Cannot connect to the Docker daemon at"
            " unix:///var/run/docker.sock' >&2\nexit 1\n"
        ),
        "garbage": "#!/bin/sh\necho 'not json at all'\nexit 0\n",
        "empty": "#!/bin/sh\nprintf '\"\"\\n'\nexit 0\n",
        "slow": "#!/bin/sh\nsleep 5\nexit 0\n",
    }
    script.write_text(bodies[kind], encoding="utf-8")
    script.chmod(0o755)
    return script
