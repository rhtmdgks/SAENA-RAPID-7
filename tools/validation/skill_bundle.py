#!/usr/bin/env python3
"""Fail-closed skill-BUNDLE enforcement gate (Wave 6 w6-08, plan D-5).

Called by saena-pilot at session start and by the ``skill-bundle-bypass``
CI gate (w6-15). Two subcommands:

``enforce [--manifest PATH] [--skills-root DIR] [--declared FILE|-] [--json]``
    THE gate. Delegates full manifest + skills validation to the w6-01 SSOT
    validator (``skill_manifest.py``, loaded by file path — never re-implemented
    here), then enforces the canonical bundle: ALL 16 manifest skills, all four
    ``phase_order`` phases non-empty, no unknown/duplicate/wrong-phase entry.
    ``--declared`` (a JSON list of skill names, or ``{"skills": [...]}``, ``-``
    for stdin) must equal the canonical set EXACTLY in both directions —
    subset fails listing the missing names, superset fails listing the unknown
    names. On green it emits the bundle fingerprint that pilot evidence binds:
    sha256 over the raw manifest bytes followed by ``<name>\\0<sha256 of that
    skill's SKILL.md bytes>\\n`` for every skill in sorted-name order.

``fingerprint [--manifest PATH] [--skills-root DIR]``
    Prints the fingerprint only — but still runs the FULL enforcement first;
    an invalid tree exits nonzero and prints no fingerprint.

There is deliberately NO bypass path: no environment variable is ever
consulted for behavior (``SAENA_SKIP_BUNDLE``-style variables are detected
and explicitly reported as ignored on stderr), no flag skips any check, and
no partial mode exists. The library entry point :func:`enforce_bundle` runs
the full validation itself, so a direct function call cannot skip it either.

Exit codes (forgectl-style, distinct per failure class):
0 green; 1 manifest invalid; 2 skills invalid; 3 usage error; 4 bundle
violation (canonical-set or declared-set mismatch).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

EXIT_OK = 0
EXIT_MANIFEST_INVALID = 1
EXIT_SKILLS_INVALID = 2
EXIT_USAGE = 3
EXIT_BUNDLE_VIOLATION = 4

REPORT_SCHEMA_VERSION = "saena.skill-bundle-report/v1"

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]
DEFAULT_MANIFEST = _REPO_ROOT / ".claude" / "skills" / "manifest.json"
DEFAULT_SKILLS_ROOT = _REPO_ROOT / ".claude" / "skills"

#: Env-var name fragments that look like bypass attempts. They are NEVER
#: consulted for behavior — main() only reports them as ignored (stderr) so
#: an operator setting SAENA_SKIP_BUNDLE=1 gets told there is no bypass path.
_BYPASS_ENV_TOKENS: tuple[str, ...] = (
    "SKIP_BUNDLE",
    "SKILL_BUNDLE",
    "BUNDLE_BYPASS",
    "BUNDLE_SKIP",
    "ALLOW_PARTIAL",
)


def _load_skill_manifest_module() -> ModuleType:
    """Load the w6-01 SSOT validator by file path (importlib), reusing an
    already-imported instance when tests put it on ``sys.path`` first."""
    existing = sys.modules.get("skill_manifest")
    if existing is not None:
        return existing
    path = _THIS_FILE.with_name("skill_manifest.py")
    spec = importlib.util.spec_from_file_location("skill_manifest", path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        raise ImportError(f"cannot load SSOT validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["skill_manifest"] = module
    spec.loader.exec_module(module)
    return module


_SM: ModuleType = _load_skill_manifest_module()


@dataclass(frozen=True)
class Finding:
    """One enforcement failure, tagged with the stage that produced it."""

    stage: str  # "manifest" | "skills" | "bundle"
    code: str
    where: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "code": self.code,
            "where": self.where,
            "message": self.message,
        }


@dataclass(frozen=True)
class BundleReport:
    """Result of one full enforcement run. ``fingerprint`` is set only when
    every stage is green (fail-closed: no fingerprint for an invalid tree)."""

    manifest: Path
    skills_root: Path
    declared_names: tuple[str, ...] | None
    findings: tuple[Finding, ...]
    checked_skills: int
    fingerprint: str | None

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def exit_code(self) -> int:
        """Worst stage wins, in gate order: manifest > skills > bundle."""
        stages = {finding.stage for finding in self.findings}
        if "manifest" in stages:
            return EXIT_MANIFEST_INVALID
        if "skills" in stages:
            return EXIT_SKILLS_INVALID
        if stages:
            return EXIT_BUNDLE_VIOLATION
        return EXIT_OK


def _issues_to_findings(stage: str, issues: list[Any]) -> list[Finding]:
    return [Finding(stage, issue.code, issue.where, issue.message) for issue in issues]


def compute_fingerprint(manifest_bytes: bytes, names: list[str], skills_root: Path) -> str:
    """sha256(manifest bytes + ``<name>\\0<SKILL.md sha256>\\n`` sorted by name).

    Any unreadable SKILL.md raises ``OSError`` — callers only invoke this
    after the skills stage has verified every file exists.
    """
    digest = hashlib.sha256()
    digest.update(manifest_bytes)
    for name in sorted(names):
        skill_bytes = (skills_root / name / "SKILL.md").read_bytes()
        skill_digest = hashlib.sha256(skill_bytes).hexdigest()
        digest.update(f"{name}\x00{skill_digest}\n".encode())
    return digest.hexdigest()


def _canonical_bundle_findings(raw_skills: list[Any]) -> list[Finding]:
    """Defense-in-depth canonical-bundle checks, independent of the delegated
    manifest validation (so even a direct :func:`enforce_bundle` call against
    a tampered in-memory path cannot dodge them)."""
    findings: list[Finding] = []
    mandatory: dict[str, str] = dict(_SM.MANDATORY_SKILLS)
    phase_order: tuple[str, ...] = tuple(_SM.PHASE_ORDER)

    names: list[str] = []
    phase_by_name: dict[str, Any] = {}
    for entry in raw_skills:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        if isinstance(raw_name, str):
            names.append(raw_name)
            phase_by_name[raw_name] = entry.get("phase")
    if not names:
        return [Finding("bundle", "empty-bundle", "-", "manifest declares no skills at all")]

    counts = Counter(names)
    for name, count in sorted(counts.items()):
        if count > 1:
            findings.append(
                Finding("bundle", "bundle-duplicate-skill", name, f"declared {count} times")
            )

    present = set(counts)
    for name in sorted(set(mandatory) - present):
        findings.append(
            Finding(
                "bundle",
                "bundle-missing-skill",
                name,
                f"mandatory skill `{name}` missing from the bundle",
            )
        )
    for name in sorted(present - set(mandatory)):
        findings.append(
            Finding(
                "bundle",
                "bundle-unknown-skill",
                name,
                f"`{name}` is not in the mandatory 16-skill bundle",
            )
        )

    for name in sorted(present & set(mandatory)):
        if phase_by_name.get(name) != mandatory[name]:
            findings.append(
                Finding(
                    "bundle",
                    "bundle-wrong-phase",
                    name,
                    f"phase {phase_by_name.get(name)!r} != mandated {mandatory[name]!r}",
                )
            )
    for phase in phase_order:
        if not any(phase_by_name.get(name) == phase for name in present):
            findings.append(
                Finding(
                    "bundle",
                    "empty-phase",
                    phase,
                    f"phase `{phase}` has no skill in the bundle",
                )
            )
    return findings


def _declared_findings(declared: list[str], canonical: set[str]) -> list[Finding]:
    """Declared bundle must equal the canonical set EXACTLY, both directions."""
    findings: list[Finding] = []
    counts = Counter(declared)
    for name, count in sorted(counts.items()):
        if count > 1:
            findings.append(
                Finding("bundle", "declared-duplicate", name, f"declared {count} times")
            )
    for name in sorted(canonical - set(counts)):
        findings.append(
            Finding(
                "bundle",
                "declared-missing-skill",
                name,
                f"declared bundle is missing canonical skill `{name}` (subset forbidden)",
            )
        )
    for name in sorted(set(counts) - canonical):
        findings.append(
            Finding(
                "bundle",
                "declared-unknown-skill",
                name,
                f"declared skill `{name}` is not in the canonical bundle (superset forbidden)",
            )
        )
    return findings


def parse_declared(raw: str, source: str) -> tuple[list[str] | None, list[Finding]]:
    """Parse a declared-bundle document: JSON list of names or {"skills": [...]}.

    Fail-closed: unknown keys, non-string entries, or any other shape is a
    bundle violation, never silently coerced.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [
            Finding(
                "bundle", "malformed-declared", source, f"declared file is not valid JSON: {exc}"
            )
        ]
    if isinstance(data, dict):
        unknown = sorted(set(data) - {"skills"})
        if unknown:
            return None, [
                Finding(
                    "bundle",
                    "unknown-declared-key",
                    source,
                    f"unknown key(s) in declared object: {unknown} (only 'skills' is allowed)",
                )
            ]
        data = data.get("skills")
    if not isinstance(data, list):
        return None, [
            Finding(
                "bundle",
                "malformed-declared",
                source,
                'declared bundle must be a JSON list of skill names or {"skills": [...]}',
            )
        ]
    bad = [item for item in data if not (isinstance(item, str) and item.strip())]
    if bad:
        return None, [
            Finding(
                "bundle",
                "malformed-declared",
                source,
                f"declared entries must be non-empty strings, got {bad!r}",
            )
        ]
    return list(data), []


