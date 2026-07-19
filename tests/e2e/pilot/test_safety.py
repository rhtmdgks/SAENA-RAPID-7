"""E2E safety invariants: Unicode/space paths, hostile-content quarantine, and
honest Docker-absence reporting.

Scenario keys: ``unicode_path_audit``, ``malicious_quarantined``,
``docker_absent_honest``.
"""

from __future__ import annotations

from pathlib import Path

from _e2e_run import assert_settings_intact, start
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED


def _pilot_home_blob(pilot_home: Path) -> str:
    """Every byte the pilot wrote under the run store, concatenated — used to
    prove a planted secret sentinel never landed in ANY artifact."""
    parts: list[str] = []
    for path in sorted(pilot_home.rglob("*")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, argv, cwd, env) -> int:  # type: ignore[no-untyped-def]
        self.calls.append((tuple(argv), str(cwd)))
        return 0


# --------------------------------------------------------------------------- #
# unicode-path-audit
# --------------------------------------------------------------------------- #
def test_unicode_path_audit__audits_and_binds_unicode_path(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_unicode_space_repo(customers)
    assert " " in customer.name and any(ord(c) > 0x7F for c in customer.name)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    boundary = res.json["report"]["boundary"]
    assert boundary["customer_root"] == str(customer.resolve())
    assert res.json["report"]["binding"]["customer_sha"]


def test_unicode_path_audit__launch_argv_preserves_unicode_path(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_unicode_space_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    launch = res.json["launch"]
    # The space+Hangul path survives verbatim as a discrete argv element.
    assert launch["argv"][2] == str(customer.resolve())
    assert_settings_intact(launch, real_rapid7_root)


def test_unicode_path_audit__worktree_path_unicode_safe(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_unicode_space_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]
    worktree = customer.parent / f"{customer.name}.saena-worktrees" / run_id
    assert worktree.is_dir()
    assert " " in str(worktree) and any(ord(c) > 0x7F for c in str(worktree))
    assert build.porcelain(customer) == ""


# --------------------------------------------------------------------------- #
# malicious-quarantined
# --------------------------------------------------------------------------- #
def test_malicious_quarantined__injection_treated_as_data(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_malicious_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    rec = res.json["report"]["stricter_rules_reconciliation"]
    listed = {e["path"] for e in rec["rule_files"]}
    assert {"CLAUDE.md", "AGENTS.md"} <= listed
    for entry in rec["rule_files"]:
        assert entry["sha256"] and "size_bytes" in entry  # hashed, not interpreted
    assert "never executes or follows" in rec["policy"]
    # The injection text is DATA — it never appears in any pilot output/artifact.
    assert build.INJECTION_TEXT not in res.out
    assert build.INJECTION_TEXT not in _pilot_home_blob(pilot_home)
    # The launch is unaffected by the injected instructions.
    assert_settings_intact(res.json["launch"], real_rapid7_root)


def test_malicious_quarantined__planted_secret_absent_from_all_artifacts(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_malicious_repo(customers)
    assert (customer / ".env.leak").read_text(encoding="utf-8").find(build.SENTINEL_SECRET) >= 0
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK  # the planted file is never read → run succeeds
    assert build.SENTINEL_SECRET not in _pilot_home_blob(pilot_home)
    assert build.SENTINEL_SECRET not in res.out


def test_malicious_quarantined__secret_in_script_fails_closed(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_malicious_repo(customers, secret_in_script=True, name="hostile-script")
    res = start("audit", customer, "--dry-run")
    # A secret-shaped value that WOULD land in the report makes the pilot refuse
    # to write it — fail closed, never a leak.
    assert res.exit_code == EXIT_VALIDATION_FAILED
    # The value itself is withheld from the error (only the field path is shown).
    assert build.SENTINEL_SECRET not in res.err
    assert "secret-shaped" in res.err.lower() or "secret" in res.err.lower()


def test_malicious_quarantined__secret_never_in_evidence_on_failclosed(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_malicious_repo(customers, secret_in_script=True, name="hostile-script2")
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_VALIDATION_FAILED
    # Even the partial run store (events written before the refusal) is clean.
    assert build.SENTINEL_SECRET not in _pilot_home_blob(pilot_home)


# --------------------------------------------------------------------------- #
# docker-absent-honest  (PATH shim: git present, no docker binary)
# --------------------------------------------------------------------------- #
def test_docker_absent_honest__preflight_reports_docker_absent(
    real_rapid7_root, pilot_home, customers, build, path_without_docker
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("preflight", customer)
    assert res.exit_code == EXIT_OK
    docker = res.json["report"]["docker"]
    assert docker["cli_present"] is False
    assert docker["daemon_healthy"] is False
    assert "not found on PATH" in (docker["error_detail"] or "")


def test_docker_absent_honest__lane_still_runs_container_free(
    real_rapid7_root, pilot_home, customers, build, path_without_docker
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    # v1 pilot lanes are container-free: Docker absence must not block them.
    res = start("preflight", customer)
    assert res.exit_code == EXIT_OK
    assert (pilot_home / "pilot-runs" / res.json["run_id"] / "run.json").is_file()


def test_docker_absent_honest__no_false_container_verification(
    real_rapid7_root, pilot_home, customers, build, path_without_docker
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("preflight", customer)
    assert res.exit_code == EXIT_OK
    docker = res.json["report"]["docker"]
    # Never claims container-backed verification it did not perform.
    assert docker["container_verification_available"] is False
    assert docker["server_version"] is None
