"""F-2 Unsupported claim (k3s spec §10 row 2, failure-mode matrix `F-2`).

Fixture: a source/patch asserts "best-in-class" (or similarly superlative
public-facing wording) with no attached evidence — Algorithm §11.1 "Content
fidelity: every material claim → evidence ID, unsupported claim 0건" (zero
tolerance, no threshold) and CLAUDE.md principle 11 ("증거 없는 완료 선언
금지... 외부 lift 주장 금지").

Wired against the REAL `saena_quality_eval` Release Gate engine
(`JobKind.QUALITY_EVAL`): `gates.gate_content_fidelity` /
`engine.run_quality_evaluation`. A claim with `evidence_id=None` fails the
`content_fidelity` gate unconditionally, and — CLAUDE.md 원칙 8 ("critical
gates skip 금지": every gate this engine defines is blocking) —
`QualityEvalOutcome.forbids_promotion=True`, which is this engine's pure
DATA signal that "block public wording" translates to in practice: nothing
downstream may promote/publish a patch unit whose Release Gate result says
this.
"""

from __future__ import annotations

from factories import (
    APPROVED_SCOPE_GLOBS,
    CHANGED_FILES,
    build_gate_input_bundle,
    build_quality_eval_request,
)
from saena_quality_eval.engine import run_quality_evaluation
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import gate_content_fidelity
from saena_quality_eval.inputs import BoundaryOutcome, Claim, ContentFidelityOutcome

UNSUPPORTED_CLAIM_TEXT = "best-in-class AEO optimization — #1 in every benchmark"


def test_unsupported_superlative_claim_fails_content_fidelity_gate() -> None:
    outcome = gate_content_fidelity(
        ContentFidelityOutcome(claims=(Claim(claim_id="claim-best-in-class", evidence_id=None),))
    )
    assert outcome.gate_id == GateId.CONTENT_FIDELITY
    assert outcome.passed is False
    assert len(outcome.failures) == 1
    failure = outcome.failures[0]
    assert failure.error_code == "saena.validation.unsupported_claim"
    assert failure.retryable is False
    assert "claim-best-in-class" in failure.redacted_detail["claim_id"]


def test_evidence_backed_claim_passes_content_fidelity_gate() -> None:
    """Negative control: the SAME gate, given a claim WITH an evidence_id,
    passes — proves this is a real evidence check, not a blanket denial."""
    outcome = gate_content_fidelity(
        ContentFidelityOutcome(claims=(Claim(claim_id="claim-benchmarked", evidence_id="EV-01"),))
    )
    assert outcome.passed is True
    assert outcome.failures == ()


def test_unsupported_claim_forbids_promotion_end_to_end_via_release_gate() -> None:
    """End-to-end: `run_quality_evaluation` — one unsupported claim among
    otherwise-passing gates still forbids promotion (block public wording),
    and the `content_fidelity` `VerificationResult` row records the reason
    (auditable, not a silent drop)."""
    gate_inputs = build_gate_input_bundle(
        content_fidelity=ContentFidelityOutcome(
            claims=(
                Claim(claim_id="claim-evidenced", evidence_id="EV-01"),
                Claim(claim_id="claim-best-in-class", evidence_id=None),
            )
        ),
        boundary=BoundaryOutcome(
            changed_files=CHANGED_FILES, approved_scope_globs=APPROVED_SCOPE_GLOBS
        ),
    )
    request = build_quality_eval_request(gate_inputs=gate_inputs)

    outcome = run_quality_evaluation(request)

    assert outcome.forbids_promotion is True
    assert outcome.overall_status == "failed"
    content_fidelity_result = outcome.gate_result_for(GateId.CONTENT_FIDELITY)
    assert content_fidelity_result["status"] == "failed"
    assert content_fidelity_result["failures"]
    # audit: one audit record exists for the content_fidelity gate, and it
    # is NOT silently swallowed among the passing gates.
    content_fidelity_audit = next(
        r for r in outcome.audit_records if r.gate_id == GateId.CONTENT_FIDELITY
    )
    assert content_fidelity_audit.status == "failed"
    assert content_fidelity_audit.error_codes == ("saena.validation.unsupported_claim",)