def enforce_bundle(
    manifest: Path,
    skills_root: Path,
    declared: list[str] | None = None,
) -> BundleReport:
    """Run the FULL enforcement pipeline. This is the only library entry
    point; it always executes every stage that its predecessors allow —
    there is no argument that skips a check.

    Stage 1 (manifest): load + delegate to ``skill_manifest.validate_manifest_data``.
    Stage 2 (skills):   delegate to ``skill_manifest.validate_skills_on_disk``.
    Stage 3 (bundle):   independent canonical-bundle checks + declared-set
                        equality (both directions).
    Fingerprint is computed only when all stages are green.
    """
    declared_tuple = tuple(declared) if declared is not None else None

    try:
        manifest_bytes = manifest.read_bytes()
    except OSError as exc:
        return BundleReport(
            manifest,
            skills_root,
            declared_tuple,
            (Finding("manifest", "unreadable", "-", f"manifest `{manifest}` unreadable: {exc}"),),
            0,
            None,
        )
    try:
        data = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return BundleReport(
            manifest,
            skills_root,
            declared_tuple,
            (
                Finding(
                    "manifest",
                    "malformed-json",
                    "-",
                    f"manifest `{manifest}` is not valid JSON: {exc}",
                ),
            ),
            0,
            None,
        )

    manifest_issues = _SM.validate_manifest_data(data)
    if manifest_issues:
        return BundleReport(
            manifest,
            skills_root,
            declared_tuple,
            tuple(_issues_to_findings("manifest", manifest_issues)),
            0,
            None,
        )

    assert isinstance(data, dict)  # guaranteed by a green manifest stage
    raw_skills = data["skills"]
    names = [
        entry["name"]
        for entry in raw_skills
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]

    skills_issues = _SM.validate_skills_on_disk(set(names), skills_root)
    checked = len([n for n in names if (skills_root / n / "SKILL.md").is_file()])
    if skills_issues:
        return BundleReport(
            manifest,
            skills_root,
            declared_tuple,
            tuple(_issues_to_findings("skills", skills_issues)),
            checked,
            None,
        )

    bundle_findings = _canonical_bundle_findings(raw_skills)
    if declared is not None:
        bundle_findings.extend(_declared_findings(declared, set(names)))
    if bundle_findings:
        return BundleReport(
            manifest, skills_root, declared_tuple, tuple(bundle_findings), checked, None
        )

    fingerprint = compute_fingerprint(manifest_bytes, names, skills_root)
    return BundleReport(manifest, skills_root, declared_tuple, (), checked, fingerprint)


