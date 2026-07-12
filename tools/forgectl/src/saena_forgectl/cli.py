"""`forgectl` CLI — argparse dispatch. `preflight` is the W2C deliverable
(k3s spec §8.1); the top-level `--version` flag and `preflight` subcommand
are the only surface this patch unit implements — additional `forgectl`
subcommands (`install`, `rollback`, ...) are future work, not stubbed here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from saena_forgectl import __version__
from saena_forgectl.errors import ValuesFileError
from saena_forgectl.models import PreflightReport
from saena_forgectl.preflight import run_preflight

#: Exit codes (k3s spec §8.1: preflight either passes or names what
#: failed). `2` is deliberately distinct from `1` — a malformed values file
#: is "your input could not even be evaluated", not "your input was
#: evaluated and rejected" (CI needs to tell these apart: the latter means
#: "fix the declared config", the former means "the file itself is
#: broken").
EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_VALUES_FILE_INVALID = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgectl",
        description="SAENA FORGE k3s package operator CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"forgectl {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run the k3s spec §8.1 static preflight checks against a Helm values file",
    )
    preflight_parser.add_argument(
        "--values",
        required=True,
        help="Path to the Helm values YAML file to check",
    )
    preflight_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the report as JSON instead of the human-readable report",
    )
    # Live-cluster verification flags from the k3s spec §8.1 example
    # invocation are accepted for command-line compatibility but are
    # documented no-ops in this static-preflight implementation — see
    # tools/forgectl/README.md's "Out (documented extension point)"
    # section. Accepting-and-warning (rather than rejecting as unknown
    # flags) keeps the exact §8.1 example invocation runnable today.
    live_check_flags = (
        "--verify-signatures",
        "--check-network-policy",
        "--check-external-secrets",
        "--check-registry",
    )
    for flag in live_check_flags:
        preflight_parser.add_argument(flag, action="store_true", help=argparse.SUPPRESS)

    return parser


def _render_human_report(report: PreflightReport, *, values_path: str) -> str:
    lines = [f"forgectl preflight — {values_path}", ""]
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{status}] {check.name}: {check.detail}")
    lines.append("")
    if report.passed:
        lines.append("preflight: all checks passed")
    else:
        failed_names = ", ".join(check.name for check in report.failed_checks)
        failed_count = len(report.failed_checks)
        lines.append(f"preflight: FAILED — {failed_count} check(s) failed: {failed_names}")
    return "\n".join(lines)


def _run_preflight_command(args: argparse.Namespace) -> int:
    live_flags_requested = [
        flag_name
        for flag_name, dest in (
            ("--verify-signatures", "verify_signatures"),
            ("--check-network-policy", "check_network_policy"),
            ("--check-external-secrets", "check_external_secrets"),
            ("--check-registry", "check_registry"),
        )
        if getattr(args, dest, False)
    ]

    try:
        report = run_preflight(args.values)
    except ValuesFileError as exc:
        if args.as_json:
            print(json.dumps({"error_code": exc.error_code, "message": str(exc), **exc.context}))
        else:
            print(f"forgectl preflight: {exc}", file=sys.stderr)
        return EXIT_VALUES_FILE_INVALID

    if args.as_json:
        payload = report.to_dict()
        if live_flags_requested:
            payload["live_flags_accepted_as_noop"] = live_flags_requested
        print(json.dumps(payload, indent=2))
    else:
        print(_render_human_report(report, values_path=args.values))
        if live_flags_requested:
            print(
                "\nnote: "
                + ", ".join(live_flags_requested)
                + " are accepted for §8.1 command-line compatibility but this is a "
                "static preflight — no live-cluster verification is performed "
                "(see tools/forgectl/README.md)."
            )

    return EXIT_OK if report.passed else EXIT_CHECKS_FAILED


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "preflight":
        return _run_preflight_command(args)

    parser.print_help()
    return EXIT_OK
