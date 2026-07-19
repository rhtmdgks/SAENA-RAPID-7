"""E2E: framework discovery + read-mode safety for Next.js, static HTML, and
unsupported (WordPress/PHP) customer repos.

Scenario keys: ``nextjs_audit``, ``static_audit``, ``unsupported_reportonly``.
"""

from __future__ import annotations

from pathlib import Path

from _e2e_run import assert_settings_intact, start
from saena_pilot.cli import EXIT_OK

_TRANSIENT_ARTIFACTS = (
    "coverage.xml",
    ".coverage",
    ".pytest_cache",
    "__pycache__",
    ".devcontainer/devcontainer-lock.json",
)


def _filter_transient(porcelain: str) -> str:
    """Drop lines for test-harness build artifacts (coverage data files, caches,
    the pre-existing untracked devcontainer lockfile) that the FULL `just verify`
    run legitimately creates at the repo root — they are NOT customer copies and
    would otherwise make the before/after RAPID-7 delta spuriously non-empty."""
    kept = []
    for line in porcelain.splitlines():
        path = line[3:] if len(line) > 3 else line
        if any(marker in path for marker in _TRANSIENT_ARTIFACTS):
            continue
        kept.append(line)
    return "\n".join(kept)


def _rapid7_porcelain(build, root: Path) -> str:  # noqa: ANN001
    return _filter_transient(build.run_git(root, "status", "--porcelain").stdout)


# --------------------------------------------------------------------------- #
# nextjs-audit
# --------------------------------------------------------------------------- #
def test_nextjs_audit__discovery_supported_with_routes(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    disc = res.json["report"]["discovery"]
    assert disc["framework"] == "nextjs"
    assert disc["status"] == "SUPPORTED"
    assert disc["routes"], "expected app/ routes to be discovered"
    assert disc["package_manager"] == "npm"  # package-lock.json present


def test_nextjs_audit__test_command_reported_verbatim(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("preflight", customer)
    assert res.exit_code == EXIT_OK
    disc = res.json["report"]["discovery"]
    # The pilot REPORTS discovered commands verbatim — it never runs them.
    assert disc["test_command"] == build.NEXTJS_TEST_COMMAND
    assert disc["build_command"] == build.NEXTJS_BUILD_COMMAND
    assert disc["lint_command"] == build.NEXTJS_LINT_COMMAND


def test_nextjs_audit__launch_attaches_customer_root_readonly(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    launch = res.json["launch"]
    # Read mode attaches the customer ROOT (never a worktree); settings intact.
    assert launch["argv"] == ["claude", "--add-dir", str(customer.resolve())]
    assert_settings_intact(launch, real_rapid7_root)


def test_nextjs_audit__non_dry_run_launch_captured_by_stub(
    real_rapid7_root, pilot_home, customers, build, stub_claude
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer)  # NOT dry-run → default runner → stub claude
    assert res.exit_code == EXIT_OK
    assert res.json["launch_exit"] == 0
    # The PATH-stub claude captured the launch — Claude Code was never started.
    captured = stub_claude.read_text(encoding="utf-8")
    assert "--add-dir" in captured
    assert str(customer.resolve()) in captured


def test_nextjs_audit__zero_writes_to_customer_and_rapid7(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    r7_before = _rapid7_porcelain(build, real_rapid7_root)
    for mode in ("preflight", "audit"):
        extra = ("--dry-run",) if mode == "audit" else ()
        assert start(mode, customer, *extra).exit_code == EXIT_OK
        assert build.porcelain(customer) == ""  # zero customer writes
    assert _rapid7_porcelain(build, real_rapid7_root) == r7_before


# --------------------------------------------------------------------------- #
# static-audit
# --------------------------------------------------------------------------- #
def test_static_audit__discovery_supported_static_html(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_static_html_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    disc = res.json["report"]["discovery"]
    assert disc["framework"] == "static-html"
    assert disc["status"] == "SUPPORTED"


def test_static_audit__no_package_json_no_writes(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_static_html_repo(customers)
    assert not (customer / "package.json").exists()
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    assert build.porcelain(customer) == ""
    disc = res.json["report"]["discovery"]
    # No build/test commands to report — honestly None, never guessed.
    assert disc["build_command"] is None
    assert disc["test_command"] is None


def test_static_audit__launch_and_evidence_ok(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_static_html_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    assert_settings_intact(res.json["launch"], real_rapid7_root)
    run_dir = pilot_home / "pilot-runs" / res.json["run_id"]
    assert (run_dir / "events.jsonl").is_file()


# --------------------------------------------------------------------------- #
# unsupported-reportonly
# --------------------------------------------------------------------------- #
def test_unsupported_reportonly__wordpress_reported_not_written(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_unsupported_repo(customers, flavor="wordpress")
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    disc = res.json["report"]["discovery"]
    assert disc["framework"] == "wordpress"
    assert disc["status"] == "UNSUPPORTED"
    assert "report-only" in disc["detail"].lower()
    assert build.porcelain(customer) == ""  # report-only: zero writes


def test_unsupported_reportonly__bare_php_reported(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_unsupported_repo(customers, flavor="php", name="php-site")
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    disc = res.json["report"]["discovery"]
    assert disc["framework"] == "php"
    assert disc["status"] == "UNSUPPORTED"


def test_unsupported_reportonly__audit_completes_readonly(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_unsupported_repo(customers, flavor="wordpress")
    r7_before = _rapid7_porcelain(build, real_rapid7_root)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    # Unsupported ≠ blocked: the read-only audit still completes and records a run.
    assert (pilot_home / "pilot-runs" / res.json["run_id"] / "run.json").is_file()
    assert _rapid7_porcelain(build, real_rapid7_root) == r7_before
