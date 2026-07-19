"""Preflight/audit report assembly and rendering (JSON + human text).

Reports are written ONLY into the run store (`~/.saena/pilot-runs/<run-id>/`
or `$SAENA_PILOT_HOME`) — never into either repository. Every report passes
the secret-shape guard before serialization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from saena_pilot.models import BoundaryReport, BundleInfo
from saena_pilot.secretguard import guard_tree

REPORT_SCHEMA_VERSION = "saena.pilot-report/v1"

# The five W0 dev-repo safety hooks (ADR-0019). The pilot keeps them active by
# launching Claude from the RAPID-7 root; surfacing their health in preflight is
# a safety signal — a present `.claude/hooks/DISABLED` kill-switch means the
# safety layer is OFF for this run (VULN/finding surfaced, w6-13).
_EXPECTED_HOOK_SCRIPTS = (
    "deny-deploy-push.sh",
    "deny-unpinned-install.sh",
    "protect-paths.sh",
    "audit-log.sh",
    "secret-scan.sh",
)


def assess_hooks_health(rapid7_root: Path) -> dict[str, Any]:
    """Report the RAPID-7 hook safety layer's health (never mutates anything).

    `hooks_disabled` True means `.claude/hooks/DISABLED` exists — the safety
    hooks are bypassed for this session; the pilot surfaces it as a WARNING
    finding rather than failing, because disabling is an explicit,
    audit-logged human action, but an operator must see it.
    """
    hooks_dir = rapid7_root / ".claude" / "hooks"
    settings = rapid7_root / ".claude" / "settings.json"
    disabled = (hooks_dir / "DISABLED").exists()
    present = [name for name in _EXPECTED_HOOK_SCRIPTS if (hooks_dir / "scripts" / name).is_file()]
    missing = [name for name in _EXPECTED_HOOK_SCRIPTS if name not in present]
    warnings: list[str] = []
    if disabled:
        warnings.append(
            "hooks DISABLED: .claude/hooks/DISABLED is present — the W0 dev-repo "
            "safety hooks are bypassed for this session"
        )
    if not settings.is_file():
        warnings.append("hooks settings missing: .claude/settings.json not found")
    if missing:
        warnings.append(f"hook scripts missing: {', '.join(missing)}")
    return {
        "settings_present": settings.is_file(),
        "hooks_disabled": disabled,
        "hook_scripts_present": present,
        "hook_scripts_missing": missing,
        "warnings": warnings,
    }


def build_report(
    *,
    mode: str,
    run_id: str,
    rapid7_sha: str,
    boundary: BoundaryReport,
    domain: str,
    bundle: BundleInfo,
    contract: dict[str, Any],
    contract_questions: list[str],
    reconciliation: dict[str, Any],
    discovery: dict[str, Any],
    suggested_human_actions: list[str],
    docker: dict[str, Any] | None = None,
    hooks_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": mode,
        "run_id": run_id,
        "binding": {
            "rapid7_sha": rapid7_sha,
            "customer_sha": boundary.head_sha,
            "domain": domain,
        },
        "boundary": boundary.to_dict(),
        "bundle": bundle.to_dict(),
        "contract": contract,
        "contract_complete": not contract_questions,
        "contract_questions": contract_questions,
        "stricter_rules_reconciliation": reconciliation,
        "discovery": discovery,
        "docker": docker,
        "hooks_health": hooks_health,
        "suggested_human_actions": suggested_human_actions,
    }
    guard_tree(report, path="report")
    return report


def render_human(report: dict[str, Any]) -> str:
    lines = [
        f"saena-pilot {report['mode']} report — run {report['run_id']}",
        "",
        f"  RAPID-7 HEAD:  {report['binding']['rapid7_sha']}",
        f"  customer HEAD: {report['binding']['customer_sha']}",
        f"  domain:        {report['binding']['domain']}",
        "",
        "boundary findings:",
    ]
    findings = report["boundary"]["findings"]
    if not findings:
        lines.append("  (none)")
    else:
        for finding in findings:
            lines.append(f"  [{finding['severity']}] {finding['code']}: {finding['detail']}")
    lines.append("")
    bundle = report["bundle"]
    lines.append(
        f"skill bundle: {bundle['bundle_name']} — {len(bundle['skill_names'])} skill(s), "
        f"manifest sha256 {bundle['manifest_sha256'][:12]}… (validated)"
    )
    lines.append("")
    if report["contract_complete"]:
        lines.append("action contract: COMPLETE")
    else:
        lines.append("action contract: INCOMPLETE — open questions:")
        lines.extend(f"  {question}" for question in report["contract_questions"])
    lines.append("")
    lines.append("stricter-rules reconciliation:")
    rule_files = report["stricter_rules_reconciliation"]["rule_files"]
    if not rule_files:
        lines.append("  no customer CLAUDE.md/AGENTS.md files found")
    else:
        for entry in rule_files:
            lines.append(
                f"  {entry['path']} ({entry['size_bytes']} bytes, sha256 {entry['sha256'][:12]}…)"
            )
    lines.append(f"  policy: {report['stricter_rules_reconciliation']['policy']}")
    lines.append("")
    discovery = report["discovery"]
    lines.append(
        f"discovery: framework={discovery['framework']} status={discovery['status']} — "
        f"{discovery['detail']}"
    )
    docker = report.get("docker")
    if docker is not None:
        lines.append("")
        lines.append(
            f"docker: cli_present={docker['cli_present']} "
            f"daemon_healthy={docker['daemon_healthy']} "
            f"server_version={docker['server_version']}"
        )
        if docker.get("error_detail"):
            lines.append(f"  detail: {docker['error_detail']}")
    hooks_health = report.get("hooks_health")
    if hooks_health is not None:
        lines.append("")
        status = "DISABLED" if hooks_health["hooks_disabled"] else "active"
        n_present = len(hooks_health["hook_scripts_present"])
        n_total = n_present + len(hooks_health["hook_scripts_missing"])
        lines.append(
            f"hooks: {status} — {n_present}/{n_total} scripts present, "
            f"settings_present={hooks_health['settings_present']}"
        )
        for warning in hooks_health["warnings"]:
            lines.append(f"  [WARN] {warning}")
    if report["suggested_human_actions"]:
        lines.append("")
        lines.append("suggested external/operational actions (HUMAN decision only):")
        lines.extend(f"  - {action}" for action in report["suggested_human_actions"])
    return "\n".join(lines)


def write_report(run_directory: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    """Write `report-<mode>.json` + `.txt` into the run store."""
    mode = report["mode"]
    json_path = run_directory / f"report-{mode}.json"
    text_path = run_directory / f"report-{mode}.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text_path.write_text(render_human(report) + "\n", encoding="utf-8")
    return json_path, text_path
