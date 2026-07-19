"""Shared helpers/fixtures for the w6-08 skill-bundle enforcement tests.

Fixture-building style derives from `tests/unit/skills_manifest/conftest.py`
(w6-01): the REAL checked-in manifest is the base fixture (regression-testing
it), synthetic SKILL.md trees are rendered under `tmp_path`, and each keyword
argument of `make_skill_md` introduces exactly one targeted defect.
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
if str(_VALIDATION_DIR) not in sys.path:  # direct-import safety outside pytest
    sys.path.insert(0, str(_VALIDATION_DIR))

import skill_bundle  # noqa: E402
import skill_manifest  # noqa: E402

REAL_MANIFEST_PATH = _REPO_ROOT / ".claude" / "skills" / "manifest.json"
REAL_SKILLS_ROOT = _REPO_ROOT / ".claude" / "skills"

__all__ = [
    "REAL_MANIFEST_PATH",
    "REAL_SKILLS_ROOT",
    "make_skill_md",
    "manifest_data",
    "run_cli",
    "skill_bundle",
    "skill_manifest",
    "write_bundle",
    "write_declared",
    "write_manifest",
    "write_skill",
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


def write_declared(tmp_path: Path, data: Any, name: str = "declared.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_skill_md(name: str, *, body_extra: str = "") -> str:
    """Render a SKILL.md that passes the full w6-01 quality contract."""
    fm = (
        f"name: {name}\n"
        f"description: Apply the {name} phase workflow for SAENA FORGE pilot runs; "
        "trigger when the controller reaches this skill's phase.\n"
    )
    filler = "\n".join(
        f"Deterministic instruction line {i + 1} for this section." for i in range(5)
    )
    parts: list[str] = []
    for title in skill_manifest.REQUIRED_SECTIONS:
        parts.append(f"## {title}")
        if title == "Purpose":
            parts.append(
                "Engine scope: ChatGPT Search only; Google AI Overviews/AI Mode/"
                "Gemini are forbidden (NR-1).\n" + filler
            )
        elif title == "Workflow":
            parts.append(
                "\n".join(f"{i + 1}. Execute deterministic step {i + 1}." for i in range(6))
            )
        elif title == "Examples":
            parts.append(
                "Run against the fixture repo under tests/e2e/pilot/fixtures/nextjs-basic.\n"
                "Demo domain: https://www.example.com/docs (reserved example host).\n"
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
    """Invoke `skill_bundle.main` and return (exit_code, stdout)."""
    code = skill_bundle.main(argv)
    return code, capsys.readouterr().out
