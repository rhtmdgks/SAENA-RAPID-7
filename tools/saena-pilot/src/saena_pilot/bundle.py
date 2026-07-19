"""Skill-bundle enforcement — fail-closed at EVERY pilot start.

The pilot refuses to start unless the RAPID-7 root carries a positively
validated skill bundle:

1. `.claude/skills/manifest.json` must exist, parse, and declare
   `schema_version` "saena.skill-manifest/v1" with a non-empty `skills` list.
2. The canonical validator `tools/validation/skill_manifest.py` (w6-01) must
   exist and BOTH `validate-manifest --manifest …` and `validate-skills
   --skills-root …` must exit 0 when run as subprocesses.

Missing manifest, missing validator, parse failure, or validator failure all
map to the same outcome: `BundleInvalidError` → `EXIT_BUNDLE_INVALID`.

There is deliberately NO bypass: no CLI flag (the parser rejects any
`--skip-bundle`-ish flag as unknown), no environment variable is consulted,
and no alternate entry point skips this module — `cli.main` calls it before
any run mode proceeds.

Interpreter note: the validator subprocess uses `sys.executable` (the very
interpreter running saena-pilot — under `uv run saena-pilot` that IS the
uv-managed project python, equivalent to `uv run python`). An env-configurable
interpreter would itself be a bypass vector (point it at `/bin/true` and the
validator "passes"), so the interpreter is deliberately not configurable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from saena_pilot.errors import BundleInvalidError
from saena_pilot.models import BundleInfo, sha256_file

MANIFEST_SCHEMA_VERSION = "saena.skill-manifest/v1"
MANIFEST_RELPATH = Path(".claude") / "skills" / "manifest.json"
VALIDATOR_RELPATH = Path("tools") / "validation" / "skill_manifest.py"

#: Injectable subprocess runner type (tests substitute a recorder; the
#: default is a real, shell-free, list-argv subprocess call).
SubprocessRunner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — list argv, never shell
        list(argv),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def enforce_bundle(rapid7_root: Path, *, runner: SubprocessRunner | None = None) -> BundleInfo:
    """Validate the skill bundle or raise `BundleInvalidError`. Returns the
    positive proof (`BundleInfo`) that evidence records bind to."""
    run = runner if runner is not None else _default_runner
    manifest_path = rapid7_root / MANIFEST_RELPATH
    if not manifest_path.is_file():
        raise BundleInvalidError(
            f"skill manifest missing: {manifest_path} — the pilot cannot start "
            "without the validated 16-skill bundle (fail-closed, no bypass)",
            context={"manifest_path": str(manifest_path)},
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleInvalidError(
            f"skill manifest unreadable/unparsable: {manifest_path}: {exc}",
            context={"manifest_path": str(manifest_path)},
        ) from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BundleInvalidError(
            f"skill manifest {manifest_path} does not declare schema_version "
            f"{MANIFEST_SCHEMA_VERSION!r}",
            context={"manifest_path": str(manifest_path)},
        )

    skills = manifest.get("skills")
    if not isinstance(skills, list) or not skills:
        raise BundleInvalidError(
            f"skill manifest {manifest_path} has no skills — an empty bundle is invalid",
            context={"manifest_path": str(manifest_path)},
        )
    skill_names: list[str] = []
    for entry in skills:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise BundleInvalidError(
                f"skill manifest {manifest_path} contains an entry without a name",
                context={"manifest_path": str(manifest_path)},
            )
        skill_names.append(name)

    bundle_name = manifest.get("bundle_name")
    if not isinstance(bundle_name, str) or not bundle_name:
        raise BundleInvalidError(
            f"skill manifest {manifest_path} does not declare bundle_name",
            context={"manifest_path": str(manifest_path)},
        )

    validator_path = rapid7_root / VALIDATOR_RELPATH
    if not validator_path.is_file():
        raise BundleInvalidError(
            f"skill-bundle validator missing: {validator_path} — cannot positively "
            "validate the bundle, refusing to start (fail-closed)",
            context={"validator_path": str(validator_path)},
        )

    invocations: list[tuple[str, ...]] = [
        (
            sys.executable,
            str(validator_path),
            "validate-manifest",
            "--manifest",
            str(manifest_path),
        ),
        (
            sys.executable,
            str(validator_path),
            "validate-skills",
            "--manifest",
            str(manifest_path),
            "--skills-root",
            str(rapid7_root / ".claude" / "skills"),
        ),
    ]
    for argv in invocations:
        result = run(argv, rapid7_root)
        if result.returncode != 0:
            detail = (result.stdout or "").strip() or (result.stderr or "").strip()
            raise BundleInvalidError(
                f"skill-bundle validator rejected the bundle "
                f"(argv={list(argv)!r}, exit={result.returncode}): {detail}",
                context={"argv": list(argv), "returncode": result.returncode},
            )

    return BundleInfo(
        manifest_path=manifest_path,
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        manifest_sha256=sha256_file(manifest_path),
        bundle_name=bundle_name,
        skill_names=tuple(skill_names),
        validator_invocations=tuple(invocations),
    )
