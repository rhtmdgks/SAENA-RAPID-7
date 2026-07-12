"""K-anonymity runtime gate (ADR-0013 mandate).

ADR-0013 ("k-anonymity 게이트의 스키마 한계") states that the relation
``cohort_size >= privacy_threshold`` cannot be expressed in JSON Schema
2020-12 — there is no cross-field comparison operator. The AggregateContext
envelope schema (``packages/contracts/json-schema/envelope/event-envelope/v1``)
therefore only constrains each field's type and lower bound (both
``integer, minimum: 1``) and leaves the relational invariant to a
publish-side runtime gate. This module IS that gate.

See also: ``tests/contract/fixtures/envelope/invalid/cohort-below-threshold.json``,
which documents that a schema-only validator passes a cohort/threshold
violation — the permanent regression fixture this gate exists to close.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GateDecision(StrEnum):
    """Outcome of a k-anonymity gate evaluation."""

    ALLOWED = "allowed"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True, slots=True)
class KAnonymityGateResult:
    """Immutable result of :func:`KAnonymityGate.evaluate`.

    ``decision`` is the authoritative outcome; ``reason`` is a short,
    non-sensitive machine-readable code suitable for logging (it never
    carries cohort membership or lineage detail — only the numeric facts
    already present in the AggregateContext envelope).

    Security note (critic MUST-FIX, w2-03 post-review): a plain dataclass
    lets a caller construct an internally-inconsistent instance directly —
    e.g. ``KAnonymityGateResult(decision=GateDecision.ALLOWED,
    cohort_size=1, privacy_threshold=999, reason="...")`` — and hand it to
    :func:`saena_domain.privacy.status.transition` to launder a
    ``pending_review -> k_anonymized`` transition without ever running the
    gate. ``__post_init__`` closes this by recomputing the decision from
    ``cohort_size``/``privacy_threshold`` using the same validation and
    comparison :class:`KAnonymityGate` itself uses, and raising if the
    caller-supplied ``decision`` disagrees. This makes
    :meth:`KAnonymityGate.evaluate` the only way to produce a valid
    instance in practice — any other construction path is either identical
    to what ``evaluate`` would have produced, or raises.
    """

    decision: GateDecision
    cohort_size: int
    privacy_threshold: int
    reason: str

    def __post_init__(self) -> None:
        expected = KAnonymityGate._compute(self.cohort_size, self.privacy_threshold)
        if expected.decision is not self.decision:
            raise ValueError(
                "KAnonymityGateResult.decision is inconsistent with cohort_size/"
                f"privacy_threshold: supplied decision={self.decision.value!r}, but "
                f"cohort_size={self.cohort_size} privacy_threshold={self.privacy_threshold} "
                f"recomputes to decision={expected.decision.value!r}. This result must be "
                "produced by KAnonymityGate.evaluate(), not constructed directly."
            )

    @property
    def allowed(self) -> bool:
        return self.decision is GateDecision.ALLOWED


class KAnonymityGate:
    """Evaluates the ADR-0013 k-anonymity relational invariant.

    ``cohort_size >= privacy_threshold`` passes (boundary case
    ``cohort_size == privacy_threshold`` is ALLOWED — k-anonymity is
    conventionally defined as "at least k", not "more than k").

    Both inputs must respect the AggregateContext schema minima
    (``type: integer, minimum: 1`` for both ``cohort_size`` and
    ``privacy_threshold``, per event-envelope v1 §aggregateContextEnvelope).
    Values violating those minima are rejected here too — this gate is the
    single place that owns the full relational + minima check at publish
    time, since the schema alone (per ADR-0013) cannot enforce the relation.
    """

    #: Mirrors the schema minima (`"minimum": 1`) for both fields.
    MINIMUM_VALUE = 1

    @classmethod
    def evaluate(cls, cohort_size: int, privacy_threshold: int) -> KAnonymityGateResult:
        """Evaluate the gate for a given cohort size and privacy threshold.

        Raises:
            TypeError: if either argument is not an ``int`` (covers the
                "missing threshold" / wrong-type bypass-avoidance case —
                callers must not silently coerce ``None`` or floats).
            ValueError: if either argument violates the schema minimum
                (``>= 1``).
        """
        return cls._compute(cohort_size, privacy_threshold)

    @classmethod
    def _compute(cls, cohort_size: int, privacy_threshold: int) -> KAnonymityGateResult:
        """Shared decision logic, reused by both :meth:`evaluate` and
        :meth:`KAnonymityGateResult.__post_init__` (the latter uses this to
        detect forged/inconsistent results — see that class's docstring).
        Constructs the returned :class:`KAnonymityGateResult` via
        ``object.__new__`` + direct field assignment to avoid re-triggering
        ``__post_init__`` recursively; the fields assigned are exactly the
        ones this method itself just validated and computed, so the
        invariant it exists to check is satisfied by construction.
        """
        cls._validate_type("cohort_size", cohort_size)
        cls._validate_type("privacy_threshold", privacy_threshold)
        cls._validate_minimum("cohort_size", cohort_size)
        cls._validate_minimum("privacy_threshold", privacy_threshold)

        if cohort_size >= privacy_threshold:
            decision = GateDecision.ALLOWED
            reason = "cohort_size_meets_threshold"
        else:
            decision = GateDecision.SUPPRESSED
            reason = "cohort_size_below_threshold"

        result = object.__new__(KAnonymityGateResult)
        object.__setattr__(result, "decision", decision)
        object.__setattr__(result, "cohort_size", cohort_size)
        object.__setattr__(result, "privacy_threshold", privacy_threshold)
        object.__setattr__(result, "reason", reason)
        return result

    @staticmethod
    def _validate_type(field_name: str, value: int) -> None:
        # bool is an int subclass in Python; reject it explicitly so a
        # stray `True`/`False` cannot silently pass as 1/0.
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"{field_name} must be an int (schema type: integer), got {type(value).__name__}"
            )

    @classmethod
    def _validate_minimum(cls, field_name: str, value: int) -> None:
        if value < cls.MINIMUM_VALUE:
            raise ValueError(
                f"{field_name} must be >= {cls.MINIMUM_VALUE} (schema minimum), got {value}"
            )
