#!/usr/bin/env python3
"""Fail-closed validator for the SAENA FORGE skill-manifest SSOT (Wave 6 w6-01).

Two subcommands (both exit 0 only when fully green):

``validate-manifest --manifest <path> [--schema <path>] [--json]``
    Structural + semantic validation of ``.claude/skills/manifest.json``
    WITHOUT requiring any SKILL.md on disk: closed key sets, closed engine
    enum (exactly ``["chatgpt-search"]`` — lookalikes such as
    ``chatgpt-search-beta`` are rejected, fa-06/fa-07 precedent), the 14
    defined agents, semver versions, canonical paths, dependency
    cycles/phase ordering, and exact equality with the mandatory 16-skill
    set. ``--schema`` additionally cross-checks that the JSON Schema file
    has not drifted from this module's closed key/enum sets (full
    instance validation against the schema is the ``check-jsonschema``
    CI gate's job — this module stays stdlib+pyyaml only).

``validate-skills --manifest <path> --skills-root <dir> [--json]``
    Cross-checks disk vs manifest in BOTH directions (manifest entry with
    no SKILL.md on disk fails; a ``<dir>/SKILL.md`` on disk that is not in
    the manifest fails), then applies the plan §3.2 SKILL.md quality
    contract per file: exact ``name``+``description`` frontmatter, the 16
    required H2 sections with non-trivial content, a numbered Workflow,
    engine-scope statement, no secret-shaped strings, and no real-looking
    customer domains in Examples.

Exit codes: 0 green; 1 manifest invalid; 2 skills invalid; 3 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXIT_OK = 0
EXIT_MANIFEST_INVALID = 1
EXIT_SKILLS_INVALID = 2
EXIT_USAGE = 3

SCHEMA_VERSION = "saena.skill-manifest/v1"
REPORT_SCHEMA_VERSION = "saena.skill-manifest-report/v1"
BUNDLE_NAME = "saena-forge-core"
#: Closed engine enum — fa-06 allows exactly this id, fa-07 denies lookalikes.
ENGINE_SCOPE: tuple[str, ...] = ("chatgpt-search",)
PHASE_ORDER: tuple[str, ...] = ("bootstrap", "plan", "execute", "verify")

#: The 14 defined agents (spec report A10) — never invent a 15th.
AGENTS: frozenset[str] = frozenset(
    {
        "discovery-agent",
        "demand-agent",
        "evidence-agent",
        "citation-competition-agent",
        "technical-risk-agent",
        "planner-agent",
        "technical-patch-agent",
        "content-compiler-agent",
        "schema-agent",
        "integrator-agent",
        "test-agent",
        "fidelity-critic",
        "security-critic",
        "independent-release-reviewer",
    }
)

#: The mandatory 16-skill bundle (wave6-plan §1) — name -> required phase.
#: The manifest must contain EXACTLY this set (missing or extra = drift).
MANDATORY_SKILLS: dict[str, str] = {
    "saena-intake": "bootstrap",
    "saena-security-redteam": "bootstrap",
    "saena-site-discovery": "plan",
    "saena-demand-graph": "plan",
    "saena-b2b-saas-entity": "plan",
    "saena-claim-evidence": "plan",
    "saena-chatgpt-search": "plan",
    "saena-technical-aeo": "execute",
    "saena-answer-capsule": "execute",
    "saena-schema-fidelity": "execute",
    "ponytail": "execute",
    "saena-content-fidelity": "verify",
    "saena-accessibility-visual": "verify",
    "saena-patch-review": "verify",
    "saena-rollback": "verify",
    "ponytail-review": "verify",
}

#: ADR-0007 engine-neutrality branch point — the only skill allowed (and
#: required) to carry ``adr0007_engine_swap_point: true``.
ENGINE_SWAP_SKILL = "saena-chatgpt-search"

TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"schema_version", "engine_scope", "bundle_name", "phase_order", "skills"}
)
SKILL_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "version",
        "phase",
        "path",
        "engines",
        "required_inputs",
        "produces",
        "agents",
        "depends_on",
        "safety_gates",
        "verification_gates",
        "failure_behavior",
    }
)
SKILL_KEYS: frozenset[str] = SKILL_REQUIRED_KEYS | {"adr0007_engine_swap_point"}
FRONTMATTER_KEYS: frozenset[str] = frozenset({"name", "description"})

#: Required H2 sections (wave6-plan §3.2). A heading satisfies a required
#: section when the heading, casefolded, starts with the required title
#: casefolded — so "## When to use (trigger)" satisfies "When to use".
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Purpose",
    "When to use",
    "When NOT to use",
    "Required inputs",
    "Authoritative references",
    "Workflow",
    "Agent delegation",
    "Hooks & gates",
    "Artifacts & outputs",
    "Evidence & provenance",
    "Fail-closed behavior",
    "Untrusted content & prompt injection",
    "Secrets & PII",
    "Verification",
    "Non-goals",
    "Examples",
)
MIN_SECTION_LINES = 2
MIN_BODY_LINES = 80
MIN_WORKFLOW_STEPS = 5
MAX_DESCRIPTION_LENGTH = 1024
#: Scope-sensitive engine statement every SKILL.md body must carry.
ENGINE_STATEMENT = "ChatGPT Search"

_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_WORKFLOW_STEP_RE = re.compile(r"^\s{0,3}\d+[.)]\s+\S")

#: Secret-shaped patterns — a small LOCAL copy by convention (the repo keeps
#: deliberate per-package copies; see w6-repo-report "Secret guards"). Includes
#: the hyphen-infix ``sk-live-…`` variant (c5-06 audit) and JWT-like blobs.
_SECRET_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\b[sr]k-(?:live|test)-[A-Za-z0-9]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
)

#: Examples-section domain policy: only reserved/example hosts are allowed
#: (plan §3.2 — "fixture paths & example.com-style domains only").
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}\b", re.IGNORECASE)
_ALLOWED_FINAL_LABELS: frozenset[str] = frozenset({"example", "test", "invalid", "localhost"})
_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"example.com", "example.org", "example.net", "schema.org"}
)
#: Real-registry TLDs that make a token "real-looking"; anything else
#: (``robots.txt``, ``next.config.js``, …) is treated as a filename/path.
_REAL_TLDS: frozenset[str] = frozenset(
    {"com", "org", "net", "io", "ai", "co", "dev", "app", "cloud", "biz", "info", "kr", "us"}
)


@dataclass(frozen=True)
class Issue:
    """One validation failure. `where` is a skill name, file, or '-'."""

    code: str
    where: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "where": self.where, "message": self.message}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _load_json(path: Path, label: str) -> tuple[Any, list[Issue]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Issue("unreadable", "-", f"{label} `{path}` unreadable: {exc}")]
    try:
        return json.loads(raw), []
    except json.JSONDecodeError as exc:
        return None, [Issue("malformed-json", "-", f"{label} `{path}` is not valid JSON: {exc}")]


# --------------------------------------------------------------------------- #
# Manifest validation (no disk skills required)
# --------------------------------------------------------------------------- #
def _check_const(data: dict[str, Any], key: str, expected: Any, issues: list[Issue]) -> None:
    actual = data.get(key)
    if actual != expected:
        code = f"bad-{key.replace('_', '-')}"
        issues.append(Issue(code, "-", f"{key} must be {expected!r}, got {actual!r}"))


def _validate_skill_entry(
    entry: dict[str, Any], name: str, phase_rank: dict[str, int], issues: list[Issue]
) -> None:
    unknown = sorted(set(entry) - SKILL_KEYS)
    if unknown:
        issues.append(Issue("unknown-skill-key", name, f"unknown skill key(s): {unknown}"))
    missing = sorted(SKILL_REQUIRED_KEYS - set(entry))
    if missing:
        issues.append(Issue("missing-skill-key", name, f"missing required key(s): {missing}"))

    version = entry.get("version")
    if not (isinstance(version, str) and _SEMVER_RE.match(version)):
        issues.append(
            Issue("bad-version", name, f"version {version!r} is not strict semver (X.Y.Z)")
        )

    phase = entry.get("phase")
    if phase not in phase_rank:
        issues.append(
            Issue("bad-phase", name, f"phase {phase!r} not in phase_order {list(PHASE_ORDER)}")
        )

    expected_path = f".claude/skills/{name}/SKILL.md"
    if entry.get("path") != expected_path:
        issues.append(
            Issue("bad-path", name, f"path must be `{expected_path}`, got {entry.get('path')!r}")
        )

    engines = entry.get("engines")
    if not (isinstance(engines, list) and engines):
        issues.append(Issue("bad-engines", name, "engines must be a non-empty list"))
    else:
        for engine in engines:
            if engine not in ENGINE_SCOPE:
                issues.append(
                    Issue(
                        "unknown-engine",
                        name,
                        f"engine {engine!r} not in the closed engine_scope {list(ENGINE_SCOPE)}",
                    )
                )
        if len(set(engines)) != len(engines):
            issues.append(Issue("bad-engines", name, "engines contains duplicates"))

    agents = entry.get("agents")
    if not isinstance(agents, list):
        issues.append(Issue("bad-agents", name, "agents must be a list"))
    else:
        for agent in agents:
            if agent not in AGENTS:
                issues.append(
                    Issue(
                        "unknown-agent",
                        name,
                        f"agent {agent!r} is not one of the 14 defined agents",
                    )
                )

    for key in ("required_inputs", "produces", "depends_on", "safety_gates", "verification_gates"):
        value = entry.get(key)
        if not isinstance(value, list) or any(
            not (isinstance(item, str) and item.strip()) for item in value
        ):
            code = f"bad-{key.replace('_', '-')}"
            issues.append(Issue(code, name, f"{key} must be a list of non-empty strings"))

    if entry.get("failure_behavior") != "fail-closed":
        issues.append(
            Issue(
                "bad-failure-behavior",
                name,
                f"failure_behavior must be 'fail-closed', got {entry.get('failure_behavior')!r}",
            )
        )

    flag = entry.get("adr0007_engine_swap_point")
    if name == ENGINE_SWAP_SKILL:
        if flag is not True:
            issues.append(
                Issue(
                    "missing-engine-swap-flag",
                    name,
                    "saena-chatgpt-search must carry adr0007_engine_swap_point: true "
                    "(ADR-0007 engine-neutrality branch point)",
                )
            )
    elif "adr0007_engine_swap_point" in entry:
        issues.append(
            Issue(
                "misplaced-engine-swap-flag",
                name,
                "adr0007_engine_swap_point is only valid on saena-chatgpt-search",
            )
        )


def _validate_dependencies(
    skills: dict[str, dict[str, Any]], phase_rank: dict[str, int], issues: list[Issue]
) -> None:
    for name, entry in skills.items():
        deps = entry.get("depends_on")
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if dep not in skills:
                issues.append(
                    Issue("unknown-dependency", name, f"depends_on {dep!r} is not in the manifest")
                )
                continue
            my_rank = phase_rank.get(str(entry.get("phase")), -1)
            dep_rank = phase_rank.get(str(skills[dep].get("phase")), -1)
            if my_rank >= 0 and dep_rank >= 0 and dep_rank > my_rank:
                issues.append(
                    Issue(
                        "backward-phase-dependency",
                        name,
                        f"depends_on {dep!r} points to a LATER phase "
                        f"({skills[dep].get('phase')} after {entry.get('phase')})",
                    )
                )

    # Cycle detection (iterative DFS, three colors).
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(skills, WHITE)
    for root in sorted(skills):
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = GRAY
        path: list[str] = [root]
        while stack:
            node, idx = stack[-1]
            deps_raw = skills[node].get("depends_on")
            deps = (
                [d for d in deps_raw if isinstance(d, str) and d in skills]
                if isinstance(deps_raw, list)
                else []
            )
            if idx < len(deps):
                stack[-1] = (node, idx + 1)
                child = deps[idx]
                if color[child] == GRAY:
                    cycle = path[path.index(child) :] + [child]
                    issues.append(
                        Issue("dependency-cycle", child, f"dependency cycle: {' -> '.join(cycle)}")
                    )
                elif color[child] == WHITE:
                    color[child] = GRAY
                    stack.append((child, 0))
                    path.append(child)
            else:
                color[node] = BLACK
                stack.pop()
                path.pop()


def validate_manifest_data(data: Any) -> list[Issue]:
    """All structural+semantic manifest checks; empty list == valid."""
    if not isinstance(data, dict):
        return [Issue("bad-manifest", "-", "manifest root must be a JSON object")]
    issues: list[Issue] = []

    unknown = sorted(set(data) - TOP_LEVEL_KEYS)
    if unknown:
        issues.append(Issue("unknown-top-level-key", "-", f"unknown top-level key(s): {unknown}"))
    missing = sorted(TOP_LEVEL_KEYS - set(data))
    if missing:
        issues.append(Issue("missing-top-level-key", "-", f"missing top-level key(s): {missing}"))

    _check_const(data, "schema_version", SCHEMA_VERSION, issues)
    _check_const(data, "engine_scope", list(ENGINE_SCOPE), issues)
    _check_const(data, "bundle_name", BUNDLE_NAME, issues)
    _check_const(data, "phase_order", list(PHASE_ORDER), issues)

    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list):
        issues.append(Issue("bad-skills", "-", "skills must be a list"))
        return issues

    phase_rank = {phase: rank for rank, phase in enumerate(PHASE_ORDER)}
    skills: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw_skills):
        if not isinstance(entry, dict):
            issues.append(Issue("bad-skill-entry", f"skills[{i}]", "skill entry must be an object"))
            continue
        name = entry.get("name")
        if not (isinstance(name, str) and _NAME_RE.match(name)):
            issues.append(
                Issue("bad-name", f"skills[{i}]", f"name {name!r} is not a kebab-case identifier")
            )
            continue
        if name in skills:
            issues.append(Issue("duplicate-name", name, f"duplicate skill name {name!r}"))
            continue
        skills[name] = entry
        _validate_skill_entry(entry, name, phase_rank, issues)

    # Mandatory bundle: EXACT set equality — missing OR unregistered-extra fails.
    missing_mandatory = sorted(set(MANDATORY_SKILLS) - set(skills))
    if missing_mandatory:
        issues.append(
            Issue(
                "missing-mandatory-skill",
                "-",
                f"missing mandatory skill(s): {missing_mandatory}",
            )
        )
    extra = sorted(set(skills) - set(MANDATORY_SKILLS))
    if extra:
        issues.append(
            Issue(
                "unregistered-skill-drift",
                "-",
                f"skill(s) not in the mandatory 16-skill bundle: {extra}",
            )
        )
    for name, entry in skills.items():
        required_phase = MANDATORY_SKILLS.get(name)
        if required_phase is not None and entry.get("phase") != required_phase:
            issues.append(
                Issue(
                    "wrong-mandatory-phase",
                    name,
                    f"phase {entry.get('phase')!r} != mandated {required_phase!r}",
                )
            )

    _validate_dependencies(skills, phase_rank, issues)
    return issues


def _validate_schema_sync(schema_path: Path) -> list[Issue]:
    """Anti-drift cross-check: the JSON Schema must agree with this module's
    closed key/enum sets. (Instance validation against the schema is done by
    the `check-jsonschema` CLI in CI — not re-implemented here.)"""
    schema, issues = _load_json(schema_path, "schema")
    if issues:
        return issues
    if not isinstance(schema, dict):
        return [Issue("bad-schema", "-", "schema root must be a JSON object")]

    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        issues.append(Issue("bad-schema", "-", "schema $schema must be draft 2020-12"))

    props = schema.get("properties")
    if not isinstance(props, dict) or set(props) != TOP_LEVEL_KEYS:
        issues.append(
            Issue("schema-drift", "-", "schema top-level properties != validator TOP_LEVEL_KEYS")
        )
        return issues
    if props.get("schema_version", {}).get("const") != SCHEMA_VERSION:
        issues.append(Issue("schema-drift", "-", "schema schema_version const drifted"))
    if props.get("engine_scope", {}).get("const") != list(ENGINE_SCOPE):
        issues.append(Issue("schema-drift", "-", "schema engine_scope const drifted"))
    if props.get("bundle_name", {}).get("const") != BUNDLE_NAME:
        issues.append(Issue("schema-drift", "-", "schema bundle_name const drifted"))
    if props.get("phase_order", {}).get("const") != list(PHASE_ORDER):
        issues.append(Issue("schema-drift", "-", "schema phase_order const drifted"))

    skill_def = schema.get("$defs", {}).get("skill", {})
    skill_props = skill_def.get("properties")
    if not isinstance(skill_props, dict) or set(skill_props) != SKILL_KEYS:
        issues.append(Issue("schema-drift", "-", "schema skill properties != validator SKILL_KEYS"))
        return issues
    if set(skill_def.get("required", [])) != SKILL_REQUIRED_KEYS:
        issues.append(Issue("schema-drift", "-", "schema skill required != SKILL_REQUIRED_KEYS"))
    agents_enum = skill_props.get("agents", {}).get("items", {}).get("enum")
    if not isinstance(agents_enum, list) or set(agents_enum) != AGENTS:
        issues.append(Issue("schema-drift", "-", "schema agents enum != the 14 defined agents"))
    engines_enum = skill_props.get("engines", {}).get("items", {}).get("enum")
    if engines_enum != list(ENGINE_SCOPE):
        issues.append(Issue("schema-drift", "-", "schema engines enum != closed ENGINE_SCOPE"))
    phase_enum = skill_props.get("phase", {}).get("enum")
    if phase_enum != list(PHASE_ORDER):
        issues.append(Issue("schema-drift", "-", "schema phase enum != PHASE_ORDER"))
    if skill_props.get("failure_behavior", {}).get("const") != "fail-closed":
        issues.append(Issue("schema-drift", "-", "schema failure_behavior const drifted"))
    return issues


# --------------------------------------------------------------------------- #
# SKILL.md quality validation
# --------------------------------------------------------------------------- #
def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Return (frontmatter, body, error). Fail-closed on any malformation."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "", "file does not start with a `---` YAML frontmatter fence"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            try:
                fm = yaml.safe_load(fm_text)
            except yaml.YAMLError as exc:
                return None, body, f"frontmatter is not valid YAML: {exc}"
            if not isinstance(fm, dict):
                return None, body, "frontmatter is not a YAML mapping"
            return fm, body, None
    return None, "", "frontmatter fence `---` is never closed"


def _sections(body: str) -> dict[str, list[str]]:
    """Map H2 heading text -> content lines (until the next H2)."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        m = _H2_RE.match(line)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
        elif current is not None:
            out[current].append(line)
    return out


