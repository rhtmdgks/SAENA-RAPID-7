"""``IntakeGuard`` — B-verified-only, fail-closed strategy-skill-bank intake
boundary (w5-16, wave5-plan.md deliverable 3 / exit E7).

Source specification references (READ-ONLY basis for this module):
- docs/architecture/wave5-plan.md deliverable 3 / E7 — "skill-bank intake
  consumes ONLY B-verified outcomes (fail-closed)".
- wave5-plan.md Non-scope — "Strategy-card auto-approval/global sharing;
  production skill-bank learning loop (W5 = fail-closed intake boundary
  ONLY)". This module admits candidates into a ``CANDIDATE`` pool and
  STOPS THERE: no approve/promote/share/learn API exists anywhere in this
  package (see ``test_api_surface_structural`` for the executable pin).
- ``packages/contracts/json-schema/event/strategy-card-eligible/v1/
  strategy-card-eligible.schema.json`` — the wire payload this guard
  evaluates. ``source_outcome.b_verdict`` is schema-``const`` ``"pass"`` and
  ``source_outcome.evidence_bundle_manifest_hash`` is a bare content-addressed
  hash. The schema is OPEN (``compat_class: open`` — no
  ``additionalProperties: false`` at the top level) and carries NO
  tenant-identifying field by design; this guard is the second, defensive
  line the module docstring on ``b_gate.BGateDecision`` requires: *"any code
  can construct one ... a bare BGateDecision object received across a trust
  boundary [must never be trusted]"* — the schema's ``const`` enforces shape,
  this guard re-checks the SEMANTICS defensively (a forged/`model_construct`
  payload, or a legitimate payload whose backing evidence does not actually
  verify, must still be rejected here).
- ``saena_domain.measurement.evidence`` (w5-08) — ``EvidenceBundleManifest``/
  ``verify_manifest``: this guard treats a bare
  ``evidence_bundle_manifest_hash`` as UNVERIFIABLE unless the caller also
  supplies the manifest it is claimed to hash, and that manifest's OWN
  ``manifest_hash`` (recomputed via ``verify_manifest``, not merely read)
  equals the claimed hash. A hash with no verifiable manifest never admits
  (w5-08 SF-4 trust-boundary obligation, named explicitly in this unit's
  directive).
- ``saena_domain.measurement.b_gate`` (w5-06) — ``BVerdict``: PASS is the
  ONLY verdict this guard ever admits on. FAIL and UNDETERMINED (including a
  verdict forged via ``BGateDecision.model_construct`` to claim PASS-shaped
  fields while carrying an UNDETERMINED/FAIL ``verdict`` enum member) are
  REJECT(not_b_verified) — never queued for later re-evaluation or
  auto-admission (directive requirement 3).

## Two admission surfaces, one guard

Real intake happens over the wire (``strategy.card.eligible.v1`` envelope
payload — a dict/JSON object matching the generated
``saena_schemas.event.strategy_card_eligible_v1.StrategyCardEligibleV1Payload``
model). But the schema's ``b_verdict: const "pass"`` on its own does not
prove the manifest hash is verifiable, nor that the outcome is from a
production pipeline rather than a relabeled test fixture, nor that the
payload does not smuggle a tenant/raw-content field into `` card_candidate_ref``
or the open-class top-level object (the schema is intentionally
``additionalProperties``-open at the top level — an "outcome-field-gap" this
guard closes as its own obligation, wave5-plan.md "Binding conventions").
``IntakeCandidate`` is the guard's own richer input: the wire payload PLUS
the out-of-band facts (the manifest to verify the hash against, and the
outcome's provenance) that a real service boundary (w5-12) is responsible
for attaching before calling this guard. A payload alone is never sufficient
to admit; this guard never trusts wire shape as a proxy for verified fact.

## Fail-closed defaults

Every admission path is enumerated explicitly; there is no default-True
branch. Missing/absent optional context (no manifest supplied, no
provenance asserted) is treated as the WORST case (unverifiable /
non-production), never the best case. An unrecognised/extra field on the
candidate widens nothing — ``IntakeCandidate`` and its nested models are
``extra="forbid"``, so an attempted new "semantics" field that this guard
does not know how to check is a hard construction-time rejection, not a
silently-ignored pass-through (directive requirement 4).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from saena_domain.measurement.b_gate import BVerdict
from saena_domain.measurement.evidence import EvidenceBundleManifest, verify_manifest

__all__ = [
    "IntakeDecisionStatus",
    "CandidatePool",
    "SourceOutcomeProvenance",
    "SourceOutcomeAssertion",
    "IntakeCandidate",
    "IntakeRejectReason",
    "IntakeDecision",
    "IntakeGuard",
]


class IntakeDecisionStatus(str, Enum):
    """The only two possible outcomes of :meth:`IntakeGuard.evaluate`.

    There is no third value and no partial/pending state — every candidate
    is either admitted as a candidate or rejected with a named reason
    (directive requirement 4: fail-closed, no silent widening).
    """

    ADMIT_AS_CANDIDATE = "admit_as_candidate"
    REJECT = "reject"


class CandidatePool(str, Enum):
    """The pool an admitted candidate lands in.

    ``PRODUCTION`` and ``TEST`` are strictly separated: a test-fixture
    source outcome can ONLY ever land in ``TEST`` — it structurally cannot
    reach ``PRODUCTION`` (directive requirement 1c: "test-fixture admits
    only into a test-marked candidate pool, never production pool"). This
    module has no operation that moves a candidate between pools.
    """

    PRODUCTION = "production"
    TEST = "test"


class SourceOutcomeProvenance(str, Enum):
    """Where the backing B-gate outcome decision actually came from.

    Mirrors ``saena_domain.measurement.b_gate.PolicyProvenance`` /
    ``did.PolicyProvenance`` 's closed ``production`` / ``test_fixture``
    vocabulary — this module does not invent a third value. The wire
    ``strategy-card-eligible.v1`` payload carries no such field (by schema
    design, to stay tenant/production-agnostic on the bus); it is asserted
    out-of-band by the service boundary (w5-12) that calls this guard, which
    is the same boundary that has (or does not have) a legitimate production
    B-gate decision to point at.
    """

    PRODUCTION = "production"
    TEST_FIXTURE = "test_fixture"


class SourceOutcomeAssertion(BaseModel):
    """Out-of-band facts about the source outcome, asserted by the caller.

    NOT part of the wire payload — the wire schema is intentionally silent
    on b_verdict provenance and manifest verifiability (see module
    docstring). A real service boundary (w5-12) is the trusted party that
    knows whether the ``BGateDecision`` behind this candidate was a real
    production decision or a test fixture, and holds (or can fetch) the
    actual :class:`EvidenceBundleManifest` the claimed hash is supposed to
    verify against. This guard NEVER infers provenance from the payload
    shape alone — an absent/unrecognised provenance is fail-closed to "not
    production" (see :meth:`IntakeGuard.evaluate`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The actual B-gate verdict behind this candidate. Re-asserted here
    #: (rather than trusted from the wire payload's ``const: "pass"`` alone)
    #: because a payload can be forged via ``model_construct`` bypassing the
    #: schema/pydantic ``const`` check entirely — the guard re-derives its
    #: own admission decision from this field, never from wire shape.
    b_verdict: BVerdict
    #: Where the decision behind ``b_verdict`` came from.
    provenance: SourceOutcomeProvenance
    #: The evidence-bundle manifest the candidate's
    #: ``evidence_bundle_manifest_hash`` is claimed to be the hash of. `None`
    #: means "no manifest was supplied" — fail-closed to unverifiable, never
    #: to trusting the bare hash.
    manifest: EvidenceBundleManifest | None = None


#: Field NAME markers that name tenant-identifying or raw-content fields
#: outright — mirrors `saena_domain.measurement.evidence`'s
#: `_FORBIDDEN_FIELD_NAME_MARKERS` denylist discipline (NFKC + casefold +
#: separator-stripped substring match against the field NAME, never the
#: value). Superset here: adds the tenant/run/experiment identifiers this
#: aggregate-only payload must never carry (wave5-plan.md "AGGREGATE-ONLY /
#: PRIVACY" — the strategy-card-eligible schema comment pins "NO tenant_id/
#: run_id/experiment_id and NO raw customer content").
_FORBIDDEN_FIELD_NAME_MARKERS: tuple[str, ...] = (
    "tenant_id",
    "tenant",
    "customer_id",
    "customer",
    "workspace_id",
    "project_id",
    "site_id",
    "run_id",
    "experiment_id",
    "actor_id",
    "user_id",
    "account_id",
    "raw_response",
    "raw_content",
    "raw_html",
    "raw_body",
    "raw_screenshot",
    "screenshot",
    "response_body",
    "response_text",
    "query_text",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "private_key",
    "token",
)

_MAX_FIELD_VALUE_LENGTH = 4096

_SECRET_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"gh[opsu]_[A-Za-z0-9]{36}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{10,}"),
    re.compile(
        r"\b[sr]k-(live|test)-[A-Za-z0-9]{10,}"
    ),  # hyphen-infix variant (sk-live-…, c5-06 audit)
)