# --------------------------------------------------------------------------- #
# Reporting + CLI
# --------------------------------------------------------------------------- #
def _render_report(report: BundleReport, declared_source: str | None, as_json: bool) -> str:
    if as_json:
        return json.dumps(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "command": "enforce",
                "manifest": str(report.manifest),
                "skills_root": str(report.skills_root),
                "declared": declared_source,
                "ok": report.ok,
                "exit_code": report.exit_code,
                "checked_skills": report.checked_skills,
                "fingerprint": report.fingerprint,
                "errors": [finding.as_dict() for finding in report.findings],
            },
            indent=2,
            sort_keys=True,
        )
    lines = [f"skill-bundle enforce — {report.manifest}"]
    lines.append(f"skills root: {report.skills_root} ({report.checked_skills} skill file(s))")
    if declared_source is not None:
        lines.append(f"declared bundle: {declared_source}")
    for finding in report.findings:
        lines.append(
            f"  [FAIL:{finding.stage}] {finding.code} ({finding.where}): {finding.message}"
        )
    lines.append("")
    if report.ok:
        lines.append(f"bundle fingerprint: {report.fingerprint}")
        lines.append("RESULT: PASS")
    else:
        lines.append(
            f"RESULT: FAIL — {len(report.findings)} problem(s); fail-closed, no fingerprint"
        )
    return "\n".join(lines)