def _find_section(sections: dict[str, list[str]], required: str) -> list[str] | None:
    """A heading satisfies `required` when it starts with it (casefolded)."""
    want = required.casefold()
    merged: list[str] = []
    found = False
    for heading, content in sections.items():
        if heading.casefold().startswith(want):
            found = True
            merged.extend(content)
    return merged if found else None


def _check_examples_domains(examples_text: str, where: str, issues: list[Issue]) -> None:
    for match in _DOMAIN_RE.finditer(examples_text):
        host = match.group(0).lower().rstrip(".")
        labels = host.split(".")
        if labels[-1] in _ALLOWED_FINAL_LABELS:
            continue
        if labels[-1] not in _REAL_TLDS:
            continue  # filename/path-shaped token (robots.txt, next.config.js, …)
        if host in _ALLOWED_HOSTS or any(host.endswith("." + a) for a in _ALLOWED_HOSTS):
            continue
        issues.append(
            Issue(
                "real-domain-in-examples",
                where,
                f"real-looking domain `{host}` in Examples — use example.com/.example/"
                ".test/.invalid or fixture paths only",
            )
        )


def _validate_skill_file(path: Path, name: str, issues: list[Issue]) -> None:
    where = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(Issue("unreadable", where, f"SKILL.md unreadable: {exc}"))
        return

    for pattern in _SECRET_SHAPED_PATTERNS:
        if pattern.search(text):
            issues.append(
                Issue(
                    "secret-shaped-string",
                    where,
                    f"secret-shaped string matching `{pattern.pattern}` present",
                )
            )

    fm, body, err = _split_frontmatter(text)
    if err is not None or fm is None:
        issues.append(Issue("malformed-frontmatter", where, err or "frontmatter missing"))
        return

    if set(fm) != FRONTMATTER_KEYS:
        issues.append(
            Issue(
                "bad-frontmatter-keys",
                where,
                f"frontmatter keys must be exactly {sorted(FRONTMATTER_KEYS)}, got {sorted(fm)}",
            )
        )
    fm_name = fm.get("name")
    if fm_name != name:
        issues.append(
            Issue(
                "frontmatter-name-mismatch",
                where,
                f"frontmatter name {fm_name!r} != directory/manifest name {name!r}",
            )
        )
    description = fm.get("description")
    if not (isinstance(description, str) and description.strip()):
        issues.append(Issue("bad-description", where, "description must be a non-empty string"))
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        issues.append(
            Issue(
                "description-too-long",
                where,
                f"description is {len(description)} chars (max {MAX_DESCRIPTION_LENGTH})",
            )
        )

    non_blank = [line for line in body.splitlines() if line.strip()]
    if len(non_blank) < MIN_BODY_LINES:
        issues.append(
            Issue(
                "body-too-short",
                where,
                f"body has {len(non_blank)} non-blank lines (min {MIN_BODY_LINES})",
            )
        )

    sections = _sections(body)
    for required in REQUIRED_SECTIONS:
        content = _find_section(sections, required)
        if content is None:
            issues.append(
                Issue("missing-section", where, f"required H2 section `{required}` missing")
            )
            continue
        if len([line for line in content if line.strip()]) < MIN_SECTION_LINES:
            issues.append(
                Issue(
                    "trivial-section",
                    where,
                    f"section `{required}` has fewer than {MIN_SECTION_LINES} non-blank lines",
                )
            )

    workflow = _find_section(sections, "Workflow") or []
    steps = [line for line in workflow if _WORKFLOW_STEP_RE.match(line)]
    if len(steps) < MIN_WORKFLOW_STEPS:
        issues.append(
            Issue(
                "workflow-too-few-steps",
                where,
                f"Workflow has {len(steps)} numbered steps (min {MIN_WORKFLOW_STEPS})",
            )
        )

    if ENGINE_STATEMENT not in body:
        issues.append(
            Issue(
                "missing-engine-scope-statement",
                where,
                f"body must state the engine scope (`{ENGINE_STATEMENT}` only)",
            )
        )

    examples = _find_section(sections, "Examples")
    if examples is not None:
        _check_examples_domains("\n".join(examples), where, issues)