def _normalize_field_name(name: str) -> str:
    """Same normalization rule as ``saena_domain.measurement.evidence``
    (NFKC + casefold + separator strip) so this guard's denylist matching is
    consistent with the sibling evidence-bundle raw-content guard."""
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return normalized.replace("-", "").replace("_", "")


_NORMALIZED_FORBIDDEN_MARKERS: tuple[str, ...] = tuple(
    _normalize_field_name(marker) for marker in _FORBIDDEN_FIELD_NAME_MARKERS
)


class IntakeRejectReason(str, Enum):
    """Closed, typed vocabulary of reasons :meth:`IntakeGuard.evaluate` may
    reject a candidate for. No free-text reason ever substitutes for a
    member of this enum (mirrors ``saena_domain.measurement.reason_codes.
    ReasonCode`` discipline)."""

    NOT_B_VERIFIED = "not_b_verified"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    UNVERIFIABLE_EVIDENCE = "unverifiable_evidence"
    TAMPERED_EVIDENCE = "tampered_evidence"
    TENANT_IDENTIFYING_FIELD = "tenant_identifying_field"
    RAW_CONTENT_FIELD = "raw_content_field"


class IntakeCandidate(BaseModel):
    """One strategy-card intake request: wire payload fields + out-of-band
    verification context.

    ``extra="forbid"`` at every level (this model AND
    :class:`SourceOutcomeAssertion`) — an unrecognised extra field never
    silently widens admission; it is a hard construction-time
    :class:`pydantic.ValidationError` instead, which
    :meth:`IntakeGuard.evaluate_payload` catches and turns into a named
    ``MISSING_REQUIRED_FIELD``-shaped rejection (see that method).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_candidate_ref: str = Field(min_length=1, max_length=128)
    evidence_bundle_manifest_hash: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    source_outcome: SourceOutcomeAssertion
    #: Additional wire-payload fields beyond the two required ones (the
    #: schema is open-class: `additionalProperties` is unconstrained at the
    #: top level). Every key/value here is scanned by the aggregate-only
    #: denylist guard exactly like the two required string fields above.
    extra_payload_fields: Mapping[str, Any] = Field(default_factory=dict)


class IntakeDecision(BaseModel):
    """Frozen, pure result of :meth:`IntakeGuard.evaluate`.

    ``status == ADMIT_AS_CANDIDATE`` iff ``reject_reasons`` is empty; a
    non-empty ``reject_reasons`` always means ``REJECT`` (never a partial
    admit). ``pool`` is only meaningful (non-``None``) on an admit — a
    rejected candidate has no pool.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: IntakeDecisionStatus
    pool: CandidatePool | None = None
    reject_reasons: tuple[IntakeRejectReason, ...] = Field(default_factory=tuple)
    card_candidate_ref: str | None = None


