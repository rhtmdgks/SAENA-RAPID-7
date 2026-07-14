#!/usr/bin/env python3
"""Fail-closed renderer for required-measurement-gate evidence (Wave 5 Closure).

Reads the machine-generated evidence JSON a gate's completeness guard wrote
(see ``tests/integration/_gate_evidence.py``) and renders a GitHub job summary
FROM that evidence — never a static success claim. Exits NON-ZERO (fail closed)
whenever the evidence is missing, malformed, schema-mismatched, stale (bound to
a different commit/run), or reports an incomplete / failed / not-real-container
gate. A green render therefore means the gate demonstrably executed the full
required set against real containers on THIS commit+run.

Usage:
    render_gate_evidence.py --gate <e2e|failure-modes> --evidence <path> \
        [--summary-file $GITHUB_STEP_SUMMARY]

Exit codes: 0 = evidence proves a complete, real-container, passing gate.
            non-zero = anything else (the CI step fails, so a false green cannot
            be produced by the summary step running on its own).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "saena.gate-evidence/v1"

# Which backend legs each gate MUST prove ran against a real container/server.
REQUIRED_LEGS: dict[str, tuple[str, ...]] = {
    "e2e": ("postgres", "clickhouse", "temporal"),
    "failure-modes": ("postgres",),
}


def _fail(summary_lines: list[str], reason: str) -> None:
    summary_lines.append(f"- **RESULT: FAILED / NOT PROVEN** — {reason}")


def _load(evidence_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not evidence_path.exists():
        return (
            None,
            f"evidence file `{evidence_path}` does not exist "
            "(gate did not run or crashed before writing)",
        )
    try:
        raw = evidence_path.read_text()
    except OSError as exc:
        return None, f"evidence file unreadable: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"evidence file is not valid JSON (malformed): {exc}"
    if not isinstance(data, dict):
        return None, "evidence file is not a JSON object"
    return data, None


def _check_binding(data: dict[str, Any]) -> str | None:
    binding = data.get("run_binding")
    if not isinstance(binding, dict):
        return "evidence has no run_binding block"
    env_sha = os.environ.get("GITHUB_SHA")
    env_run = os.environ.get("GITHUB_RUN_ID")
    # In CI both are set — enforce an exact match so a stale artifact from a
    # different commit/run cannot render as this run's success. Locally (no
    # GITHUB_SHA) skip the CI-binding check; the evidence still had to be freshly
    # written by this process's guard.
    if env_sha and binding.get("commit_sha") != env_sha:
        return (
            f"evidence commit_sha `{binding.get('commit_sha')}` != this run's "
            f"GITHUB_SHA `{env_sha}` (stale/reused evidence)"
        )
    if env_run and str(binding.get("github_run_id")) != str(env_run):
        return (
            f"evidence github_run_id `{binding.get('github_run_id')}` != this "
            f"run's GITHUB_RUN_ID `{env_run}` (stale/reused evidence)"
        )
    return None


def render(gate: str, evidence_path: Path) -> tuple[int, str]:
    lines: list[str] = [f"### measurement-{gate} gate — runtime evidence", ""]
    required_legs = REQUIRED_LEGS.get(gate)
    if required_legs is None:
        lines.append(f"- **RESULT: FAILED** — unknown gate `{gate}`")
        return 1, "\n".join(lines)

    data, err = _load(evidence_path)
    if err:
        _fail(lines, err)
        return 1, "\n".join(lines)
    assert data is not None

    if data.get("schema_version") != SCHEMA_VERSION:
        _fail(
            lines,
            f"schema_version `{data.get('schema_version')}` != expected `{SCHEMA_VERSION}`",
        )
        return 1, "\n".join(lines)

    if data.get("gate_name") != gate:
        _fail(lines, f"evidence gate_name `{data.get('gate_name')}` != `{gate}`")
        return 1, "\n".join(lines)

    binding_err = _check_binding(data)
    if binding_err:
        _fail(lines, binding_err)
        return 1, "\n".join(lines)

    # --- render the recorded facts (always, so a failure is visible) --------- #
    b = data.get("run_binding", {})
    lines.append(f"- SHA: `{b.get('commit_sha')}`")
    lines.append(f"- run: `{b.get('github_run_id')}` attempt `{b.get('github_run_attempt')}`")
    lines.append(f"- required-mode armed: `{data.get('required_mode_armed')}`")
    lines.append(
        f"- expected={data.get('expected_count')} selected={data.get('selected_count')} "
        f"executed={data.get('executed_count')} passed={data.get('passed_count')} "
        f"failed={data.get('failed_count')} skipped={data.get('skipped_count')} "
        f"xfailed={data.get('xfailed_count')} xpassed={data.get('xpassed_count')} "
        f"deselected={data.get('deselected_count')}"
    )
    missing = data.get("missing_node_ids") or []
    unexpected = data.get("unexpected_node_ids") or []
    dups = data.get("duplicate_ids") or []
    lines.append(f"- missing={len(missing)} unexpected={len(unexpected)} duplicate_ids={len(dups)}")
    legs = data.get("legs") or {}
    if legs:
        leg_str = ", ".join(
            f"{name}: exec={info.get('executed')} passed={info.get('passed')} "
            f"witness={'yes' if info.get('witness') else 'NO'}"
            for name, info in sorted(legs.items())
        )
        lines.append(f"- legs → {leg_str}")
    if gate == "failure-modes":
        lines.append(
            f"- primary: expected={data.get('primary_expected')} "
            f"executed={data.get('primary_executed')} passed={data.get('primary_passed')}; "
            f"recovery: expected={data.get('recovery_expected')} "
            f"executed={data.get('recovery_executed')} passed={data.get('recovery_passed')}"
        )
    wl = data.get("witnesses") or {}
    if wl:
        lines.append(
            "- container witnesses: "
            + ", ".join(f"{k}=`{v.get('image')}`" for k, v in sorted(wl.items()))
        )

    # --- the gating decision (fail closed on any shortfall) ------------------ #
    problems: list[str] = []
    if not data.get("required_mode_armed"):
        problems.append("required mode was NOT armed")
    if not data.get("completeness_passed"):
        problems.append("completeness_passed is not true")
    if missing:
        problems.append(f"{len(missing)} required node(s) did not execute-and-PASS")
    if int(data.get("skipped_count") or 0) != 0:
        problems.append(f"skipped_count={data.get('skipped_count')} (required gate must be 0)")
    if int(data.get("failed_count") or 0) != 0:
        problems.append(f"failed_count={data.get('failed_count')}")
    if not data.get("real_containers_proven"):
        problems.append("real_containers_proven is not true")
    for leg in required_legs:
        info = legs.get(leg) if isinstance(legs, dict) else None
        if not info or not info.get("witness"):
            problems.append(f"no real-container witness for the '{leg}' leg")
        elif int(info.get("passed") or 0) <= 0:
            problems.append(f"zero passing tests on the '{leg}' leg")
    if int(data.get("expected_count") or 0) <= 0:
        problems.append("expected_count is 0 (empty manifest)")

    if problems:
        lines.append("")
        _fail(lines, "; ".join(problems))
        return 1, "\n".join(lines)

    lines.append("")
    lines.append(
        f"- **RESULT: PROVEN** — full required set ({data.get('expected_count')} scenarios) "
        "executed and PASSED against real containers on this commit+run; skipped=0, missing=0."
    )
    return 0, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, choices=sorted(REQUIRED_LEGS))
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument(
        "--summary-file",
        type=Path,
        default=None,
        help="append the rendered markdown here (e.g. $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args(argv)

    code, summary = render(args.gate, args.evidence)

    target = args.summary_file or os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(summary + "\n")
        except OSError:
            print(summary)
    else:
        print(summary)
    if code != 0:
        print(
            f"::error::measurement-{args.gate} evidence check FAILED (see job summary)",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
