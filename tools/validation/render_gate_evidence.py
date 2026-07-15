#!/usr/bin/env python3
"""STRICT fail-closed validator + renderer for required-measurement-gate
evidence (Wave 5 Closure — strict evidence validation).

Reads the machine-generated evidence JSON a gate's completeness guard wrote
(``tests/integration/_gate_evidence.py``) and renders a GitHub job summary FROM
that evidence — never a static success claim, and never by TRUSTING the
producer's ``completeness_passed`` assertion. It INDEPENDENTLY re-derives
acceptance from mutually consistent facts against an authoritative spec
(``gate_evidence_spec.py``): execution lifecycle, exact count consistency,
per-leg + primary/recovery consistency, strict runtime-witness shape, and exact
run/invocation binding. ANY missing field, wrong type (incl. bool-vs-int),
null, contradiction, stale/mismatched binding, or fabricated witness makes it
exit NON-ZERO (NOT PROVEN). Only a fully self-consistent, real-container,
fully-passing, correctly-bound payload returns 0.

Usage:
    render_gate_evidence.py --gate <e2e|failure-modes> --evidence <path> \
        [--summary-file $GITHUB_STEP_SUMMARY]

Exit codes: 0 = PROVEN; non-zero = fail closed. Booleans are checked with strict
`is True` (never truthiness); integers must be real ints (a JSON `true` is NOT
accepted where an int is required, and vice-versa).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from gate_evidence_spec import SCHEMA_VERSION, SPEC, GateSpec  # noqa: E402

#: Binding evidence field -> the env var it must match.
_BINDING_ENV = {
    "commit_sha": "GITHUB_SHA",
    "github_run_id": "GITHUB_RUN_ID",
    "github_run_attempt": "GITHUB_RUN_ATTEMPT",
    "invocation_id": "SAENA_GATE_INVOCATION_ID",
}
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")


# --------------------------------------------------------------------------- #
# Strict type helpers — never truthiness for security-critical fields.
# --------------------------------------------------------------------------- #
def _is_true(v: Any) -> bool:
    return v is True


def _int_or_none(v: Any) -> int | None:
    # A JSON bool is an int subclass in Python — explicitly reject it, and
    # reject floats/strings so "0"/0.0/true never satisfy an int requirement.
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _node_file(node_id: str) -> str:
    return node_id.split("::", 1)[0] if isinstance(node_id, str) else ""


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _load(evidence_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not evidence_path.exists():
        return None, (
            f"evidence file `{evidence_path}` does not exist "
            "(gate did not run or crashed before writing)"
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


# --------------------------------------------------------------------------- #
# Independent validators — each appends human-readable NOT-PROVEN reasons.
# --------------------------------------------------------------------------- #
def _require_true(data: dict[str, Any], key: str, problems: list[str]) -> None:
    if not _is_true(data.get(key)):
        problems.append(f"{key} is not the boolean True (got {data.get(key)!r})")


def _require_int_eq(data: dict[str, Any], key: str, expected: int, problems: list[str]) -> None:
    v = _int_or_none(data.get(key))
    if v is None:
        problems.append(f"{key} is not an integer (got {data.get(key)!r})")
    elif v != expected:
        problems.append(f"{key}={v} != expected {expected}")


def _require_empty_list(data: dict[str, Any], key: str, problems: list[str]) -> None:
    v = data.get(key)
    if not isinstance(v, list):
        problems.append(f"{key} is not a list (got {type(v).__name__})")
    elif v:
        problems.append(f"{key} is non-empty ({len(v)}): {sorted(map(str, v))[:6]}")


def _validate_lifecycle(data: dict[str, Any], problems: list[str]) -> None:
    for key in (
        "command_started",
        "collection_completed",
        "required_mode_armed",
        "completeness_passed",
        "real_containers_proven",
    ):
        _require_true(data, key, problems)
    _require_int_eq(data, "exit_code", 0, problems)


def _validate_counts(data: dict[str, Any], spec: GateSpec, problems: list[str]) -> None:
    exp = _int_or_none(data.get("expected_count"))
    if exp is None:
        problems.append(f"expected_count is not an integer (got {data.get('expected_count')!r})")
        return
    if exp <= 0:
        problems.append(f"expected_count={exp} is not > 0 (empty manifest)")
    if exp != spec.expected_count:
        problems.append(f"expected_count={exp} != authoritative {spec.expected_count}")
    # Every count field pinned to the required-manifest size (or 0).
    for key in ("selected_count", "executed_count", "passed_count"):
        _require_int_eq(data, key, spec.expected_count, problems)
    for key in (
        "failed_count",
        "skipped_count",
        "xfailed_count",
        "xpassed_count",
        "deselected_count",
    ):
        _require_int_eq(data, key, 0, problems)
    _require_empty_list(data, "missing_node_ids", problems)
    _require_empty_list(data, "duplicate_ids", problems)
    # Relational belt-and-suspenders (independent of the exact-equality above).
    p, e, s = (
        _int_or_none(data.get("passed_count")),
        _int_or_none(data.get("executed_count")),
        _int_or_none(data.get("selected_count")),
    )
    if p is not None and e is not None and p > e:
        problems.append(f"passed_count={p} > executed_count={e}")
    if e is not None and s is not None and e > s:
        problems.append(f"executed_count={e} > selected_count={s}")


def _validate_unexpected(data: dict[str, Any], spec: GateSpec, problems: list[str]) -> None:
    unexpected = data.get("unexpected_node_ids")
    if not isinstance(unexpected, list):
        problems.append("unexpected_node_ids is not a list")
        return
    allowed = set(spec.authorized_unexpected_files)
    for node in unexpected:
        f = _node_file(node)
        if f not in allowed:
            problems.append(
                f"unauthorized unexpected node `{node}` (file `{f}` not an "
                "authorized guard/meta-test file — cannot substitute for a "
                "required manifest node)"
            )


def _validate_legs(data: dict[str, Any], spec: GateSpec, problems: list[str]) -> None:
    legs = data.get("legs")
    if not isinstance(legs, dict):
        problems.append("legs block is not an object")
        return
    for leg in spec.all_legs:
        info = legs.get(leg)
        if not isinstance(info, dict):
            problems.append(f"legs['{leg}'] missing or not an object")
            continue
        expected = spec.leg_expected[leg]
        ex = _int_or_none(info.get("executed"))
        pa = _int_or_none(info.get("passed"))
        if ex is None or ex != expected:
            problems.append(f"legs['{leg}'].executed={info.get('executed')!r} != {expected}")
        if pa is None or pa != expected:
            problems.append(f"legs['{leg}'].passed={info.get('passed')!r} != {expected}")
        # Every required leg (and the composed logical leg) must be witnessed.
        must_witness = leg in spec.required_witness_legs or (
            leg == "composed" and spec.has_composed_leg
        )
        if must_witness and not _is_true(info.get("witness")):
            problems.append(f"legs['{leg}'].witness is not True")


def _validate_witnesses(data: dict[str, Any], spec: GateSpec, problems: list[str]) -> None:
    witnesses = data.get("witnesses")
    if not isinstance(witnesses, dict):
        problems.append("witnesses block is not an object")
        return
    for leg in spec.required_witness_legs:
        w = witnesses.get(leg)
        if not isinstance(w, dict):
            problems.append(f"no runtime witness object for the '{leg}' leg")
            continue
        if not _is_true(w.get("started")):
            problems.append(
                f"witness '{leg}'.started is not the boolean True (got {w.get('started')!r})"
            )
        if w.get("leg") != leg:
            problems.append(
                f"witness '{leg}'.leg={w.get('leg')!r} != key '{leg}' (leg/key mismatch)"
            )
        image = w.get("image")
        prefix = spec.witness_image_prefix.get(leg, "")
        if not _nonempty_str(image):
            problems.append(f"witness '{leg}'.image is empty/absent")
        elif not image.startswith(prefix):
            problems.append(
                f"witness '{leg}'.image `{image}` not in the approved family `{prefix}…`"
            )
        if leg in spec.container_id_required_legs:
            cid = w.get("container_id")
            if not _nonempty_str(cid) or not _CONTAINER_ID_RE.match(cid.strip()):
                problems.append(
                    f"witness '{leg}'.container_id `{cid}` is not a valid nonempty container id"
                )
    # composed is proven ONLY by the underlying real DB witnesses.
    if spec.has_composed_leg:
        for leg in ("postgres", "clickhouse"):
            if not isinstance(witnesses.get(leg), dict):
                problems.append(f"'composed' leg not backed by a real '{leg}' witness")


def _validate_primary_recovery(data: dict[str, Any], spec: GateSpec, problems: list[str]) -> None:
    if not spec.has_primary_recovery:
        return
    _require_int_eq(data, "primary_expected", spec.primary_expected, problems)
    _require_int_eq(data, "recovery_expected", spec.recovery_expected, problems)
    _require_int_eq(data, "primary_executed", spec.primary_expected, problems)
    _require_int_eq(data, "primary_passed", spec.primary_expected, problems)
    _require_int_eq(data, "recovery_executed", spec.recovery_expected, problems)
    _require_int_eq(data, "recovery_passed", spec.recovery_expected, problems)
    _require_int_eq(data, "postgres_scenarios", spec.postgres_scenarios, problems)
    pe, re_ = (
        _int_or_none(data.get("primary_expected")),
        _int_or_none(data.get("recovery_expected")),
    )
    exp = _int_or_none(data.get("expected_count"))
    if pe is not None and re_ is not None and exp is not None and pe + re_ != exp:
        problems.append(f"primary({pe})+recovery({re_}) != expected_count({exp})")


def _validate_binding(data: dict[str, Any], problems: list[str]) -> None:
    binding = data.get("run_binding")
    if not isinstance(binding, dict):
        problems.append("evidence has no run_binding object")
        return
    ci_mode = bool((os.environ.get("GITHUB_SHA") or "").strip())
    any_expected = False
    for field, var in _BINDING_ENV.items():
        expected = os.environ.get(var)
        actual = binding.get(field)
        has_expected = expected is not None and expected.strip() != ""
        if has_expected:
            any_expected = True
            if not _nonempty_str(actual):
                problems.append(f"binding.{field} is absent/blank while {var} is set")
            elif actual.strip() != expected.strip():
                problems.append(
                    f"binding.{field}=`{actual}` != {var}=`{expected}` (stale/reused evidence)"
                )
        elif ci_mode:
            # CI required mode: every binding field must be present + nonblank
            # even if a particular env var wasn't forwarded to this step.
            if not _nonempty_str(actual):
                problems.append(
                    f"CI mode: binding.{field} is absent/blank (all binding fields required)"
                )
    # Locally (no GitHub env at all), require an explicit expected binding so a
    # bare `render` can't be silently unbound — the caller must supply at least
    # one of the *_ENV vars (tests do). Never weakens CI.
    if not ci_mode and not any_expected:
        problems.append(
            "no run-binding env supplied (GITHUB_SHA/RUN_ID/RUN_ATTEMPT/"
            "SAENA_GATE_INVOCATION_ID) — cannot validate the evidence is bound "
            "to this invocation; refusing to render PROVEN unbound"
        )


# --------------------------------------------------------------------------- #
# Rendering (facts always shown; PROVEN only when zero problems)
# --------------------------------------------------------------------------- #
def _render_facts(data: dict[str, Any], gate: str, lines: list[str]) -> None:
    b = data.get("run_binding") if isinstance(data.get("run_binding"), dict) else {}
    lines.append(f"- SHA: `{b.get('commit_sha')}`")
    lines.append(
        f"- run: `{b.get('github_run_id')}` attempt `{b.get('github_run_attempt')}` "
        f"invocation `{b.get('invocation_id')}`"
    )
    lines.append(f"- required-mode armed: `{data.get('required_mode_armed')}`")
    lines.append(
        f"- expected={data.get('expected_count')} selected={data.get('selected_count')} "
        f"executed={data.get('executed_count')} passed={data.get('passed_count')} "
        f"failed={data.get('failed_count')} skipped={data.get('skipped_count')} "
        f"xfailed={data.get('xfailed_count')} xpassed={data.get('xpassed_count')} "
        f"deselected={data.get('deselected_count')}"
    )
    missing = data.get("missing_node_ids") if isinstance(data.get("missing_node_ids"), list) else []
    unexpected = (
        data.get("unexpected_node_ids") if isinstance(data.get("unexpected_node_ids"), list) else []
    )
    dups = data.get("duplicate_ids") if isinstance(data.get("duplicate_ids"), list) else []
    lines.append(f"- missing={len(missing)} unexpected={len(unexpected)} duplicate_ids={len(dups)}")
    legs = data.get("legs") if isinstance(data.get("legs"), dict) else {}
    if legs:
        leg_str = ", ".join(
            f"{name}: exec={info.get('executed')} passed={info.get('passed')} "
            f"witness={'yes' if info.get('witness') is True else 'NO'}"
            for name, info in sorted(legs.items())
            if isinstance(info, dict)
        )
        lines.append(f"- legs → {leg_str}")
    if gate == "failure-modes":
        lines.append(
            f"- primary exp/exec/pass={data.get('primary_expected')}/"
            f"{data.get('primary_executed')}/{data.get('primary_passed')}; "
            f"recovery={data.get('recovery_expected')}/"
            f"{data.get('recovery_executed')}/{data.get('recovery_passed')}"
        )
    wl = data.get("witnesses") if isinstance(data.get("witnesses"), dict) else {}
    if wl:
        lines.append(
            "- container witnesses: "
            + ", ".join(
                f"{k}=`{v.get('image')}`(id={v.get('container_id')})"
                for k, v in sorted(wl.items())
                if isinstance(v, dict)
            )
        )


def render(gate: str, evidence_path: Path) -> tuple[int, str]:
    lines: list[str] = [f"### measurement-{gate} gate — runtime evidence (strict)", ""]
    spec = SPEC.get(gate)
    if spec is None:
        lines.append(f"- **RESULT: FAILED** — unknown gate `{gate}`")
        return 1, "\n".join(lines)

    data, err = _load(evidence_path)
    if err:
        lines.append(f"- **RESULT: FAILED / NOT PROVEN** — {err}")
        return 1, "\n".join(lines)
    assert data is not None

    # Structural gates first (schema/gate_name) — a wrong shape can't be rendered.
    if data.get("schema_version") != SCHEMA_VERSION:
        lines.append(
            f"- **RESULT: FAILED / NOT PROVEN** — schema_version "
            f"`{data.get('schema_version')}` != expected `{SCHEMA_VERSION}`"
        )
        return 1, "\n".join(lines)
    if data.get("gate_name") != gate:
        lines.append(
            f"- **RESULT: FAILED / NOT PROVEN** — evidence gate_name "
            f"`{data.get('gate_name')}` != `{gate}`"
        )
        return 1, "\n".join(lines)

    _render_facts(data, gate, lines)

    problems: list[str] = []
    _validate_binding(data, problems)
    _validate_lifecycle(data, problems)
    _validate_counts(data, spec, problems)
    _validate_unexpected(data, spec, problems)
    _validate_legs(data, spec, problems)
    _validate_witnesses(data, spec, problems)
    _validate_primary_recovery(data, spec, problems)

    lines.append("")
    if problems:
        lines.append(f"- **RESULT: FAILED / NOT PROVEN** — {'; '.join(problems)}")
        return 1, "\n".join(lines)

    lines.append(
        f"- **RESULT: PROVEN** — {spec.expected_count} required scenarios "
        "execute-and-PASSED against real containers, all counts/legs/witnesses/"
        "binding mutually consistent on this commit+run+invocation; skipped=0, missing=0."
    )
    return 0, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, choices=sorted(SPEC))
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