def _sorted_reasons(reasons: set[IntakeRejectReason]) -> tuple[IntakeRejectReason, ...]:
    return tuple(sorted(reasons, key=lambda r: r.value))


def _guard_value(name: str, value: Any, offenders: set[IntakeRejectReason]) -> None:
    """Recursively scan one (name, value) pair, accumulating reject reasons
    rather than raising — this guard NEVER echoes an offending value back
    (mirrors ``saena_domain.measurement.evidence.guard_evidence_fields``'s
    redaction discipline), it only records WHICH reason category fired."""
    normalized_name = _normalize_field_name(name)
    if any(marker in normalized_name for marker in _NORMALIZED_FORBIDDEN_MARKERS):
        if (
            "raw" in normalized_name
            or "response" in normalized_name
            or "screenshot" in normalized_name
            or "query" in normalized_name
        ) or (
            "secret" in normalized_name
            or "password" in normalized_name
            or "passwd" in normalized_name
            or "token" in normalized_name
            or "key" in normalized_name
        ):
            offenders.add(IntakeRejectReason.RAW_CONTENT_FIELD)
        else:
            offenders.add(IntakeRejectReason.TENANT_IDENTIFYING_FIELD)
        return
    if not normalized_name.isascii():
        # Cross-script homoglyph smuggling defense — mirrors evidence.py.
        offenders.add(IntakeRejectReason.TENANT_IDENTIFYING_FIELD)
        return
    if isinstance(value, str):
        if len(value) > _MAX_FIELD_VALUE_LENGTH:
            offenders.add(IntakeRejectReason.RAW_CONTENT_FIELD)
            return
        for pattern in _SECRET_SHAPED_PATTERNS:
            if pattern.search(value):
                offenders.add(IntakeRejectReason.RAW_CONTENT_FIELD)
                return
        return
    if isinstance(value, Mapping):
        _guard_mapping(value, offenders)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _guard_value(name, item, offenders)


