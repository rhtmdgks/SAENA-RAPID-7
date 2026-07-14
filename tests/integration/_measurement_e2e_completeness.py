"""Authoritative manifest SSOT + completeness guard for the REQUIRED composed
measurement E2E lane (Wave 5 Closure — Required-Scenario Completeness).

Why this exists
---------------
The pre-existing required-mode guards (``measurement_e2e/conftest.py`` and
``measurement_failure/conftest.py``) close *Docker-absent / all-skipped /
zero-collected* fail-open: with the required env armed, any skip or zero-pass in
the SELECTED set hard-fails (exit 6). But they inspect only ``session.items`` —
the tests pytest actually SELECTED after ``-k`` / ``-m`` / ``--deselect`` /
single-node-path / ``PYTEST_ADDOPTS`` filtering. A caller who selects a
*subset* (even one real scenario) leaves the selected set fully passing, so the
lane went GREEN having run only a fraction of the required scenarios — a
partial-selection / deselection fail-open (reproduced at b44f3b5).

The fix: an authoritative manifest of every required E2E scenario, compared
against what actually EXECUTED and PASSED. Any expected scenario that was
deselected, never collected, skipped, or did not pass is a HARD FAILURE — the
guard knows the *expected* set independently of the *selected* set, so it cannot
be shrunk by a selection option.

This is TEST-SUPPORT ONLY — never imported by any production/runtime package
(it lives under ``tests/`` and is imported only by ``tests/integration/
conftest.py`` and the E2E guard self-tests). It hardcodes no count; the
manifest is a set of semantic scenario IDs + pytest node IDs + backend legs,
and a drift meta-test (in the guard self-tests) asserts the manifest set equals
the actual collectible set in BOTH directions (a renamed/removed test, or a new
test absent from the manifest, fails loudly).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Backend legs. A required E2E run must exercise EVERY leg — dropping the whole
# Temporal directory (path omission) or the whole composed directory must
# hard-fail even though every SELECTED test passed.
# --------------------------------------------------------------------------- #
LEG_POSTGRES = "postgres"
LEG_CLICKHOUSE = "clickhouse"
LEG_TEMPORAL = "temporal"
LEG_COMPOSED = "composed"
ALL_LEGS: frozenset[str] = frozenset({LEG_POSTGRES, LEG_CLICKHOUSE, LEG_TEMPORAL, LEG_COMPOSED})

#: The required-mode arming env var (same contract as measurement_e2e/conftest).
REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_E2E_REQUIRED"

#: Exit code for a required-lane HARD FAILURE (non-zero, non-5; matches the
#: sibling guards' _HARD_FAIL_EXIT).
HARD_FAIL_EXIT = 6

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The two test modules that make up the composed E2E lane, as repo-relative
# node-id prefixes. The composed module exercises real Postgres 16 + ClickHouse
# 24.8 through the actual `run_measurement` composition; the workflow module
# exercises the real Temporal time-skipping test server.
_COMPOSED_MODULE = "tests/integration/measurement_e2e/test_real_composed_measurement_e2e.py"
_WORKFLOW_MODULE = "tests/integration/measurement_workflow/test_measurement_workflow.py"

# Leg tags are the container/infrastructure dependency of the module: the
# composed harness spins up BOTH Postgres and ClickHouse and drives the full
# pipeline, so every composed node exercises {postgres, clickhouse, composed};
# every workflow node exercises {temporal}. This is a conservative
# infrastructure-leg classification (not a per-assertion claim).
_COMPOSED_LEGS: frozenset[str] = frozenset({LEG_POSTGRES, LEG_CLICKHOUSE, LEG_COMPOSED})
_WORKFLOW_LEGS: frozenset[str] = frozenset({LEG_TEMPORAL})


@dataclass(frozen=True)
class RequiredScenario:
    """One required E2E scenario. ``scenario_id`` is a stable semantic name
    (survives node-path refactors); ``node_id`` is the exact pytest node id the
    guard matches against executed/passed items; ``legs`` is the backend legs
    it exercises."""

    scenario_id: str
    node_id: str
    legs: frozenset[str] = field(default_factory=frozenset)


def _composed(func: str, scenario_id: str) -> RequiredScenario:
    return RequiredScenario(scenario_id, f"{_COMPOSED_MODULE}::{func}", _COMPOSED_LEGS)


def _workflow(func: str, scenario_id: str) -> RequiredScenario:
    return RequiredScenario(scenario_id, f"{_WORKFLOW_MODULE}::{func}", _WORKFLOW_LEGS)


# --------------------------------------------------------------------------- #
# THE MANIFEST. Every required composed-E2E scenario. Adding/removing/renaming a
# real E2E test REQUIRES a matching edit here — the drift meta-test enforces the
# equality in both directions, so the manifest can never silently under- or
# over-declare the actual suite.
# --------------------------------------------------------------------------- #
REQUIRED_SCENARIOS: tuple[RequiredScenario, ...] = (
    # --- composed PG + ClickHouse leg (19) ---
    _composed("test_full_pass_flow_b_verified_skill_intake_accepted", "full-pass-flow"),
    _composed("test_one_qualifying_layer_not_pass_intake_denied", "one-layer-not-pass"),
    _composed("test_missing_grs_fails_closed_never_pass", "missing-grs-failclosed"),
    _composed("test_invalid_grs_deny_bundle_fails_closed_never_pass", "invalid-grs-failclosed"),
    _composed("test_day2_late_deployment_undetermined_clock_not_started", "day2-clock-not-started"),
    _composed(
        "test_day2_late_deployment_via_temporal_timer_never_starts", "day2-timer-never-starts"
    ),
    _composed("test_crash_replay_during_timer_preserves_original_window", "crash-replay-window"),
    _composed("test_duplicate_identical_confirmation_is_idempotent", "duplicate-idempotent"),
    _composed(
        "test_conflicting_confirmation_undetermined_first_record_unchanged",
        "conflicting-undetermined",
    ),
    _composed(
        "test_non_conflict_store_errors_still_propagate_against_real_pg",
        "store-errors-propagate",
    ),
    _composed("test_cross_tenant_read_denied_no_existence_oracle", "cross-tenant-read-denied"),
    _composed("test_cross_tenant_write_replay_rejected", "cross-tenant-write-rejected"),
    _composed("test_evidence_tamper_detected_on_readback_no_promotion", "evidence-tamper-detected"),
    _composed(
        "test_secret_sentinel_absent_from_evidence_and_persistence_rows",
        "secret-absent-rows",
    ),
    _composed(
        "test_secret_sentinel_absent_from_conflicting_confirmation_reason_codes",
        "secret-absent-reasoncodes",
    ),
    _composed("test_secret_sentinel_absent_from_raised_exception_strings", "secret-absent-exc"),
    _composed("test_zero_common_trend_effect_never_falsely_promoted", "zero-trend-not-promoted"),
    _composed(
        "test_outcome_publisher_refuses_forged_pass_without_qualifying_layers",
        "publisher-refuses-forged",
    ),
    _composed(
        "test_successful_path_physical_persistence_subsequent_real_reads",
        "physical-persistence-reads",
    ),
    # --- Temporal leg (9) ---
    _workflow("test_full_flow_signal_window_skip_to_decided_outcome", "wf-full-flow-decided"),
    _workflow("test_worker_restart_midwindow_timer_continues_not_reset", "wf-worker-restart"),
    _workflow("test_duplicate_deployment_signal_is_idempotent_no_restart", "wf-duplicate-signal"),
    _workflow("test_abort_midwindow_yields_undetermined_aborted", "wf-abort-undetermined"),
    _workflow("test_day2_late_deployment_never_starts_timer", "wf-day2-no-timer"),
    _workflow(
        "test_conflicting_confirmation_records_replay_and_keeps_original_window",
        "wf-conflicting-replay",
    ),
    _workflow("test_pause_holds_decision_past_window_end_until_resume", "wf-pause-resume"),
    _workflow("test_timezone_independence_anchor_at_dst_boundary", "wf-tz-independence"),
    _workflow(
        "test_confirmation_for_wrong_registration_is_refused_never_binds",
        "wf-wrong-registration",
    ),
)

EXPECTED_NODE_IDS: frozenset[str] = frozenset(s.node_id for s in REQUIRED_SCENARIOS)
EXPECTED_SCENARIO_IDS: frozenset[str] = frozenset(s.scenario_id for s in REQUIRED_SCENARIOS)


def required_armed() -> bool:
    """Fail-SAFE arming: any non-empty value other than an explicit disable
    (``0``/``false``/``no``/``off``) arms required mode (parity with
    ``measurement_e2e/conftest._required_armed``)."""
    raw = os.environ.get(REQUIRED_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _norm(node_id: str) -> str:
    """Normalize a pytest node id to the repo-relative form the manifest uses.
    pytest reports node ids relative to rootdir (the repo root here), but a
    caller who passes an absolute path or runs from a subdir can yield a
    different prefix; normalize both to the repo-relative POSIX path."""
    path_part, sep, rest = node_id.partition("::")
    try:
        p = Path(path_part)
        if p.is_absolute():
            path_part = p.resolve().relative_to(_REPO_ROOT).as_posix()
        else:
            # collapse any leading "./" and resolve against repo root
            path_part = (_REPO_ROOT / p).resolve().relative_to(_REPO_ROOT).as_posix()
    except (ValueError, OSError):
        path_part = path_part.lstrip("./")
    return f"{path_part}{sep}{rest}"


@dataclass
class CompletenessReport:
    expected: frozenset[str]
    passed: frozenset[str]
    skipped: frozenset[str]
    failed: frozenset[str]
    executed: frozenset[str]  # passed | failed | skipped that are expected
    missing: frozenset[str]  # expected - passed  (deselected/uncollected/skip/fail)
    legs_executed: dict[str, int]
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return not self.reasons


def evaluate(passed: set[str], skipped: set[str], failed: set[str]) -> CompletenessReport:
    """Compare the manifest against the actual passed/skipped/failed node sets
    (each recorded by a ``pytest_runtest_logreport`` recorder). Returns a report
    whose ``reasons`` is non-empty iff the required lane must HARD FAIL."""
    passed_n = {_norm(n) for n in passed}
    skipped_n = {_norm(n) for n in skipped}
    failed_n = {_norm(n) for n in failed}

    expected = EXPECTED_NODE_IDS
    exp_passed = expected & passed_n
    exp_skipped = expected & skipped_n
    exp_failed = expected & failed_n
    executed = exp_passed | exp_skipped | exp_failed
    missing = expected - passed_n  # anything not observed as PASSED

    legs_executed: dict[str, int] = {leg: 0 for leg in ALL_LEGS}
    for s in REQUIRED_SCENARIOS:
        if s.node_id in exp_passed:
            for leg in s.legs:
                legs_executed[leg] += 1

    reasons: list[str] = []
    if not expected:
        reasons.append("required E2E manifest is EMPTY (SSOT lost)")
    if missing:
        # deselected / never-collected / skipped / failed — all are "did not
        # complete as a pass", the exact partial-selection fail-open.
        sample = ", ".join(sorted(missing)[:8])
        more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
        reasons.append(
            f"{len(missing)} of {len(expected)} REQUIRED E2E scenario(s) did not "
            f"execute-and-PASS (deselected / not collected / skipped / failed): "
            f"{sample}{more}"
        )
    for leg in sorted(ALL_LEGS):
        if legs_executed[leg] == 0:
            reasons.append(
                f"ZERO required E2E tests executed for the '{leg}' backend leg — "
                "a required run must exercise every backend leg "
                "(Postgres / ClickHouse / Temporal / composed)"
            )
    return CompletenessReport(
        expected=expected,
        passed=frozenset(exp_passed),
        skipped=frozenset(exp_skipped),
        failed=frozenset(exp_failed),
        executed=frozenset(executed),
        missing=frozenset(missing),
        legs_executed=legs_executed,
        reasons=reasons,
    )


def format_failure(report: CompletenessReport) -> str:
    sep = "\n  - "
    legs = ", ".join(f"{k}={report.legs_executed[k]}" for k in sorted(ALL_LEGS))
    return (
        f"\n{REQUIRED_ENV_VAR} HARD FAILURE (exit {HARD_FAIL_EXIT}) — "
        f"required-scenario completeness:{sep}"
        + sep.join(report.reasons)
        + f"\n  expected={len(report.expected)} passed={len(report.passed)} "
        f"skipped={len(report.skipped)} failed={len(report.failed)} "
        f"missing={len(report.missing)} | legs[{legs}]"
        "\n  A required composed-E2E run must execute-and-PASS EVERY manifest "
        "scenario across all backend legs — a partial `-k`/`-m`/`--deselect`/"
        "single-node/PYTEST_ADDOPTS selection can never make it green. Run the "
        "full `just measurement-e2e` gate, or invoke without "
        f"{REQUIRED_ENV_VAR} for the optional/local lane."
    )
