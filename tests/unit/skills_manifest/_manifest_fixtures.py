"""Shared fixtures for the skill-manifest validator tests (w6-01).

`tests/` is not a package (repo convention — see
`tests/unit/forgectl/conftest.py`). Two `sys.path` inserts:

1. this directory, so sibling test modules can `from conftest import ...`;
2. `tools/validation`, so `import skill_manifest` resolves (the module is a
   single-file validator, deliberately not a workspace member — same as
   `render_gate_evidence.py`).

The REAL checked-in manifest is used as the base fixture (so it is itself
regression-tested), but every SKILL.md tree is synthetic under `tmp_path` —
the real `.claude/skills/` has no SKILL.md files in this worktree and tests
must never depend on them.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_VALIDATION_DIR = _REPO_ROOT / "tools" / "validation"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATION_DIR))

import skill_manifest  # noqa: E402

REAL_MANIFEST_PATH = _REPO_ROOT / ".claude" / "skills" / "manifest.json"
REAL_SCHEMA_PATH = _REPO_ROOT / ".claude" / "skills" / "manifest.schema.json"

__all__ = [
    "REAL_MANIFEST_PATH",
    "REAL_SCHEMA_PATH",
    "make_skill_md",
    "run_cli",
    "skill_manifest",
    "write_bundle",
    "write_manifest",
]


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    """Deep copy of the real checked-in manifest, safe to mutate."""
    data = json.loads(REAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def write_manifest(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_skill_md(
    name: str,
    *,
    description: str | None = None,
    fm_name: str | None = None,
    raw_frontmatter: str | None = None,
    extra_frontmatter: str = "",
    drop_section: str | None = None,
    section_overrides: dict[str, str] | None = None,
    section_lines: int = 5,
    workflow_steps: int = 6,
    include_engine_statement: bool = True,
    examples_extra: str = "",
    body_extra: str = "",
) -> str:
    """Render a SKILL.md that passes the full quality contract by default;
    keyword arguments introduce one targeted defect each."""
    if raw_frontmatter is not None:
        fm = raw_frontmatter
    else:
        desc = (
            description
            if description is not None
            else (
                f"Apply the {name} phase workflow for SAENA FORGE pilot runs; "
                "trigger when the controller reaches this skill's phase."
            )
        )
        fm = f"name: {fm_name or name}\ndescription: {desc}\n{extra_frontmatter}"

    overrides = section_overrides or {}
    filler = "\n".join(
        f"Deterministic instruction line {i + 1} for this section." for i in range(section_lines)
    )
    parts: list[str] = []
    for title in skill_manifest.REQUIRED_SECTIONS:
        if title == drop_section:
            continue
        parts.append(f"## {title}")
        if title in overrides:
            parts.append(overrides[title])
        elif title == "Purpose":
            engine_line = (
                "Engine scope: ChatGPT Search only; Google AI Overviews/AI Mode/"
                "Gemini are forbidden (NR-1).\n"
                if include_engine_statement
                else ""
            )
            parts.append(engine_line + filler)
        elif title == "Workflow":
            parts.append(
                "\n".join(
                    f"{i + 1}. Execute deterministic step {i + 1}." for i in range(workflow_steps)
                )
            )
        elif title == "Examples":
            parts.append(
                "Run against the fixture repo under tests/e2e/pilot/fixtures/nextjs-basic.\n"
                "Demo domain: https://www.example.com/docs (reserved example host).\n"
                "Alternate hosts: docs.example.org and site.example only.\n"
                "Fixture data: tests/unit/skills_manifest/fixtures/sample.json.\n"
                f"{examples_extra}"
            )
        else:
            parts.append(filler)
        parts.append("")
    body = "\n".join(parts) + ("\n" + body_extra if body_extra else "")
    return f"---\n{fm}---\n\n{body}\n"


def write_skill(skills_root: Path, name: str, content: str | None = None) -> Path:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content if content is not None else make_skill_md(name), encoding="utf-8")
    return path


def write_bundle(
    skills_root: Path,
    manifest: dict[str, Any],
    *,
    skip: set[str] | None = None,
    contents: dict[str, str] | None = None,
) -> Path:
    """Write a synthetic SKILL.md tree for every manifest entry (minus `skip`,
    with per-skill overrides via `contents`)."""
    skills_root.mkdir(parents=True, exist_ok=True)
    skip = skip or set()
    contents = contents or {}
    for entry in manifest["skills"]:
        name = entry["name"]
        if name in skip:
            continue
        write_skill(skills_root, name, contents.get(name))
    return skills_root


def run_cli(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str]:
    """Invoke `skill_manifest.main` and return (exit_code, stdout)."""
    code = skill_manifest.main(argv)
    return code, capsys.readouterr().out