def _guard_mapping(fields: Mapping[str, Any], offenders: set[IntakeRejectReason]) -> None:
    for name, value in fields.items():
        _guard_value(name, value, offenders)


class IntakeGuard:
    """B-verified-only, fail-closed strategy-skill-bank intake boundary.

    Pure, deterministic, side-effect-free: :meth:`evaluate` performs no I/O,
    no clock reads, no network calls, and equal inputs always yield an equal
    :class:`IntakeDecision`. This is the ENTIRE public surface of intake —
    there is no ``approve``/``promote``/``share``/``learn`` method anywhere
    on this class or module (``test_api_surface_structural`` pins this as an
    executable assertion, directive requirement 2).
    """

    def evaluate(self, candidate: IntakeCandidate) -> IntakeDecision:
        """Evaluate one intake candidate against the four fail-closed gates.

        Gate order (any failure accumulates a reason; ALL applicable
        failures are reported together — a candidate failing multiple gates
        at once gets every applicable reason code, not just the first):

        (a) ``source_outcome.b_verdict`` must be exactly
            :attr:`BVerdict.PASS` — FAIL/UNDETERMINED (including a verdict
            forged to claim a PASS-shaped wire payload while asserting a
            non-PASS verdict) ⇒ ``NOT_B_VERIFIED``, never queued for later
            auto-admission (directive requirement 3).
        (b) ``evidence_bundle_manifest_hash`` must be present AND verified
            against a supplied manifest: no manifest supplied ⇒
            ``UNVERIFIABLE_EVIDENCE``; a supplied manifest whose OWN
            recomputed ``manifest_hash`` (via
            ``saena_domain.measurement.evidence.verify_manifest``) does not
            match the claimed hash, OR whose chain fails ``verify_manifest``
            outright ⇒ ``TAMPERED_EVIDENCE``. INTEGRITY ONLY: manifest
            outcome-linkage and bundle completeness are the w5-12 service
            boundary's obligation, deliberately NOT checked here (pinned by
            ``test_manifest_linkage_and_completeness_are_delegated_to_service_boundary``).
        (c) Provenance-to-pool: ``PRODUCTION`` provenance admits into the
            ``PRODUCTION`` pool; ``TEST_FIXTURE`` provenance admits ONLY
            into the ``TEST`` pool — this is a structural mapping, never a
            reject path (a test fixture is a legitimate, honestly-labelled
            input; it simply cannot reach the production pool).
        (d) Aggregate-only guard: no tenant-identifying or raw-content field
            anywhere in the candidate payload (required fields AND
            ``extra_payload_fields``, recursively) ⇒
            ``TENANT_IDENTIFYING_FIELD`` / ``RAW_CONTENT_FIELD``.

        Fail-closed default: gate (a) and (b) are evaluated independently
        and BOTH must pass — a PASS verdict with unverifiable evidence is
        rejected with both applicable considerations recorded where they
        fired; an admit requires every gate to have raised nothing.
        """
        reasons: set[IntakeRejectReason] = set()

        # --- Gate (a): B-verdict must be exactly PASS -----------------------
        if candidate.source_outcome.b_verdict is not BVerdict.PASS:
            reasons.add(IntakeRejectReason.NOT_B_VERIFIED)

        # --- Gate (b): evidence hash must be present + verified -------------
        manifest = candidate.source_outcome.manifest
        if manifest is None:
            reasons.add(IntakeRejectReason.UNVERIFIABLE_EVIDENCE)
        else:
            intact, _divergence_index = verify_manifest(manifest)
            if not intact:
                reasons.add(IntakeRejectReason.TAMPERED_EVIDENCE)
            elif manifest.manifest_hash != candidate.evidence_bundle_manifest_hash:
                # The manifest itself verifies internally, but it is not the
                # manifest this hash claims to be — the caller supplied the
                # wrong (or a stale) manifest. Fail-closed: this is
                # unverifiable evidence for THIS candidate, not a tamper of
                # the supplied manifest.
                reasons.add(IntakeRejectReason.UNVERIFIABLE_EVIDENCE)

        # --- Gate (d): aggregate-only denylist scan --------------------------
        _guard_value("card_candidate_ref", candidate.card_candidate_ref, reasons)
        _guard_mapping(dict(candidate.extra_payload_fields), reasons)

        if reasons:
            return IntakeDecision(
                status=IntakeDecisionStatus.REJECT,
                pool=None,
                reject_reasons=_sorted_reasons(reasons),
                card_candidate_ref=None,
            )

        # --- Gate (c): provenance → pool (structural, admit-only) ----------
        pool = (
            CandidatePool.PRODUCTION
            if candidate.source_outcome.provenance is SourceOutcomeProvenance.PRODUCTION
            else CandidatePool.TEST
        )
        return IntakeDecision(
            status=IntakeDecisionStatus.ADMIT_AS_CANDIDATE,
            pool=pool,
            reject_reasons=(),
            card_candidate_ref=candidate.card_candidate_ref,
        )

    def evaluate_payload(
        self,
        payload: Mapping[str, Any],
        *,
        provenance: SourceOutcomeProvenance,
        manifest: EvidenceBundleManifest | None,
    ) -> IntakeDecision:
        """Evaluate a raw wire-shaped ``strategy.card.eligible.v1`` payload
        (a plain dict, e.g. as decoded off the bus) plus the out-of-band
        provenance/manifest context a service boundary (w5-12) is
        responsible for attaching.

        Fail-closed on malformed input: ANY missing required field or
        wrong-shaped value (including a payload built to intentionally omit
        ``source_outcome`` or ``evidence_bundle_manifest_hash``, or one
        constructed via a bypassing mechanism upstream that produced a
        non-dict/partial structure) is caught and reported as
        ``MISSING_REQUIRED_FIELD`` — this method never raises for
        malformed candidate input; it always returns a
        :class:`IntakeDecision`.
        """
        try:
            b_verdict_raw = payload["source_outcome"]["b_verdict"]
            candidate = IntakeCandidate(
                card_candidate_ref=payload["card_candidate_ref"],
                evidence_bundle_manifest_hash=payload["source_outcome"][
                    "evidence_bundle_manifest_hash"
                ],
                source_outcome=SourceOutcomeAssertion(
                    b_verdict=BVerdict(b_verdict_raw),
                    provenance=provenance,
                    manifest=manifest,
                ),
                extra_payload_fields={
                    k: v
                    for k, v in payload.items()
                    if k not in ("card_candidate_ref", "source_outcome")
                },
            )
        except (KeyError, TypeError, ValueError):
            # KeyError/TypeError: payload missing a required key or the
            # wrong shape entirely (e.g. `source_outcome` not a mapping).
            # ValueError: covers both an unrecognised `b_verdict` string
            # (`BVerdict(...)` raises `ValueError` on an unknown member) AND
            # `pydantic.ValidationError` — pydantic's `ValidationError` IS a
            # `ValueError` subclass, so every construction-time rejection
            # (extra="forbid" fields, pattern mismatch, etc.) is caught
            # here too. This is a fail-closed MISSING_REQUIRED_FIELD-shaped
            # rejection — never a silent pass-through and never an
            # unhandled exception escaping the guard boundary.
            return IntakeDecision(
                status=IntakeDecisionStatus.REJECT,
                pool=None,
                reject_reasons=(IntakeRejectReason.MISSING_REQUIRED_FIELD,),
                card_candidate_ref=None,
            )
        return self.evaluate(candidate)