def validate_skills_on_disk(manifest_names: set[str], skills_root: Path) -> list[Issue]:
    """Both-direction disk<->manifest cross-check + per-file quality checks."""
    issues: list[Issue] = []
    if not skills_root.is_dir():
        return [Issue("bad-skills-root", "-", f"skills root `{skills_root}` is not a directory")]

    on_disk = {entry.name for entry in skills_root.iterdir() if (entry / "SKILL.md").is_file()}
    for name in sorted(manifest_names - on_disk):
        issues.append(
            Issue(
                "skill-missing-on-disk",
                name,
                f"manifest skill `{name}` has no `{skills_root / name / 'SKILL.md'}`",
            )
        )
    for name in sorted(on_disk - manifest_names):
        issues.append(
            Issue(
                "skill-not-in-manifest",
                name,
                f"`{skills_root / name / 'SKILL.md'}` exists on disk but `{name}` "
                "is not registered in the manifest",
            )
        )
    for name in sorted(manifest_names & on_disk):
        _validate_skill_file(skills_root / name / "SKILL.md", name, issues)
    return issues


# --------------------------------------------------------------------------- #
# Reporting + CLI
# --------------------------------------------------------------------------- #
def _report(
    command: str,
    manifest: Path,
    skills_root: Path | None,
    issues: list[Issue],
    exit_code: int,
    checked_skills: int,
    as_json: bool,
) -> str:
    if as_json:
        return json.dumps(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "command": command,
                "manifest": str(manifest),
                "skills_root": str(skills_root) if skills_root is not None else None,
                "ok": not issues,
                "exit_code": exit_code,
                "checked_skills": checked_skills,
                "errors": [issue.as_dict() for issue in issues],
            },
            indent=2,
            sort_keys=True,
        )
    lines = [f"skill-manifest {command} — {manifest}"]
    if skills_root is not None:
        lines.append(f"skills root: {skills_root} ({checked_skills} skill file(s) checked)")
    for issue in issues:
        lines.append(f"  [FAIL] {issue.code} ({issue.where}): {issue.message}")
    lines.append("")
    lines.append(
        "RESULT: PASS" if not issues else f"RESULT: FAIL — {len(issues)} problem(s); fail-closed"
    )
    return "\n".join(lines)


