"""Shared fixtures + REQUIRED-mode completeness guard for the pilot E2E lane
(w6-14, mission W6-26).

Two responsibilities:

1. **Fixtures.** Every run drives the REAL ``saena-pilot`` CLI against the REAL
   RAPID-7 root (this worktree) so the genuine 16-skill bundle gate runs and its
   fingerprint binds into evidence. Customer repos are SYNTHETIC, built in
   ``tmp_path`` via real ``git init`` (never committed into RAPID-7).
   ``SAENA_PILOT_HOME`` is redirected into ``tmp_path`` and a PATH-stub
   ``claude`` captures any non-dry-run launch so Claude Code is never really
   started.

2. **Required-mode guard** (Wave-5 pattern, container-free adaptation — "required
   container" becomes "required scenario"). ``SAENA_PILOT_E2E_REQUIRED`` arms it
   fail-safe. ``pytest_collection_finish`` errors on zero-collected-while-armed
   and on a selection that does not cover the manifest (so a partial ``-k`` exits
   nonzero). ``pytest_sessionfinish`` upgrades a false-green (armed, but a
   required scenario was skipped/failed/missing, or zero passed) to a HARD exit
   6. The guard's own teeth are proven by container-free subprocess self-tests in
   ``test_completeness_guard.py`` (a META module, exempt from the accounting).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _THIS_DIR / "fixtures"
_REPO_ROOT = _THIS_DIR.parents[2]
_PILOT_SRC = _REPO_ROOT / "tools" / "saena-pilot" / "src"

for _p in (_THIS_DIR, _FIXTURES_DIR, _PILOT_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _e2e_customer_builders as builders  # noqa: E402
from _e2e_manifest import (  # noqa: E402
    DUMP_ENV_VAR,
    EXPECTED_SCENARIO_IDS,
    HARD_FAIL_EXIT,
    REQUIRED_ENV_VAR,
    evaluate,
    format_failure,
    is_meta_node,
    required_armed,
    scenario_for_node,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def real_rapid7_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """The ACTUAL RAPID-7 worktree root, with cwd pinned there so the pilot
    resolves it and enforces the real skill bundle. Verified to carry the real
    manifest so real-root runs pass the bundle gate."""
    manifest = _REPO_ROOT / ".claude" / "skills" / "manifest.json"
    assert manifest.is_file(), f"real skill manifest missing at {manifest}"
    monkeypatch.chdir(_REPO_ROOT)
    return _REPO_ROOT


@pytest.fixture
def pilot_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """SAENA_PILOT_HOME redirected under tmp_path — run metadata lands here,
    never in either repo."""
    home = tmp_path / "pilot-home"
    monkeypatch.setenv("SAENA_PILOT_HOME", str(home))
    return home


@pytest.fixture
def customers(tmp_path: Path) -> Path:
    """A base dir (outside both repos) under which fixture customer repos are
    built."""
    base = tmp_path / "customers"
    base.mkdir()
    return base


@pytest.fixture
def build():  # noqa: ANN201 - returns the builders module for direct use
    """The synthetic customer-repo builders module."""
    return builders


@pytest.fixture
def complete_intake(tmp_path: Path) -> Path:
    """An intake file that completes the action contract (unblocks plan/implement)."""
    intake = {
        "customer_id": "tenant-e2e-01",
        "allowed_write_scope": ["app/**", "src/**"],
        "protected_paths": [".github/**", "deploy/**", "package-lock.json"],
        "build_commands": ["npm run build"],
        "test_commands": "auto-detect-pending",
        "deployment_responsibility": "human",
        "data_classification": "confidential",
        "observation_authorization": {"authorized": True, "owner": "Pilot Owner"},
    }
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(intake, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A recording ``claude`` on PATH — proves a non-dry-run launch is captured
    and never really starts Claude Code. Returns the marker file it writes."""
    bin_dir = tmp_path / "stub-bin"
    marker = tmp_path / "claude-invocations.txt"
    builders.make_claude_stub(bin_dir, marker)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return marker


