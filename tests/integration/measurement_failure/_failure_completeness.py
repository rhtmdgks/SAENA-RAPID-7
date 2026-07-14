"""Authoritative manifest SSOT + completeness guard for the REQUIRED
failure-mode integration lane (Wave 5 MUST-FIX B — Required-Scenario
Completeness, mirrors ``tests/integration/_measurement_e2e_completeness.py``
EXACTLY for this lane).

Why this exists
---------------
The pre-existing required-mode guard (``measurement_failure/conftest.py``)
closes the *Docker-absent / all-skipped / zero-collected* fail-open: with
``SAENA_MEASUREMENT_FAILURE_REQUIRED`` armed, any skip in the collected set —
or zero passed, or zero collected — hard-fails (exit 6). But it inspects only
``session.items`` — the tests pytest actually SELECTED after ``-k`` /
``--deselect`` / single-node-path / ``PYTEST_ADDOPTS`` filtering. A caller who
selects a *subset* (even one real scenario) leaves the selected set fully
passing, so the lane went GREEN having run only a fraction of the required
failure-mode scenarios — a partial-selection / deselection fail-open (MUST-FIX
B; reproduced with a single-node ``-k`` selecting only
``test_fraud_did_scalar_is_zero_net_of_control_not_the_raw_movement``, with
``--deselect`` of a single node, and with ``PYTEST_ADDOPTS=-k ...`` — all
three exit 0 green against a 31-scenario required manifest).

The fix: an authoritative manifest of every required failure-mode scenario,
compared against what actually EXECUTED and PASSED. Any expected scenario
that was deselected, never collected, skipped, or did not pass is a HARD
FAILURE — the guard knows the *expected* set independently of the *selected*
set, so it cannot be shrunk by a selection option.

This is TEST-SUPPORT ONLY — never imported by any production/runtime package
(it lives under ``tests/`` and is imported only by ``tests/integration/
measurement_failure/conftest.py`` and this lane's guard self-tests). It
hardcodes no bare count comparison; the manifest is a set of semantic
scenario IDs + pytest node IDs + a category classification, and a drift
meta-test (in the guard self-tests) asserts the manifest node-id set equals
the actual collectible set (excluding the guard self-test module itself) in
BOTH directions — a renamed/removed test, or a new test absent from the
manifest, fails loudly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Scenario categories. "recovery" = replay/rollback/restart/rebuild rows;
#: "primary" = every other required failure-mode row. A required run must
#: exercise at least one of EACH category — dropping a whole category (e.g.
#: every recovery-shaped test) even while some scenarios still pass must
#: hard-fail.
CATEGORY_PRIMARY = "primary"
CATEGORY_RECOVERY = "recovery"
ALL_CATEGORIES: frozenset[str] = frozenset({CATEGORY_PRIMARY, CATEGORY_RECOVERY})

#: The required-mode arming env var (same contract as
#: measurement_failure/conftest._FAILURE_REQUIRED_ENV_VAR).
REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_FAILURE_REQUIRED"

#: Exit code for a required-lane HARD FAILURE (non-zero, non-5; matches the
#: sibling guards' hard-fail exit).
HARD_FAIL_EXIT = 6

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: This directory, repo-relative, as the node-id prefix every manifest entry
#: shares.
_THIS_MODULE_DIR = "tests/integration/measurement_failure"

#: Modules whose scenarios are "recovery" (replay/rollback/restart/rebuild) —
#: everything else in the manifest is "primary". ``test_f9_fraud_repoint.py``
#: is mixed: only its explicit replay node is "recovery", the rest "primary".
_RECOVERY_MODULES: frozenset[str] = frozenset(
    {
        "test_at_least_once_replay.py",
        "test_process_restart_rebuild.py",
        "test_clock_window_incomplete_restart.py",
        "test_conflicting_replay.py",
        "test_rollback_no_partial_state.py",
    }
)

#: The single "replay" node inside the otherwise-primary
#: ``test_f9_fraud_repoint.py`` module.
_F9_REPLAY_FUNC = "test_fraud_signal_replay_never_upgrades_to_pass"


@dataclass(frozen=True)
class RequiredScenario:
    """One required failure-mode scenario. ``scenario_id`` is a stable
    semantic name (survives node-path refactors); ``node_id`` is the exact
    pytest node id the guard matches against executed/passed items;
    ``category`` is ``"primary"`` or ``"recovery"``."""

    scenario_id: str
    node_id: str
    category: str = field(default=CATEGORY_PRIMARY)


def _scenario(module: str, func: str, scenario_id: str) -> RequiredScenario:
    node_id = f"{_THIS_MODULE_DIR}/{module}::{func}"
    is_f9_replay = module == "test_f9_fraud_repoint.py" and func == _F9_REPLAY_FUNC
    if module in _RECOVERY_MODULES or is_f9_replay:
        category = CATEGORY_RECOVERY
    else:
        category = CATEGORY_PRIMARY
    return RequiredScenario(scenario_id, node_id, category)


# --------------------------------------------------------------------------- #
# THE MANIFEST. Every required failure-mode integration scenario. Adding/
# removing/renaming a real failure-mode test REQUIRES a matching edit here —
# the drift meta-test enforces the equality in both directions, so the
# manifest can never silently under- or over-declare the actual suite.
# --------------------------------------------------------------------------- #
REQUIRED_SCENARIOS: tuple[RequiredScenario, ...] = (
    # --- at-least-once replay / duplicate delivery (3, recovery) ---
    _scenario(
        "test_at_least_once_replay.py",
        "test_duplicate_observations_within_a_signal_do_not_inflate_sample_counts",
        "duplicate-observations-no-inflate",
    ),
    _scenario(
        "test_at_least_once_replay.py",
        "test_duplicate_pipeline_runs_over_real_postgres_yield_single_outcome",
        "duplicate-pipeline-runs-single-outcome",
    ),
    _scenario(
        "test_at_least_once_replay.py",
        "test_validate_confirmation_duplicate_delivery_returns_duplicate_not_fresh_accepted",
        "duplicate-delivery-not-fresh-accepted",
    ),
    # --- clock window incomplete / restart (3, recovery) ---
    _scenario(
        "test_clock_window_incomplete_restart.py",
        "test_reevaluation_after_original_end_is_decidable_never_stuck_undetermined",
        "clock-reeval-after-end-decidable",
    ),
    _scenario(
        "test_clock_window_incomplete_restart.py",
        "test_reevaluation_before_window_end_is_undetermined_every_time",
        "clock-reeval-before-end-undetermined",
    ),
    _scenario(
        "test_clock_window_incomplete_restart.py",
        "test_window_state_is_derived_from_evaluation_at_not_wall_clock_reads",
        "clock-window-state-derived-not-wallclock",
    ),
    # --- conflicting replay (4, recovery) ---
    _scenario(
        "test_conflicting_replay.py",
        "test_confirmation_store_conflicting_content_fails_closed_first_wins",
        "conflicting-store-failclosed-first-wins",
    ),
    _scenario(
        "test_conflicting_replay.py",
        "test_evidence_bundle_content_addressed_collision_never_silently_resolved",
        "conflicting-evidence-collision-never-silent",
    ),
    _scenario(
        "test_conflicting_replay.py",
        "test_pipeline_conflicting_confirmation_replay_is_undetermined_never_pass",
        "conflicting-pipeline-replay-undetermined",
    ),
    _scenario(
        "test_conflicting_replay.py",
        "test_validate_confirmation_conflicting_content_is_rejected_not_arbitrary",
        "conflicting-validate-rejected-not-arbitrary",
    ),
    # --- F-9 fraud repoint (4: 3 primary + 1 recovery/replay) ---
    _scenario(
        "test_f9_fraud_repoint.py",
        "test_fraud_did_scalar_is_zero_net_of_control_not_the_raw_movement",
        "fraud-did-scalar-zero-net-of-control",
    ),
    _scenario(
        "test_f9_fraud_repoint.py",
        "test_fraud_signal_never_promoted_by_grs_eligibility_over_real_postgres",
        "fraud-never-promoted-by-grs-eligibility",
    ),
    _scenario(
        "test_f9_fraud_repoint.py",
        "test_fraud_signal_replay_never_upgrades_to_pass",
        "fraud-signal-replay-never-upgrades",
    ),
    _scenario(
        "test_f9_fraud_repoint.py",
        "test_fraud_signal_through_real_did_and_b_gate_never_passes",
        "fraud-through-real-did-and-b-gate-never-passes",
    ),
    # --- failure-mode coverage matrix (7, primary) ---
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_every_matrix_row_is_pytest_collectible",
        "matrix-every-row-collectible",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_every_matrix_row_test_exists_and_is_collectible",
        "matrix-every-row-exists-and-collectible",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_matrix_covers_at_least_thirteen_named_failure_modes",
        "matrix-covers-at-least-13-modes",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_no_duplicate_matrix_ids",
        "matrix-no-duplicate-ids",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_no_matrix_row_points_at_a_non_test_helper_module",
        "matrix-no-row-points-at-non-test-helper",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_real_postgres_matrix_rows_actually_ran_when_docker_is_available",
        "matrix-real-postgres-rows-actually-ran",
    ),
    _scenario(
        "test_failure_mode_coverage_matrix.py",
        "test_undetermined_or_fail_rows_assert_status_is_never_pass",
        "matrix-undetermined-or-fail-never-pass",
    ),
    # --- missing baseline / DiD insufficiency (3, primary) ---
    _scenario(
        "test_missing_baseline_did_insufficiency.py",
        "test_missing_baseline_all_signals_is_undetermined_not_a_crash",
        "missing-baseline-all-signals-undetermined",
    ),
    _scenario(
        "test_missing_baseline_did_insufficiency.py",
        "test_missing_baseline_did_scalar_is_insufficient_not_a_silent_zero",
        "missing-baseline-did-scalar-insufficient",
    ),
    _scenario(
        "test_missing_baseline_did_insufficiency.py",
        "test_missing_baseline_is_insufficient_never_a_silent_zero",
        "missing-baseline-insufficient-never-silent-zero",
    ),
    # --- observation adapter drift (3, primary) ---
    _scenario(
        "test_observation_adapter_drift.py",
        "test_conversion_is_not_a_constructable_outcome_layer",
        "adapter-conversion-not-constructable-outcome",
    ),
    _scenario(
        "test_observation_adapter_drift.py",
        "test_pipeline_all_signals_drifted_is_undetermined_not_a_crash",
        "adapter-all-signals-drifted-undetermined",
    ),
    _scenario(
        "test_observation_adapter_drift.py",
        "test_pipeline_out_of_vocabulary_layer_signal_is_undetermined_adapter_drift",
        "adapter-out-of-vocabulary-undetermined",
    ),
    # --- process restart / rebuild (2, recovery) ---
    _scenario(
        "test_process_restart_rebuild.py",
        "test_confirmation_journal_replay_rebuilds_byte_identical_state",
        "restart-journal-replay-byte-identical",
    ),
    _scenario(
        "test_process_restart_rebuild.py",
        "test_rebuild_from_real_postgres_after_simulated_restart_is_identical",
        "restart-rebuild-from-postgres-identical",
    ),
    # --- rollback / no partial state (2, recovery) ---
    _scenario(
        "test_rollback_no_partial_state.py",
        "test_conflicting_append_decision_leaves_no_partial_state",
        "rollback-conflicting-append-no-partial-state",
    ),
    _scenario(
        "test_rollback_no_partial_state.py",
        "test_pipeline_conflicting_decision_replay_leaves_original_outcome_untouched",
        "rollback-pipeline-replay-original-untouched",
    ),
)

EXPECTED_NODE_IDS: frozenset[str] = frozenset(s.node_id for s in REQUIRED_SCENARIOS)
EXPECTED_SCENARIO_IDS: frozenset[str] = frozenset(s.scenario_id for s in REQUIRED_SCENARIOS)


def failure_required_armed() -> bool:
    """Fail-SAFE arming: any non-empty value other than an explicit disable
    (``0``/``false``/``no``/``off``) arms required mode (parity with
    ``measurement_failure/conftest._failure_required_armed`` and
    ``_measurement_e2e_completeness.required_armed``)."""
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
    executed_primary: int
    executed_recovery: int
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return not self.reasons


def evaluate(passed: set[str], skipped: set[str], failed: set[str]) -> CompletenessReport:
    """Compare the manifest against the actual passed/skipped/failed node sets
    (each recorded by a ``pytest_runtest_logreport`` recorder). Returns a
    report whose ``reasons`` is non-empty iff the required lane must HARD
    FAIL. Node-id SETS are compared throughout — never a bare count — so a
    caller cannot satisfy the guard by running any 31 tests, only by running
    exactly the manifest's 31 required scenarios."""
    passed_n = {_norm(n) for n in passed}
    skipped_n = {_norm(n) for n in skipped}
    failed_n = {_norm(n) for n in failed}

    expected = EXPECTED_NODE_IDS
    exp_passed = expected & passed_n
    exp_skipped = expected & skipped_n
    exp_failed = expected & failed_n
    executed = exp_passed | exp_skipped | exp_failed
    missing = expected - passed_n  # anything not observed as PASSED

    executed_primary = 0
    executed_recovery = 0
    for s in REQUIRED_SCENARIOS:
        if s.node_id in exp_passed:
            if s.category == CATEGORY_RECOVERY:
                executed_recovery += 1
            else:
                executed_primary += 1

    reasons: list[str] = []
    if not expected:
        reasons.append("required failure-mode manifest is EMPTY (SSOT lost)")
    if missing:
        # deselected / never-collected / skipped / failed — all are "did not
        # complete as a pass", the exact partial-selection fail-open.
        sample = ", ".join(sorted(missing)[:8])
        more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
        reasons.append(
            f"{len(missing)} of {len(expected)} REQUIRED failure-mode scenario(s) did not "
            f"execute-and-PASS (deselected / not collected / skipped / failed): "
            f"{sample}{more}"
        )
    if executed_primary == 0:
        reasons.append(
            "ZERO 'primary' required failure-mode scenarios executed-and-PASSED — "
            "a required run must exercise at least one primary scenario"
        )
    if executed_recovery == 0:
        reasons.append(
            "ZERO 'recovery' (replay/rollback/restart/rebuild) required failure-mode "
            "scenarios executed-and-PASSED — a required run must exercise at least "
            "one recovery scenario"
        )
    return CompletenessReport(
        expected=expected,
        passed=frozenset(exp_passed),
        skipped=frozenset(exp_skipped),
        failed=frozenset(exp_failed),
        executed=frozenset(executed),
        missing=frozenset(missing),
        executed_primary=executed_primary,
        executed_recovery=executed_recovery,
        reasons=reasons,
    )


def format_failure(report: CompletenessReport) -> str:
    sep = "\n  - "
    return (
        f"\n{REQUIRED_ENV_VAR} HARD FAILURE (exit {HARD_FAIL_EXIT}) — "
        f"required-scenario completeness:{sep}"
        + sep.join(report.reasons)
        + f"\n  expected={len(report.expected)} passed={len(report.passed)} "
        f"skipped={len(report.skipped)} failed={len(report.failed)} "
        f"missing={len(report.missing)} | "
        f"primary_executed={report.executed_primary} recovery_executed={report.executed_recovery}"
        "\n  A required failure-mode run must execute-and-PASS EVERY manifest "
        "scenario across both categories — a partial `-k`/`--deselect`/"
        "single-node/PYTEST_ADDOPTS selection can never make it green. Run the "
        "full `just measurement-failure-modes` gate, or invoke without "
        f"{REQUIRED_ENV_VAR} for the optional/local lane."
    )