def _report_ignored_bypass_env() -> None:
    """Report (stderr) any bypass-shaped env var. NEVER changes behavior."""
    suspicious = sorted(
        name for name in os.environ if any(token in name.upper() for token in _BYPASS_ENV_TOKENS)
    )
    for name in suspicious:
        print(
            f"skill-bundle: env var {name} is IGNORED — no bypass path exists (fail-closed)",
            file=sys.stderr,
        )


def _read_declared(source: str) -> tuple[str | None, list[Finding]]:
    if source == "-":
        return sys.stdin.read(), []
    try:
        return Path(source).read_text(encoding="utf-8"), []
    except OSError as exc:
        return None, [
            Finding("bundle", "declared-unreadable", source, f"declared file unreadable: {exc}")
        ]


def _cmd_enforce(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest)
    skills_root = Path(args.skills_root)

    declared_names: list[str] | None = None
    declared_findings: list[Finding] = []
    if args.declared is not None:
        raw, declared_findings = _read_declared(args.declared)
        if raw is not None:
            declared_names, declared_findings = parse_declared(raw, args.declared)

    report = enforce_bundle(manifest, skills_root, declared_names)
    if declared_findings:
        # A declared file that cannot even be parsed is itself a bundle
        # violation — merge it in and drop any green fingerprint (fail-closed).
        report = BundleReport(
            report.manifest,
            report.skills_root,
            None,
            tuple(list(report.findings) + declared_findings),
            report.checked_skills,
            None,
        )
    print(_render_report(report, args.declared, args.as_json))
    return report.exit_code


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    report = enforce_bundle(Path(args.manifest), Path(args.skills_root), None)
    if not report.ok:
        # No fingerprint for an invalid tree; findings go to stderr only.
        print(_render_report(report, None, False), file=sys.stderr)
        return report.exit_code
    print(report.fingerprint)
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill_bundle",
        description="Fail-closed skill-bundle enforcement gate (no bypass path)",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_enforce = sub.add_parser(
        "enforce",
        help="full bundle enforcement: manifest + skills + canonical/declared set",
        allow_abbrev=False,
    )
    p_enforce.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p_enforce.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT))
    p_enforce.add_argument(
        "--declared",
        default=None,
        help="JSON list of skill names or {\"skills\": [...]}; '-' reads stdin",
    )
    p_enforce.add_argument("--json", dest="as_json", action="store_true")
    p_enforce.set_defaults(func=_cmd_enforce)

    p_fingerprint = sub.add_parser(
        "fingerprint",
        help="print the bundle fingerprint (validates first; invalid => nonzero)",
        allow_abbrev=False,
    )
    p_fingerprint.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p_fingerprint.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT))
    p_fingerprint.set_defaults(func=_cmd_fingerprint)
    return parser


def main(argv: list[str] | None = None) -> int:
    _report_ignored_bypass_env()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on usage errors and 0 on --help; remap so usage
        # stays distinct from EXIT_SKILLS_INVALID (2).
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