@pytest.fixture
def path_without_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PATH stub with git + a recording claude but NO docker binary — makes
    Docker-absence deterministic even on a Docker-equipped host. Returns the
    claude marker file."""
    bin_dir = tmp_path / "nodocker-bin"
    marker = tmp_path / "claude-invocations.txt"
    path_value = builders.make_path_without_docker(bin_dir, marker)
    monkeypatch.setenv("PATH", path_value)
    return marker


# --------------------------------------------------------------------------- #
# Required-mode completeness guard
# --------------------------------------------------------------------------- #

_OUTCOMES: dict[str, set[str]] = {"passed": set(), "skipped": set(), "failed": set()}
_COLLECTED: set[str] = set()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e_pilot: end-to-end pilot lifecycle scenario (w6-14). Completeness is "
        "gated by SAENA_PILOT_E2E_REQUIRED via the manifest SSOT, not by this marker.",
    )
    # Reset module-level recorders (a second in-process session — e.g. the guard
    # self-tests spawn subprocesses, but be defensive about re-entry).
    _OUTCOMES["passed"].clear()
    _OUTCOMES["skipped"].clear()
    _OUTCOMES["failed"].clear()
    _COLLECTED.clear()


def _this_dir_items(session: pytest.Session) -> list[pytest.Item]:
    return [
        item
        for item in session.items
        if _THIS_DIR in Path(str(item.fspath)).resolve().parents
        or Path(str(item.fspath)).resolve().parent == _THIS_DIR
    ]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Runs ONCE after collection is fully complete — after every ``-k``/``-m``
    deselection, and even on an EMPTY selection. Records the collected node ids,
    optionally dumps them (for the drift meta-test's independent collection), and
    — when armed — errors on zero collection or on a selection that does not
    cover the manifest (so a partial ``-k`` exits nonzero)."""
    items = _this_dir_items(session)
    _COLLECTED.clear()
    _COLLECTED.update(item.nodeid for item in items)

    dump_target = os.environ.get(DUMP_ENV_VAR)
    if dump_target:
        Path(dump_target).write_text(
            json.dumps(sorted(_COLLECTED), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if not required_armed():
        return

    if not items:
        raise pytest.UsageError(
            "tests/e2e/pilot collected ZERO test items while "
            f"{REQUIRED_ENV_VAR} is armed — this is the REQUIRED pilot-E2E lane; zero "
            "collection is a HARD FAILURE (a naming typo, a -k/-m mismatch, or an "
            "import/collection error must never look like an honest pass)."
        )

    covered = {
        scenario_for_node(item.nodeid)
        for item in items
        if not is_meta_node(item.nodeid) and scenario_for_node(item.nodeid) is not None
    }
    missing = EXPECTED_SCENARIO_IDS - covered
    if missing:
        raise pytest.UsageError(
            f"{REQUIRED_ENV_VAR} is armed but the SELECTED tests do not cover the "
            f"required-scenario manifest — missing {len(missing)} scenario(s): "
            f"{', '.join(sorted(missing))}. A required run must exercise EVERY scenario; "
            "a partial -k/-m/--deselect/single-node selection can never make it green. "
            f"Run the full lane, or drop {REQUIRED_ENV_VAR} for the local lane."
        )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    # A setup-phase skip surfaces at when=="setup"; a pass/fail at when=="call".
    if report.when == "setup" and report.outcome == "skipped":
        _OUTCOMES["skipped"].add(report.nodeid)
    elif report.when == "call":
        _OUTCOMES.setdefault(report.outcome, set()).add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """When armed, upgrade a FALSE-GREEN to a HARD failure: if any required
    scenario was skipped, failed, or never collected — or zero passed — set exit
    6. Only ever turns a would-be-GREEN run RED (never clobbers an existing
    non-zero exit), so a genuine test failure keeps its own exit code."""
    if not required_armed():
        return
    report = evaluate(
        collected=set(_COLLECTED),
        passed=_OUTCOMES["passed"],
        skipped=_OUTCOMES["skipped"],
        failed=_OUTCOMES["failed"],
    )
    if report.ok:
        return
    # Preserve an existing failure/usage-error exit; only upgrade a green run.
    if int(exitstatus) == 0:
        session.exitstatus = HARD_FAIL_EXIT
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(format_failure(report), red=True)