def _cmd_validate_manifest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    data, issues = _load_json(manifest_path, "manifest")
    if not issues:
        issues = validate_manifest_data(data)
        if args.schema is not None:
            issues.extend(_validate_schema_sync(Path(args.schema)))
    exit_code = EXIT_OK if not issues else EXIT_MANIFEST_INVALID
    print(_report("validate-manifest", manifest_path, None, issues, exit_code, 0, args.as_json))
    return exit_code


def _cmd_validate_skills(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    skills_root = Path(args.skills_root)
    data, manifest_issues = _load_json(manifest_path, "manifest")
    if not manifest_issues:
        manifest_issues = validate_manifest_data(data)
    if manifest_issues:
        # A broken manifest cannot anchor a disk cross-check — manifest error.
        print(
            _report(
                "validate-skills",
                manifest_path,
                skills_root,
                manifest_issues,
                EXIT_MANIFEST_INVALID,
                0,
                args.as_json,
            )
        )
        return EXIT_MANIFEST_INVALID

    assert isinstance(data, dict)
    manifest_names = {
        entry["name"]
        for entry in data["skills"]
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    issues = validate_skills_on_disk(manifest_names, skills_root)
    checked = len([n for n in manifest_names if (skills_root / n / "SKILL.md").is_file()])
    exit_code = EXIT_OK if not issues else EXIT_SKILLS_INVALID
    print(
        _report(
            "validate-skills", manifest_path, skills_root, issues, exit_code, checked, args.as_json
        )
    )
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill_manifest",
        description="Fail-closed validator for the SAENA FORGE skill-manifest SSOT",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser(
        "validate-manifest",
        help="structural+semantic manifest validation (no SKILL.md files required)",
    )
    p_manifest.add_argument("--manifest", required=True, help="path to manifest.json")
    p_manifest.add_argument(
        "--schema",
        default=None,
        help="optional manifest.schema.json to cross-check for enum/key drift",
    )
    p_manifest.add_argument("--json", dest="as_json", action="store_true")
    p_manifest.set_defaults(func=_cmd_validate_manifest)

    p_skills = sub.add_parser(
        "validate-skills",
        help="both-direction disk<->manifest cross-check + SKILL.md quality contract",
    )
    p_skills.add_argument("--manifest", required=True, help="path to manifest.json")
    p_skills.add_argument(
        "--skills-root", required=True, help="directory containing <skill>/SKILL.md dirs"
    )
    p_skills.add_argument("--json", dest="as_json", action="store_true")
    p_skills.set_defaults(func=_cmd_validate_skills)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on usage errors and 0 on --help; remap so the
        # usage exit code stays distinct from EXIT_SKILLS_INVALID (2).
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
