#!/usr/bin/env python3
"""Fail-closed sync + drift gate for the installable skill pack (Wave 6 w6-09).

Canonical source (wave6-plan D-3): ``.claude/skills/<name>/SKILL.md``.
Installable copy: ``plugins/saena-skill-pack/skills/<name>/…`` — GENERATED,
never hand-edited. One canonical source, no silent drift.

Two subcommands (both exit 0 only when fully green):

``sync [--repo-root <dir>] [--json]``
    Regenerate the plugin ``skills/`` tree from ``.claude/skills/``:
    byte-copy every file of each of the 16 manifest skills, prune stale
    dirs/files under the plugin skills root. REFUSES (exit 2, no writes)
    when the canonical manifest is invalid — validation is delegated to
    ``skill_manifest.validate_manifest_data`` (w6-01 SSOT validator), or
    when a manifest skill has no canonical SKILL.md on disk.

``check [--repo-root <dir>] [--json]``
    DRIFT GATE, read-only, fail-closed. Byte-equality in BOTH directions
    (missing copy, stale/extra copy, extra file inside a copied skill dir,
    content mismatch ⇒ nonzero with one finding per file). Also verifies:
    ``plugins/saena-skill-pack/.claude-plugin/plugin.json`` exists, parses,
    is named ``saena-skill-pack`` and its version equals the (single)
    version shared by all manifest skills; and the repo-root
    ``.claude-plugin/marketplace.json`` lists EXACTLY the saena-skill-pack
    plugin with ``metadata.pluginRoot == "./plugins"``.

Exit codes: 0 green; 1 drift/check failure; 2 manifest invalid (sync
refusal uses this too); 3 usage error.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Same-directory sibling (tools/validation/ is not a package; script and
# test invocations both put this directory on sys.path).
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(_THIS_DIR))

import skill_manifest  # noqa: E402

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_MANIFEST_INVALID = 2
EXIT_USAGE = 3

REPORT_SCHEMA_VERSION = "saena.skill-pack-report/v1"
PLUGIN_NAME = "saena-skill-pack"
MARKETPLACE_NAME = "saena-rapid-7"
PLUGIN_ROOT_REL = "./plugins"
#: Marketplace-ROOT-relative source path. Empirically verified with claude CLI
#: 2.1.205: `./`-prefixed sources resolve against the marketplace root, NOT
#: against metadata.pluginRoot (a `./saena-skill-pack` source validates but
#: fails `claude plugin install` with "Source path does not exist"), and bare
#: names (`saena-skill-pack`) are rejected by `claude plugin validate`.
PLUGIN_SOURCE_REL = "./plugins/saena-skill-pack"

CANONICAL_SKILLS_REL = Path(".claude/skills")
PLUGIN_DIR_REL = Path("plugins") / PLUGIN_NAME
PLUGIN_SKILLS_REL = PLUGIN_DIR_REL / "skills"
PLUGIN_JSON_REL = PLUGIN_DIR_REL / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON_REL = Path(".claude-plugin") / "marketplace.json"

#: plugin.json keys this repo commits to shipping (subset check, not closed —
#: the claude CLI owns the full metadata surface, `claude plugin validate
#: --strict` is the authoritative gate for it).
PLUGIN_JSON_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"name", "displayName", "version", "description", "author", "repository", "license"}
)


@dataclass(frozen=True)
class Finding:
    """One sync/check failure. `where` is a path, skill name, or '-'."""

    code: str
    where: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "where": self.where, "message": self.message}


def _default_repo_root() -> Path:
    # tools/validation/skill_pack_sync.py -> repo root two levels up.
    return _THIS_DIR.parent.parent


def _load_json(path: Path, label: str) -> tuple[object, list[Finding]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("unreadable", str(path), f"{label} unreadable: {exc}")]
    try:
        return json.loads(raw), []
    except json.JSONDecodeError as exc:
        return None, [Finding("malformed-json", str(path), f"{label} is not valid JSON: {exc}")]


# --------------------------------------------------------------------------- #
# Manifest gate (delegated to the w6-01 SSOT validator)
# --------------------------------------------------------------------------- #
def _load_valid_manifest(repo_root: Path) -> tuple[dict[str, str], list[Finding]]:
    """Return {skill name -> version} from a VALID manifest, else findings."""
    manifest_path = repo_root / CANONICAL_SKILLS_REL / "manifest.json"
    data, findings = _load_json(manifest_path, "manifest")
    if findings:
        return {}, findings
    issues = skill_manifest.validate_manifest_data(data)
    if issues:
        return {}, [
            Finding(f"manifest:{issue.code}", issue.where, issue.message) for issue in issues
        ]
    assert isinstance(data, dict)
    versions: dict[str, str] = {}
    for entry in data["skills"]:
        assert isinstance(entry, dict)  # guaranteed by the validator above
        versions[str(entry["name"])] = str(entry["version"])
    return versions, []


def _skill_files(skill_dir: Path) -> list[Path]:
    """All regular files under one skill dir, as sorted relative paths."""
    return sorted(path.relative_to(skill_dir) for path in skill_dir.rglob("*") if path.is_file())


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #
def run_sync(repo_root: Path) -> tuple[list[Finding], list[str], int]:
    """Regenerate the plugin skills tree. Returns (findings, actions, exit)."""
    names, findings = _load_valid_manifest(repo_root)
    canonical_root = repo_root / CANONICAL_SKILLS_REL
    for name in sorted(names):
        if not (canonical_root / name / "SKILL.md").is_file():
            findings.append(
                Finding(
                    "canonical-missing",
                    name,
                    f"manifest skill `{name}` has no canonical "
                    f"`{CANONICAL_SKILLS_REL / name / 'SKILL.md'}` — refusing to sync",
                )
            )
    if findings:
        return findings, [], EXIT_MANIFEST_INVALID

    plugin_skills = repo_root / PLUGIN_SKILLS_REL
    plugin_skills.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    # Prune anything under the plugin skills root that is not a manifest skill.
    for entry in sorted(plugin_skills.iterdir()):
        if entry.name in names and entry.is_dir():
            continue
        actions.append(f"prune {entry.relative_to(repo_root)}")
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for name in sorted(names):
        src = canonical_root / name
        dst = plugin_skills / name
        if (
            dst.exists()
            and _skill_files(src) == _skill_files(dst)
            and all(filecmp.cmp(src / rel, dst / rel, shallow=False) for rel in _skill_files(src))
        ):
            continue  # already byte-identical — idempotent no-op
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        actions.append(f"copy {name}")
    return [], actions, EXIT_OK


# --------------------------------------------------------------------------- #
# check (drift gate)
# --------------------------------------------------------------------------- #
def _check_tree_drift(repo_root: Path, names: set[str], findings: list[Finding]) -> None:
    canonical_root = repo_root / CANONICAL_SKILLS_REL
    plugin_skills = repo_root / PLUGIN_SKILLS_REL
    if not plugin_skills.is_dir():
        findings.append(
            Finding(
                "plugin-skills-missing",
                str(PLUGIN_SKILLS_REL),
                "plugin skills directory missing — run `skill_pack_sync.py sync`",
            )
        )
        return

    on_disk = {entry.name for entry in plugin_skills.iterdir() if entry.is_dir()}
    stray_files = [entry for entry in plugin_skills.iterdir() if not entry.is_dir()]
    for stray in sorted(stray_files):
        findings.append(
            Finding(
                "extra-copy",
                str(stray.relative_to(repo_root)),
                "unexpected file at the plugin skills root (generated tree holds skill dirs only)",
            )
        )
    for name in sorted(names - on_disk):
        findings.append(
            Finding(
                "missing-copy",
                name,
                f"manifest skill `{name}` has no copy under `{PLUGIN_SKILLS_REL}` — "
                "run `skill_pack_sync.py sync`",
            )
        )
    for name in sorted(on_disk - names):
        findings.append(
            Finding(
                "extra-copy",
                name,
                f"`{PLUGIN_SKILLS_REL / name}` exists but `{name}` is not one of the "
                "16 manifest skills — stale copy, run `skill_pack_sync.py sync`",
            )
        )

    for name in sorted(names & on_disk):
        src = canonical_root / name
        dst = plugin_skills / name
        if not src.is_dir():
            findings.append(
                Finding(
                    "canonical-missing",
                    name,
                    f"canonical `{CANONICAL_SKILLS_REL / name}` missing while a plugin copy exists",
                )
            )
            continue
        src_files = _skill_files(src)
        dst_files = _skill_files(dst)
        for rel in sorted(set(src_files) - set(dst_files)):
            findings.append(
                Finding(
                    "missing-copy",
                    f"{name}/{rel}",
                    f"canonical file `{CANONICAL_SKILLS_REL / name / rel}` has no plugin copy",
                )
            )
        for rel in sorted(set(dst_files) - set(src_files)):
            findings.append(
                Finding(
                    "extra-copy",
                    f"{name}/{rel}",
                    f"plugin file `{PLUGIN_SKILLS_REL / name / rel}` has no canonical source",
                )
            )
        for rel in sorted(set(src_files) & set(dst_files)):
            if not filecmp.cmp(src / rel, dst / rel, shallow=False):
                findings.append(
                    Finding(
                        "content-mismatch",
                        f"{name}/{rel}",
                        f"`{PLUGIN_SKILLS_REL / name / rel}` is not byte-identical to "
                        f"`{CANONICAL_SKILLS_REL / name / rel}` — run `skill_pack_sync.py sync`",
                    )
                )


def _check_plugin_json(repo_root: Path, versions: dict[str, str], findings: list[Finding]) -> None:
    path = repo_root / PLUGIN_JSON_REL
    data, load_findings = _load_json(path, "plugin.json")
    if load_findings:
        findings.extend(load_findings)
        return
    if not isinstance(data, dict):
        findings.append(Finding("bad-plugin-json", str(PLUGIN_JSON_REL), "root must be an object"))
        return
    missing = sorted(PLUGIN_JSON_REQUIRED_KEYS - set(data))
    if missing:
        findings.append(
            Finding("bad-plugin-json", str(PLUGIN_JSON_REL), f"missing required key(s): {missing}")
        )
    if data.get("name") != PLUGIN_NAME:
        findings.append(
            Finding(
                "bad-plugin-json",
                str(PLUGIN_JSON_REL),
                f"name must be {PLUGIN_NAME!r}, got {data.get('name')!r}",
            )
        )
    author = data.get("author")
    if not (isinstance(author, dict) and isinstance(author.get("name"), str)):
        findings.append(
            Finding("bad-plugin-json", str(PLUGIN_JSON_REL), "author.name must be a string")
        )

    skill_versions = sorted(set(versions.values()))
    if len(skill_versions) != 1:
        findings.append(
            Finding(
                "version-drift",
                str(PLUGIN_JSON_REL),
                f"manifest skills carry {len(skill_versions)} distinct versions "
                f"{skill_versions} — plugin version is ambiguous",
            )
        )
    elif data.get("version") != skill_versions[0]:
        findings.append(
            Finding(
                "version-drift",
                str(PLUGIN_JSON_REL),
                f"plugin version {data.get('version')!r} != manifest skill version "
                f"{skill_versions[0]!r}",
            )
        )


def _check_marketplace_json(repo_root: Path, findings: list[Finding]) -> None:
    path = repo_root / MARKETPLACE_JSON_REL
    data, load_findings = _load_json(path, "marketplace.json")
    if load_findings:
        findings.extend(load_findings)
        return
    where = str(MARKETPLACE_JSON_REL)
    if not isinstance(data, dict):
        findings.append(Finding("bad-marketplace-json", where, "root must be an object"))
        return
    if data.get("name") != MARKETPLACE_NAME:
        findings.append(
            Finding(
                "bad-marketplace-json",
                where,
                f"name must be {MARKETPLACE_NAME!r}, got {data.get('name')!r}",
            )
        )
    owner = data.get("owner")
    if not (isinstance(owner, dict) and isinstance(owner.get("name"), str)):
        findings.append(Finding("bad-marketplace-json", where, "owner.name must be a string"))
    metadata = data.get("metadata")
    plugin_root = metadata.get("pluginRoot") if isinstance(metadata, dict) else None
    if plugin_root != PLUGIN_ROOT_REL:
        findings.append(
            Finding(
                "bad-marketplace-json",
                where,
                f"metadata.pluginRoot must be {PLUGIN_ROOT_REL!r}, got {plugin_root!r}",
            )
        )
    plugins = data.get("plugins")
    if not (isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], dict)):
        findings.append(
            Finding(
                "bad-marketplace-json",
                where,
                "plugins must list exactly the one saena-skill-pack entry",
            )
        )
        return
    entry = plugins[0]
    if entry.get("name") != PLUGIN_NAME:
        findings.append(
            Finding(
                "bad-marketplace-json",
                where,
                f"plugins[0].name must be {PLUGIN_NAME!r}, got {entry.get('name')!r}",
            )
        )
    if entry.get("source") != PLUGIN_SOURCE_REL:
        findings.append(
            Finding(
                "bad-marketplace-json",
                where,
                f"plugins[0].source must be {PLUGIN_SOURCE_REL!r} (relative under "
                f"pluginRoot {PLUGIN_ROOT_REL!r}), got {entry.get('source')!r}",
            )
        )


def run_check(repo_root: Path) -> tuple[list[Finding], int]:
    """Full drift gate. Returns (findings, exit_code)."""
    versions, findings = _load_valid_manifest(repo_root)
    if findings:
        return findings, EXIT_MANIFEST_INVALID
    _check_tree_drift(repo_root, set(versions), findings)
    _check_plugin_json(repo_root, versions, findings)
    _check_marketplace_json(repo_root, findings)
    return findings, EXIT_OK if not findings else EXIT_DRIFT


# --------------------------------------------------------------------------- #
# Reporting + CLI
# --------------------------------------------------------------------------- #
def _report(
    command: str,
    repo_root: Path,
    findings: list[Finding],
    actions: list[str],
    exit_code: int,
    as_json: bool,
) -> str:
    if as_json:
        return json.dumps(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "command": command,
                "repo_root": str(repo_root),
                "ok": not findings,
                "exit_code": exit_code,
                "actions": actions,
                "errors": [finding.as_dict() for finding in findings],
            },
            indent=2,
            sort_keys=True,
        )
    lines = [f"skill-pack {command} — {repo_root}"]
    for action in actions:
        lines.append(f"  [SYNC] {action}")
    for finding in findings:
        lines.append(f"  [FAIL] {finding.code} ({finding.where}): {finding.message}")
    lines.append("")
    lines.append(
        "RESULT: PASS"
        if not findings
        else f"RESULT: FAIL — {len(findings)} problem(s); fail-closed"
    )
    return "\n".join(lines)


def _cmd_sync(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    findings, actions, exit_code = run_sync(repo_root)
    print(_report("sync", repo_root, findings, actions, exit_code, args.as_json))
    return exit_code


def _cmd_check(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    findings, exit_code = run_check(repo_root)
    print(_report("check", repo_root, findings, [], exit_code, args.as_json))
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill_pack_sync",
        description="Sync + fail-closed drift gate for plugins/saena-skill-pack (w6-09)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser(
        "sync", help="regenerate plugins/saena-skill-pack/skills from .claude/skills"
    )
    p_check = sub.add_parser(
        "check", help="drift gate: byte-equality both directions + manifest consistency"
    )
    for sp in (p_sync, p_check):
        sp.add_argument(
            "--repo-root",
            default=str(_default_repo_root()),
            help="repository root (default: derived from this file's location)",
        )
        sp.add_argument("--json", dest="as_json", action="store_true")
    p_sync.set_defaults(func=_cmd_sync)
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on usage errors; remap so usage stays distinct
        # from EXIT_MANIFEST_INVALID (2).
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
