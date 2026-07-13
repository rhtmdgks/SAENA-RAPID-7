"""`GateId` — the closed set of gate identifiers this engine evaluates.

`gate_id` is a free string on both the `domain/verification-result/v1` and
`event/quality-gate-result/v1` contracts (deliberately NOT an enum there —
"the canonical gate list lives in quality-gates.yaml", not yet authored,
per both schemas' own `$comment`). This module is THIS package's own closed
list (a `StrEnum`, so every member IS a `str` and serializes as one via
`str(gate_id)`/`gate_id.value`) until `quality-gates.yaml` lands — it does
not conflict with either contract's openness, it is simply the concrete
vocabulary this engine's pure gate functions (`gates.py`) commit to.

`ALGORITHM_11_1_GATE_IDS` is exactly the 10 gates Algorithm §11.1 names as
mandatory (`docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11.1
table, verbatim order): Build, Tests, Link/route, Crawlability, Structured
data, Content fidelity, Security, Accessibility, Performance, Diff
rationality. `ADDITIONAL_GATE_IDS` is this patch unit's own extension set
(mission items 3-7: schema/contract validation, lint/typecheck/unit/
integration/security/boundary, changed-line coverage, forbidden-file,
secret scan, generated-code drift, plus a `commit_coherence` pre-check gate
this module adds to make base/target commit coherence a first-class,
independently-reportable `VerificationResult` row rather than a side effect
buried inside another gate).

ADR-0017 "Critical gate는 스킵 불가" / CLAUDE.md 원칙 8: every `GateId`
member here is a BLOCKING gate — this package defines no "warn-only" tier.
A single failing gate anywhere in `ALL_GATE_IDS` forbids promotion
(`engine.QualityEvalOutcome.forbids_promotion`), never just the 10
Algorithm §11.1 gates.
"""

from __future__ import annotations

from enum import StrEnum


class GateId(StrEnum):
    """Closed vocabulary of gate identifiers this engine evaluates."""

    # --- Algorithm §11.1's 10 mandatory Release Gate checks ---
    BUILD = "build"
    TESTS = "tests"
    LINK_ROUTE = "link_route"
    CRAWLABILITY = "crawlability"
    STRUCTURED_DATA = "structured_data"
    CONTENT_FIDELITY = "content_fidelity"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    DIFF_RATIONALITY = "diff_rationality"

    # --- This patch unit's additional pluggable/negative-path gates ---
    COMMIT_COHERENCE = "commit_coherence"
    SCHEMA_CONTRACT = "schema_contract"
    LINT = "lint"
    TYPECHECK = "typecheck"
    UNIT_TESTS = "unit_tests"
    INTEGRATION_TESTS = "integration_tests"
    BOUNDARY = "boundary"
    CHANGED_LINE_COVERAGE = "changed_line_coverage"
    FORBIDDEN_FILE = "forbidden_file"
    SECRET_SCAN = "secret_scan"
    GENERATED_CODE_DRIFT = "generated_code_drift"


ALGORITHM_11_1_GATE_IDS: frozenset[GateId] = frozenset(
    {
        GateId.BUILD,
        GateId.TESTS,
        GateId.LINK_ROUTE,
        GateId.CRAWLABILITY,
        GateId.STRUCTURED_DATA,
        GateId.CONTENT_FIDELITY,
        GateId.SECURITY,
        GateId.ACCESSIBILITY,
        GateId.PERFORMANCE,
        GateId.DIFF_RATIONALITY,
    }
)

ADDITIONAL_GATE_IDS: frozenset[GateId] = frozenset(
    {
        GateId.COMMIT_COHERENCE,
        GateId.SCHEMA_CONTRACT,
        GateId.LINT,
        GateId.TYPECHECK,
        GateId.UNIT_TESTS,
        GateId.INTEGRATION_TESTS,
        GateId.BOUNDARY,
        GateId.CHANGED_LINE_COVERAGE,
        GateId.FORBIDDEN_FILE,
        GateId.SECRET_SCAN,
        GateId.GENERATED_CODE_DRIFT,
    }
)

ALL_GATE_IDS: frozenset[GateId] = ALGORITHM_11_1_GATE_IDS | ADDITIONAL_GATE_IDS

assert frozenset(GateId) == ALL_GATE_IDS, (  # noqa: S101 — module-load invariant, not test code
    "GateId gained a member not classified into ALGORITHM_11_1_GATE_IDS or ADDITIONAL_GATE_IDS"
)

__all__ = [
    "ADDITIONAL_GATE_IDS",
    "ALGORITHM_11_1_GATE_IDS",
    "ALL_GATE_IDS",
    "GateId",
]
