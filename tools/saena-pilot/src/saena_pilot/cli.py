"""`saena-pilot` CLI — argparse dispatch, `main(argv) -> int` (wave6-plan §3.3).

Mission-fixed UX:

    saena-pilot --customer-repo "/abs/path" --domain "https://customer.example" --mode audit

Exit codes are explicit constants (below). The parser deliberately has NO
bundle-bypass flag and this module consults NO bypass environment variable —
skill-bundle enforcement runs fail-closed at every pilot start (start modes +
resume).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from saena_pilot import __version__
from saena_pilot._git import git_head_sha, git_toplevel
from saena_pilot.boundary import validate_customer_repo
from saena_pilot.bundle import SubprocessRunner, enforce_bundle
from saena_pilot.discovery import default_adapters, discover
from saena_pilot.docker_preflight import probe_docker
from saena_pilot.domain import validate_domain
from saena_pilot.errors import (
    BoundaryViolationError,
    BundleInvalidError,
    ContractIncompleteError,
    PilotError,
    ValidationFailedError,
)
from saena_pilot.evidence import EventKind, EvidenceLog, verify_chain
from saena_pilot.intake import build_contract, load_intake_file, require_complete
from saena_pilot.launcher import (
    LaunchRunner,
    display_command,
    execute_launch,
    list_rule_files,
    reconciliation_section,
    render_launch,
)
from saena_pilot.models import BoundaryReport, LaunchSpec, Mode
from saena_pilot.report import assess_hooks_health, build_report, render_human, write_report
from saena_pilot.runstore import (
    contract_path,
    create_run,
    ensure_store_outside_repos,
    evidence_path,
    list_runs,
    load_run,
    record_evidence_head,
    run_dir,
    validate_resume,
)
from saena_pilot.worktree import create_customer_worktree, worktree_path

#: Exit-code map (frozen for CI/gates; never renumber).
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_USAGE = 2  # argparse's own usage-error code, kept identical
EXIT_CONTRACT_INCOMPLETE = 3
EXIT_BUNDLE_INVALID = 4
EXIT_BOUNDARY_VIOLATION = 5
EXIT_RUNTIME_ERROR = 6


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saena-pilot",
        description=(
            "SAENA external-customer-project pilot launcher. References the customer "
            "repo (never copies it), validates boundaries fail-closed, enforces the "
            "skill bundle at every start, and launches Claude Code from the RAPID-7 "
            "root with --add-dir."
        ),
    )
    parser.add_argument("--version", action="version", version=f"saena-pilot {__version__}")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[mode.value for mode in Mode],
        help="pilot mode",
    )
    parser.add_argument(
        "--customer-repo",
        help="ABSOLUTE path to the customer repository root (start modes)",
    )
    parser.add_argument(
        "--domain",
        help="deployed customer domain, https only (discovery/verification identity)",
    )
    parser.add_argument("--customer-id", help="customer/tenant id for the action contract")
    parser.add_argument(
        "--intake",
        help="path to the human-supplied intake JSON (action-contract inputs)",
    )
    parser.add_argument("--run-id", help="run id (resume/status/verify)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render the exact claude launch argv + env WITHOUT executing",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit machine-readable JSON instead of human text",
    )
    return parser


def _usage_error(parser: argparse.ArgumentParser, message: str) -> int:
    print(f"{parser.prog}: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def _resolve_rapid7_root() -> Path:
    toplevel = git_toplevel(Path.cwd())
    if toplevel is None:
        raise ValidationFailedError(
            "saena-pilot must be run from inside the SAENA RAPID-7 checkout "
            "(current directory is not in a git repository)"
        )
    root = Path(os.path.realpath(toplevel))
    if not (root / ".claude").is_dir():
        raise ValidationFailedError(
            f"{root} does not look like the SAENA RAPID-7 root (no .claude/ directory) "
            "— run saena-pilot from the RAPID-7 checkout"
        )
    return root


def _rapid7_head(rapid7_root: Path) -> str:
    sha = git_head_sha(rapid7_root)
    if sha is None:
        raise ValidationFailedError(
            f"RAPID-7 root {rapid7_root} has no resolvable HEAD commit",
            context={"rapid7_root": str(rapid7_root)},
        )
    return sha


def _suggested_human_actions(
    boundary: BoundaryReport, questions: list[str], rule_files: list[dict[str, Any]]
) -> list[str]:
    actions: list[str] = []
    codes = {finding.code for finding in boundary.findings}
    if "dirty_tree" in codes:
        actions.append(
            "Have the customer commit or stash uncommitted changes before any write mode."
        )
    if "detached_head" in codes:
        actions.append("Have the customer check out a named branch (HEAD is detached).")
    if "nested_repos" in codes:
        actions.append("Review nested git repositories below the customer root with the customer.")
    if rule_files:
        actions.append(
            "Reconcile customer CLAUDE.md/AGENTS.md rules with SAENA rules (stricter wins) "
            "before implement mode."
        )
    if questions:
        actions.append("Answer the open action-contract questions (see contract_questions).")
    return actions


def _print_launch_dry_run(spec: LaunchSpec) -> None:
    print("launch (dry-run — NOT executed):")
    print(f"  cwd:  {spec.cwd}")
    print(f"  argv: {display_command(spec)}")
    for key, value in spec.env_overlay.items():
        print(f"  env:  {key}={value}")


def _run_start_mode(
    args: argparse.Namespace,
    mode: Mode,
    *,
    launch_runner: LaunchRunner | None,
    bundle_runner: SubprocessRunner | None,
) -> int:
    rapid7_root = _resolve_rapid7_root()
    rapid7_sha = _rapid7_head(rapid7_root)

    boundary = validate_customer_repo(args.customer_repo, rapid7_root=rapid7_root, mode=mode)
    domain = validate_domain(args.domain)
    ensure_store_outside_repos(rapid7_root, boundary.customer_root)

    if boundary.blocked:
        details = "; ".join(f"{f.code}: {f.detail}" for f in boundary.block_findings)
        raise ValidationFailedError(
            f"customer repo state blocks mode {mode.value!r}: {details}",
            context={"blocked": [f.code for f in boundary.block_findings]},
        )

    bundle = enforce_bundle(rapid7_root, runner=bundle_runner)

    intake_data = load_intake_file(args.intake) if args.intake else None
    contract, questions = build_contract(
        customer_repo=str(boundary.customer_root),
        domain=domain,
        customer_id=args.customer_id,
        intake_data=intake_data,
    )
    if mode.requires_complete_contract:
        require_complete(contract, questions)

    record = create_run(
        customer_repo=boundary.customer_root,
        domain=domain,
        customer_id=contract.customer_id,
        rapid7_sha=rapid7_sha,
        customer_sha=boundary.head_sha,
        contract_sha256=contract.contract_sha256,
        manifest_sha256=bundle.manifest_sha256,
        mode=mode.value,
    )
    directory = run_dir(record.run_id)
    contract_path(record.run_id).write_text(
        json.dumps(contract.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    log = EvidenceLog.create(
        evidence_path(record.run_id),
        {
            "rapid7_sha": rapid7_sha,
            "customer_sha": boundary.head_sha,
            "domain": domain,
            "mode": mode.value,
            "run_id": record.run_id,
            "manifest_schema_version": bundle.manifest_schema_version,
            "manifest_sha256": bundle.manifest_sha256,
            "skill_names": list(bundle.skill_names),
        },
    )

    def _append(event: str, kind: EventKind, payload: dict[str, Any]) -> None:
        log.append(event, kind, payload)
        record_evidence_head(record, log.head())

    record_evidence_head(record, log.head())
    _append("boundary-validated", EventKind.RUN_META, boundary.to_dict())
    _append("bundle-validated", EventKind.RUN_META, bundle.to_dict())
    _append(
        "contract-recorded",
        EventKind.RUN_META,
        {"contract_sha256": contract.contract_sha256, "complete": not questions},
    )

    rule_files = list_rule_files(boundary.customer_root)
    reconciliation = reconciliation_section(rule_files)
    discovery_result = discover(boundary.customer_root, adapters=default_adapters())
    docker_status = probe_docker()
    hooks_health = assess_hooks_health(rapid7_root)
    actions = _suggested_human_actions(boundary, questions, rule_files)
    if actions:
        _append(
            "external-actions-suggested",
            EventKind.EXTERNAL_ACTION_SUGGESTED,
            {"actions": actions},
        )

    worktree_target: Path | None = None
    if mode.writes_customer:
        if args.dry_run:
            # Dry-run renders the exact argv but performs NO customer-side
            # write — the worktree path is deterministic, so it can be shown
            # without being created.
            worktree_target = worktree_path(boundary.customer_root, record.run_id)
        else:
            worktree_target = create_customer_worktree(
                boundary.customer_root, record.run_id, mode=mode
            )
            record.worktree_path = str(worktree_target)
            _append(
                "worktree-created",
                EventKind.REPO_EDIT,
                {"worktree": str(worktree_target), "branch": f"saena-pilot/{record.run_id}"},
            )

    report = build_report(
        mode=mode.value,
        run_id=record.run_id,
        rapid7_sha=rapid7_sha,
        boundary=boundary,
        domain=domain,
        bundle=bundle,
        contract=contract.to_dict(),
        contract_questions=questions,
        reconciliation=reconciliation,
        discovery=discovery_result.to_dict(),
        docker=docker_status.to_dict(),
        hooks_health=hooks_health,
        suggested_human_actions=actions,
    )
    json_path, text_path = write_report(directory, report)
    _append(
        "report-written",
        EventKind.RUN_META,
        {"report_json": str(json_path), "report_text": str(text_path)},
    )

    launch_spec: LaunchSpec | None = None
    launch_exit: int | None = None
    if mode.launches_claude:
        launch_spec = render_launch(
            mode=mode,
            rapid7_root=rapid7_root,
            customer_root=boundary.customer_root,
            worktree=worktree_target,
            run_id=record.run_id,
            run_dir=directory,
        )
        _append(
            "launch-rendered",
            EventKind.RUN_META,
            {**launch_spec.to_dict(), "dry_run": args.dry_run},
        )
        if not args.dry_run:
            launch_exit = execute_launch(launch_spec, runner=launch_runner)
            _append(
                "launch-executed",
                EventKind.RUN_META,
                {"returncode": launch_exit},
            )

    if args.as_json:
        print(
            json.dumps(
                {
                    "run_id": record.run_id,
                    "mode": mode.value,
                    "report": report,
                    "report_paths": [str(json_path), str(text_path)],
                    "launch": launch_spec.to_dict() if launch_spec else None,
                    "dry_run": args.dry_run,
                    "launch_exit": launch_exit,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(render_human(report))
        print()
        print(f"run stored: {directory}")
        if launch_spec is not None and args.dry_run:
            print()
            _print_launch_dry_run(launch_spec)
        elif launch_exit is not None:
            print(f"claude exited with {launch_exit}")

    if launch_exit is not None and launch_exit != 0:
        return EXIT_RUNTIME_ERROR
    return EXIT_OK


def _run_verify(args: argparse.Namespace) -> int:
    record = load_run(args.run_id)
    head = verify_chain(evidence_path(record.run_id), expected_head=record.chain_head)
    payload = {
        "run_id": record.run_id,
        "evidence_records": head.count,
        "chain_head": head.chain_hash,
        "verified": True,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"evidence chain VERIFIED for run {record.run_id}: {head.count} record(s), "
            f"head {head.chain_hash[:16]}…"
        )
    return EXIT_OK


def _run_status(args: argparse.Namespace) -> int:
    if not args.run_id:
        runs = list_runs()
        if args.as_json:
            print(json.dumps({"runs": runs}, indent=2))
        else:
            if not runs:
                print("no pilot runs recorded")
            for run_id in runs:
                print(run_id)
        return EXIT_OK

    record = load_run(args.run_id)
    try:
        verify_chain(evidence_path(record.run_id), expected_head=record.chain_head)
        evidence_status = "VERIFIED"
    except ValidationFailedError as exc:
        evidence_status = f"INVALID ({exc})"
    payload = {**record.to_dict(), "evidence_status": evidence_status}
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"run {record.run_id}")
        print(f"  created:       {record.created_ts}")
        print(f"  customer repo: {record.customer_repo}")
        print(f"  domain:        {record.domain}")
        print(f"  customer id:   {record.customer_id}")
        print(f"  RAPID-7 SHA:   {record.rapid7_sha}")
        print(f"  customer SHA:  {record.customer_sha}")
        print(f"  modes:         {[entry['mode'] for entry in record.mode_history]}")
        print(f"  worktree:      {record.worktree_path}")
        print(f"  evidence:      {evidence_status}")
    return EXIT_OK


def _run_resume(
    args: argparse.Namespace,
    *,
    bundle_runner: SubprocessRunner | None,
) -> int:
    rapid7_root = _resolve_rapid7_root()
    record = load_run(args.run_id)
    validate_resume(record, rapid7_root=rapid7_root)
    boundary = validate_customer_repo(
        record.customer_repo, rapid7_root=rapid7_root, mode=Mode.RESUME
    )
    bundle = enforce_bundle(rapid7_root, runner=bundle_runner)
    if bundle.manifest_sha256 != record.manifest_sha256:
        raise ValidationFailedError(
            f"skill manifest changed since run {record.run_id} was recorded "
            f"(recorded {record.manifest_sha256}, current {bundle.manifest_sha256}) — "
            "refusing resume; start a fresh run",
            context={"run_id": record.run_id},
        )
    verify_chain(evidence_path(record.run_id), expected_head=record.chain_head)

    log = EvidenceLog(evidence_path(record.run_id))
    log.append(
        "resume-validated",
        EventKind.RUN_META,
        {"boundary": boundary.to_dict(), "manifest_sha256": bundle.manifest_sha256},
    )
    record_evidence_head(record, log.head())

    last_mode = record.mode_history[-1]["mode"] if record.mode_history else None
    payload = {
        "run_id": record.run_id,
        "resumable": True,
        "last_mode": last_mode,
        "boundary_findings": [f.to_dict() for f in boundary.findings],
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"run {record.run_id} is RESUMABLE (state re-validated)")
        print(f"  last mode: {last_mode}")
        print(
            f"  next step: re-invoke saena-pilot --mode {last_mode} … or continue "
            "with the recorded worktree"
        )
    return EXIT_OK


def _dispatch(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    launch_runner: LaunchRunner | None,
    bundle_runner: SubprocessRunner | None,
) -> int:
    mode = Mode(args.mode)

    if mode.starts_run:
        missing = [
            flag
            for flag, value in (("--customer-repo", args.customer_repo), ("--domain", args.domain))
            if not value
        ]
        if missing:
            return _usage_error(parser, f"mode {mode.value!r} requires {', '.join(missing)}")
        if args.run_id:
            return _usage_error(
                parser, f"--run-id is not valid with mode {mode.value!r} (a new run id is minted)"
            )
        return _run_start_mode(args, mode, launch_runner=launch_runner, bundle_runner=bundle_runner)

    # verify / resume / status operate on recorded runs.
    for flag, value in (
        ("--customer-repo", args.customer_repo),
        ("--domain", args.domain),
        ("--customer-id", args.customer_id),
        ("--intake", args.intake),
    ):
        if value:
            return _usage_error(
                parser,
                f"{flag} is not valid with mode {mode.value!r} (recorded in the run store)",
            )
    if mode in (Mode.VERIFY, Mode.RESUME) and not args.run_id:
        return _usage_error(parser, f"mode {mode.value!r} requires --run-id")

    if mode is Mode.VERIFY:
        return _run_verify(args)
    if mode is Mode.RESUME:
        return _run_resume(args, bundle_runner=bundle_runner)
    return _run_status(args)


def main(
    argv: Sequence[str] | None = None,
    *,
    launch_runner: LaunchRunner | None = None,
    bundle_runner: SubprocessRunner | None = None,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse prints its own message; normalize --help to OK and any
        # usage error to the explicit USAGE constant.
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE

    try:
        return _dispatch(args, parser, launch_runner=launch_runner, bundle_runner=bundle_runner)
    except ContractIncompleteError as exc:
        print(f"saena-pilot: {exc}", file=sys.stderr)
        return EXIT_CONTRACT_INCOMPLETE
    except BundleInvalidError as exc:
        print(f"saena-pilot: {exc}", file=sys.stderr)
        return EXIT_BUNDLE_INVALID
    except BoundaryViolationError as exc:
        print(f"saena-pilot: {exc}", file=sys.stderr)
        return EXIT_BOUNDARY_VIOLATION
    except ValidationFailedError as exc:
        print(f"saena-pilot: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    except PilotError as exc:
        print(f"saena-pilot: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except Exception as exc:  # noqa: BLE001 — CLI boundary: never traceback at the user
        print(f"saena-pilot: unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


def entry() -> None:
    """Console-script entry point (`[project.scripts] saena-pilot`)."""
    sys.exit(main())
