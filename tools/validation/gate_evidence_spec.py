"""Authoritative EXPECTED-shape SSOT for the measurement-gate evidence
validator (Wave 5 Closure — strict evidence validation).

Pure data, ZERO imports of test-support/runtime packages, so
``render_gate_evidence.py`` can import it in any environment (CI job step,
local) without pulling pytest/testcontainers. The numbers here are the
manifest-derived expectations; a drift test
(``tests/unit/gate_evidence/test_spec_matches_manifest.py``) asserts they equal
the live test manifests (``tests/integration/_measurement_e2e_completeness.py``
+ ``_failure_completeness.py``), so this SSOT can never silently diverge from
what the gates actually require — no magic number is duplicated without a guard.

Distinction the validator enforces (documented once, here):

- ``expected_count`` is the REQUIRED-SCENARIO count (28 E2E / 31 failure).
- The gate's total pytest pass count is higher because it ALSO runs the
  guard/meta self-tests (in ``authorized_unexpected_files``). Those legitimately
  appear in the evidence's ``unexpected_node_ids`` but may NEVER substitute for
  a required manifest node — the validator requires ``missing_node_ids == []``
  independently, and requires every unexpected node to live in an authorized
  guard/meta file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "saena.gate-evidence/v1"


@dataclass(frozen=True)
class GateSpec:
    #: required-scenario (manifest) count — NOT the total pytest pass count.
    expected_count: int
    #: per-leg expected executed==passed count (manifest-derived).
    leg_expected: dict[str, int]
    #: legs that MUST carry a real-container/test-server runtime witness.
    required_witness_legs: tuple[str, ...]
    #: leg -> required image/server-identity prefix (approved family).
    witness_image_prefix: dict[str, str]
    #: witness legs whose container_id must be a nonempty, container-id-shaped
    #: string (a real Docker container). Temporal's in-process test server is
    #: exempt (it has no docker container id).
    container_id_required_legs: tuple[str, ...]
    #: repo-relative test files whose nodes may legitimately appear in
    #: unexpected_node_ids (the gate's guard/meta self-tests). Any unexpected
    #: node from any OTHER file is unauthorized -> fail closed. File-level (not
    #: a permissive name prefix).
    authorized_unexpected_files: tuple[str, ...]
    #: 'composed' logical leg (proven by postgres AND clickhouse witnesses).
    has_composed_leg: bool = False
    #: failure-mode primary/recovery split (0 when N/A).
    has_primary_recovery: bool = False
    primary_expected: int = 0
    recovery_expected: int = 0
    #: failure-mode: every required node runs against real Postgres.
    postgres_scenarios: int = 0
    #: legs the payload's `legs` block must contain (superset of witness legs;
    #: includes the logical 'composed' leg for e2e).
    all_legs: tuple[str, ...] = field(default_factory=tuple)


SPEC: dict[str, GateSpec] = {
    "e2e": GateSpec(
        expected_count=28,
        leg_expected={"postgres": 19, "clickhouse": 19, "composed": 19, "temporal": 9},
        required_witness_legs=("postgres", "clickhouse", "temporal"),
        witness_image_prefix={
            "postgres": "postgres:16",
            "clickhouse": "clickhouse/clickhouse-server:24.8",
            "temporal": "temporalio",
        },
        container_id_required_legs=("postgres", "clickhouse"),
        authorized_unexpected_files=(
            "tests/integration/measurement_e2e/test_zero_collected_guard.py",
        ),
        has_composed_leg=True,
        all_legs=("clickhouse", "composed", "postgres", "temporal"),
    ),
    "failure-modes": GateSpec(
        expected_count=31,
        leg_expected={"postgres": 31},
        required_witness_legs=("postgres",),
        witness_image_prefix={"postgres": "postgres:16"},
        container_id_required_legs=("postgres",),
        authorized_unexpected_files=(
            "tests/integration/measurement_failure/test_failure_required_guard.py",
        ),
        has_primary_recovery=True,
        primary_expected=16,
        recovery_expected=15,
        postgres_scenarios=31,
        all_legs=("postgres",),
    ),
}
