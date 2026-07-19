"""Fixture-building helpers for `saena_pilot` unit tests.

Deliberately NOT named `conftest`: several `tests/unit/*` directories insert
themselves on `sys.path` and a plain `from conftest import …` in a test
module resolves against whichever `conftest` module Python cached first in a
full-suite run. A unique module name sidesteps that collision entirely.

All git interaction is list-argv subprocess (never a shell, never chdir) with
a hermetic identity/env so host git config cannot influence fixtures.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """List-argv git helper for tests (never a shell, never chdir)."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "pilot-test",
            "GIT_AUTHOR_EMAIL": "pilot-test@example.com",
            "GIT_COMMITTER_NAME": "pilot-test",
            "GIT_COMMITTER_EMAIL": "pilot-test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )


def make_git_repo(path: Path, *, filename: str = "README.md") -> Path:
    """Create a git repository with one commit at `path`."""
    path.mkdir(parents=True, exist_ok=True)
    assert run_git(path, "init", "-q", "-b", "main").returncode == 0
    (path / filename).write_text("fixture\n", encoding="utf-8")
    assert run_git(path, "add", "-A").returncode == 0
    result = run_git(path, "commit", "-q", "-m", "fixture commit")
    assert result.returncode == 0, result.stderr
    return path


def head_sha(repo: Path) -> str:
    result = run_git(repo, "rev-parse", "HEAD")
    assert result.returncode == 0
    return result.stdout.strip()


FIXTURE_SKILLS = ("saena-intake", "saena-security-redteam", "ponytail")

_VALIDATOR_SOURCE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    \"\"\"Fixture skill-manifest validator (unit-test stand-in for w6-01's
    tools/validation/skill_manifest.py). Deterministic exit codes:
    0 = valid, 1 = invalid, 2 = usage.\"\"\"
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


def make_rapid7_fixture(path: Path) -> Path:
    """A fixture RAPID-7 root: git repo + valid fixture skill bundle +
    fixture validator script, all committed."""
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
            for name in FIXTURE_SKILLS
        ],
    }
    (skills_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for name in FIXTURE_SKILLS:
        skill_dir = skills_root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: fixture\n---\n# {name}\n", encoding="utf-8"
        )
    validator = path / "tools" / "validation" / "skill_manifest.py"
    validator.parent.mkdir(parents=True)
    validator.write_text(_VALIDATOR_SOURCE, encoding="utf-8")
    assert run_git(path, "add", "-A").returncode == 0
    assert run_git(path, "commit", "-q", "-m", "fixture bundle").returncode == 0
    return path
