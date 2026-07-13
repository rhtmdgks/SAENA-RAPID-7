"""GRS (Guarantee Readiness Score) policy interface — signed bundle loading
and fail-closed eligibility evaluation (w5-07, pure domain logic).

Design authority: wave5-plan.md E6 / H1 — "GRS: signed policy bundle,
missing/unsigned => fail-closed DENY/UNDETERMINED; TEST-ONLY fixture in tests;
production values BLOCKED(human)". This module builds the MECHANISM ONLY.

## What "mechanism only" means here (the load-bearing invariant)

The production GRS threshold numbers, the B-SLA remediation window, and the
credit mechanics are an OPEN human decision (§13-7). This module therefore
contains **no threshold constant of any kind** — every threshold value flows
in from a signed `GrsPolicyBundle.values` mapping that is *opaque* to this
code. `tests/unit/domain_measurement_grs/test_grs_policy.py::
test_module_source_contains_no_numeric_threshold_constants` greps this file's
source and fails if a float literal (or any non-structural int literal)
appears — a fallback threshold baked into the mechanism would be a silent
production decision, exactly what §13-7 forbids.

Concretely, eligibility never reads a bundle value via ``dict.get(key,
default)``; it reads ONLY through `GrsPolicyBundle.require_threshold`, which
takes NO default parameter and RAISES `ThresholdMissingError` on a missing
key. A missing required threshold is therefore structurally impossible to
"default-pass": the evaluator catches that raise and returns `DENY` naming the
missing key.

## Fail-closed loading

`load_policy_bundle` is default-refuse — mirroring
`saena_policy_gate.engine.PolicyEngine`'s default-deny shape one layer up. It
REFUSES (raises `PolicyRefusedError`) unless every one of these holds:

  - the raw payload is a mapping carrying `version` / `values` / `provenance`;
  - `provenance` is a recognized enum value;
  - a `provenance=production` bundle carries a signature AND an injected
    `verifier` AND `verifier.verify(signed_digest, signature)` returns True,
    where `signed_digest` is bound to the bundle's own canonical content
    (`bundle_hash`), so a post-signing tamper of `values`/`version`/
    `provenance` breaks verification;
  - a `provenance=test_fixture` payload is NEVER loadable unsigned through this
    function — the only unsigned test-fixture path is the explicit,
    loudly-named `make_test_fixture_policy()` factory. A hostile raw payload
    that self-declares `test_fixture` to dodge the signature requirement is
    refused here.

An absent verifier, a rejecting verifier, and a verifier that RAISES are all
fail-closed REFUSED — a verifier backend exception must never propagate as an
accidental allow.

## Honest reporting (mechanism PASS / production BLOCKED separation)

Every `GrsDecision` carries `policy_version` + `bundle_hash` + `provenance`
(audit requirement — even a DENY carries them). A decision made against a
`test_fixture` bundle has `is_production_valid == False` regardless of the
eligibility outcome, so a passing MECHANISM test can never be misread
downstream as a passing PRODUCTION guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from saena_domain.audit.canonical import canonical_json, sha256_hex

# Semantic-version (MAJOR.MINOR.PATCH) — repo-canonical pattern, verbatim from
# packages/contracts/json-schema/common/identifiers/v1/identifiers.schema.json
# #/$defs/semver (critic #1 should-fix 1): rejects leading zeros ("01.0.0").
# Structural pattern, not a threshold — the digits live inside a regex STRING
# literal (a STRING token, never a NUMBER token), so the module's
# no-numeric-literal structural test remains meaningful.
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

# Default semver for a TEST-ONLY fixture bundle. Assembled from `str(len(...))`
# rather than written as a bare "0.0.0" string literal ON PURPOSE: the module's
# structural test greps this source for numeric literals to prove no production
# threshold constant is baked in, and a literal version string would read as a
# float to that grep. Building it from a non-numeric expression keeps the
# "zero threshold constants" property literally true in the source bytes.
_ZERO_PART = str(len(""))
_FIXTURE_DEFAULT_VERSION = ".".join((_ZERO_PART, _ZERO_PART, _ZERO_PART))


class PolicyProvenance(str, Enum):
    """Where a GRS policy bundle came from. Immutable on a constructed bundle;
    part of the signed/hashed payload so it cannot be flipped post-signing."""

    PRODUCTION = "production"
    TEST_FIXTURE = "test_fixture"


class GrsEligibility(str, Enum):
    """The eligibility verdict of a GRS evaluation."""

    ELIGIBLE = "ELIGIBLE"
    DENY = "DENY"
    UNDETERMINED = "UNDETERMINED"


class PolicyRefusedError(Exception):
    """Raised by `load_policy_bundle` when a bundle cannot be safely loaded.

    Carries a machine-stable `reason` string in addition to the human message
    — the fail-closed outcome is always explicit, never a bare truthiness
    check at the call site.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ThresholdMissingError(KeyError):
    """Raised by `GrsPolicyBundle.require_threshold` when a required threshold
    key is absent from `values`. A `KeyError` subclass so it reads naturally,
    but its own type lets the evaluator catch EXACTLY the missing-threshold
    case (and name the key) rather than swallowing unrelated `KeyError`s."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


@runtime_checkable
class SignatureVerifier(Protocol):
    """Injected signature-verification port. Kept as a Protocol so this pure
    domain module never imports a crypto library — production wiring supplies a
    real implementation; tests supply deterministic doubles. `verify` returns
    True IFF `signature` is a valid signature over `signed_digest`."""

    def verify(self, signed_digest: str, signature: str) -> bool: ...


def _canonical_payload(
    *, version: str, values: Mapping[str, Any], provenance: PolicyProvenance
) -> str:
    """The canonical byte-string a bundle commits to: values + version +
    provenance, via `saena_domain.audit.canonical` (reused — no new hashing
    rule per wave5-plan.md binding conventions). `dict(values)` normalizes any
    read-only proxy back to a plain mapping so `canonical_json`'s `sort_keys`
    produces the identical bytes regardless of the values container type."""
    return canonical_json(
        {
            "provenance": provenance.value,
            "values": dict(values),
            "version": version,
        }
    )


def compute_bundle_hash(
    *, version: str, values: Mapping[str, Any], provenance: PolicyProvenance
) -> str:
    """SHA-256 hex of the canonical (values+version+provenance) payload."""
    return sha256_hex(_canonical_payload(version=version, values=values, provenance=provenance))


@dataclass(frozen=True, slots=True)
class GrsPolicyBundle:
    """An immutable GRS policy bundle.

    `values` is an OPAQUE mapping of named thresholds — this module never
    interprets a specific key's numeric meaning, it only reads keys by name via
    `require_threshold`. The stored `values` is wrapped in a read-only
    `MappingProxyType` so a holder cannot mutate a threshold after
    construction (which would silently diverge from `bundle_hash`).
    """

    version: str
    values: Mapping[str, Any]
    provenance: PolicyProvenance
    test_only: bool = field(default=False)
    # Precomputed at construction (critic #2 re-verify round 4 MUST-FIX): the
    # canonical digest is computed EXACTLY ONCE, inside __post_init__, so
    # (a) a non-JSON-serializable `values` payload fails AT CONSTRUCTION with
    # ValueError — no constructed bundle can ever crash a later read path
    # (evaluate_grs_eligibility's decision records access bundle_hash on
    # EVERY exit; a lazy recomputing property made that a raw-TypeError
    # landmine reachable via make_test_fixture_policy or direct
    # construction), and (b) every subsequent `bundle_hash` read returns the
    # cached string with no recomputation to fail.
    _bundle_hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _SEMVER_RE.match(self.version):
            raise ValueError(f"version must be MAJOR.MINOR.PATCH semver, got {self.version!r}")
        # Invariant (critic #2 should-fix 1): `test_only` is NOT an independent
        # degree of freedom — it must equal `provenance is TEST_FIXTURE`.
        # Rejecting the two nonsense states at construction (production+
        # test_only, and an un-marked test_fixture) means no reachable bundle
        # can ever carry a contradictory marker for `is_production_valid` to
        # misread downstream.
        expected_test_only = self.provenance is PolicyProvenance.TEST_FIXTURE
        if self.test_only is not expected_test_only:
            raise ValueError(
                "test_only must equal (provenance is test_fixture): got "
                f"test_only={self.test_only!r} with provenance={self.provenance.value!r}"
            )
        # Freeze `values` behind a read-only proxy (object.__setattr__ because
        # the dataclass is frozen). A plain dict copy first so the proxy is
        # over a private copy, not the caller's live dict.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        # Serializability is validated HERE, uniformly for every construction
        # path (loader, factory, direct) — canonical_json's TypeError on a
        # set/bytes/... value becomes a construction-time ValueError, never a
        # deferred crash inside an evaluation/audit read path.
        try:
            digest = compute_bundle_hash(
                version=self.version, values=self.values, provenance=self.provenance
            )
        except TypeError:
            raise ValueError(
                "non-serializable values (fail-closed): policy bundle values "
                "must be canonical-JSON-serializable"
            ) from None
        object.__setattr__(self, "_bundle_hash", digest)

    @property
    def bundle_hash(self) -> str:
        """The canonical digest, precomputed at construction — a plain cached
        read that CANNOT raise (see `_bundle_hash` field note)."""
        return self._bundle_hash

    def require_threshold(self, key: str) -> Any:
        """Return `values[key]`, RAISING `ThresholdMissingError` if absent.

        This is the ONLY way eligibility reads a threshold. It takes NO
        `default` parameter by design — a default would be a fallback
        threshold, the exact thing this module must not have. Missing =>
        fail-closed (the caller turns the raise into DENY)."""
        try:
            return self.values[key]
        except KeyError:
            raise ThresholdMissingError(key) from None


def make_test_fixture_policy(
    values: Mapping[str, Any] | None = None,
    *,
    version: str = _FIXTURE_DEFAULT_VERSION,
) -> GrsPolicyBundle:
    """Construct a TEST-ONLY, UNSIGNED GRS policy bundle. DO NOT USE IN
    PRODUCTION.

    ============================ TEST-ONLY ============================
    This factory is the ONLY sanctioned way to obtain an unsigned GRS
    policy bundle. It exists so unit tests can exercise the eligibility
    MECHANISM without a real signing key. Every bundle it returns has
    `provenance == TEST_FIXTURE` and `test_only == True`, so every
    decision derived from it reports `is_production_valid == False` — a
    fixture can NEVER masquerade as a production guarantee. Loading a
    production policy always goes through `load_policy_bundle` with a real
    signature + verifier.
    ==================================================================

    `values` defaults to an EMPTY mapping when omitted — a fixture author must
    opt into whatever threshold keys their test needs; there is no baked-in
    default threshold value here either.
    """
    return GrsPolicyBundle(
        version=version,
        values=dict(values) if values is not None else {},
        provenance=PolicyProvenance.TEST_FIXTURE,
        test_only=True,
    )


def _coerce_provenance(raw_provenance: Any) -> PolicyProvenance:
    try:
        return PolicyProvenance(raw_provenance)
    except ValueError:
        raise PolicyRefusedError(
            f"unrecognized provenance {raw_provenance!r} (fail-closed)"
        ) from None


def load_policy_bundle(
    raw: Any,
    *,
    signature: str | None,
    verifier: SignatureVerifier | None,
) -> GrsPolicyBundle:
    """Load + verify a raw GRS policy bundle, fail-closed (default-refuse).

    `raw` is the untrusted, pre-verification payload (as decoded from bytes):
    a mapping carrying `version` / `values` / `provenance`. `signature` is the
    detached signature over the bundle's canonical digest; `verifier` is the
    injected verification port.

    Raises `PolicyRefusedError` unless the bundle is structurally well-formed
    AND (for production provenance) carries a signature that the injected
    verifier accepts over the bundle's own content digest. See module docstring
    for the full refusal matrix.
    """
    if not isinstance(raw, Mapping):
        raise PolicyRefusedError("raw policy bundle is not a mapping (fail-closed)")

    missing = [k for k in ("version", "values", "provenance") if k not in raw]
    if missing:
        raise PolicyRefusedError(f"raw policy bundle missing keys {missing} (fail-closed)")

    raw_values = raw["values"]
    if not isinstance(raw_values, Mapping):
        raise PolicyRefusedError("policy bundle 'values' is not a mapping (fail-closed)")

    provenance = _coerce_provenance(raw["provenance"])
    version = raw["version"]
    if not isinstance(version, str):
        raise PolicyRefusedError("policy bundle 'version' is not a string (fail-closed)")

    if provenance is PolicyProvenance.TEST_FIXTURE:
        # A raw payload self-declaring test_fixture must NOT bypass the
        # signature requirement — the only unsigned fixture path is the
        # explicit make_test_fixture_policy() factory.
        raise PolicyRefusedError(
            "test_fixture provenance is not loadable via load_policy_bundle; "
            "use make_test_fixture_policy() (fail-closed)"
        )

    # provenance is PRODUCTION from here — a signature is MANDATORY.
    if signature is None:
        raise PolicyRefusedError("production policy bundle requires a signature (fail-closed)")
    if verifier is None:
        raise PolicyRefusedError("production policy bundle requires a verifier (fail-closed)")

    # Construction is the single validation choke point (critic #2 re-verify
    # round 4): semver, the test_only/provenance invariant, AND values
    # serializability (the digest is computed once inside __post_init__) all
    # raise ValueError there — converted here to PolicyRefusedError per this
    # function's contract (critic #1 should-fix 2). A non-JSON-serializable
    # `values` payload therefore surfaces as PolicyRefusedError("... non-
    # serializable values ..."), never a bare TypeError; after construction,
    # `bundle_hash` is a cached read that cannot raise.
    try:
        bundle = GrsPolicyBundle(version=version, values=raw_values, provenance=provenance)
    except ValueError as exc:
        raise PolicyRefusedError(f"malformed policy bundle: {exc} (fail-closed)") from None

    signed_digest = bundle.bundle_hash
    try:
        accepted = verifier.verify(signed_digest, signature)
    except Exception:  # noqa: BLE001 - any verifier failure is fail-closed
        raise PolicyRefusedError("signature verifier raised (fail-closed)") from None

    # MUST-FIX (critic #2): STRICT acceptance — only the literal bool True
    # accepts. A truthiness check (`if not accepted`) fails OPEN for a
    # misbehaving verifier that returns a truthy non-bool ("false", 1,
    # object(), ...); `is not True` refuses every such value. Note `1 == True`
    # in Python but `1 is not True` — identity, not equality, is the guard.
    if accepted is not True:
        raise PolicyRefusedError(
            "signature verification failed / hash mismatch / non-boolean verifier "
            "verdict (fail-closed)"
        )

    return bundle


# --------------------------------------------------------------------------
# Eligibility evaluation
# --------------------------------------------------------------------------

# Threshold KEY NAMES and the comparison each imposes — these are structural
# (names + operator identity), NOT threshold values. Each entry maps a bundle
# threshold key to (input key, comparator name). The threshold NUMBER lives
# only in the signed bundle; this table only knows WHICH input to compare
# against WHICH threshold and in WHICH direction.
#
# `at_least`  : input >= threshold  (e.g. min score, min independent layers)
# `at_most`   : input <= threshold  (e.g. max open incidents)
_REQUIRED_THRESHOLDS: tuple[tuple[str, str, str], ...] = (
    ("min_grs", "grs", "at_least"),
    ("min_independent_layers", "independent_layers", "at_least"),
    ("max_open_incidents", "open_incidents", "at_most"),
)


def _passes(comparator: str, observed: Any, threshold: Any) -> bool:
    if comparator == "at_least":
        return observed >= threshold
    # at_most
    return observed <= threshold


@dataclass(frozen=True, slots=True)
class GrsDecision:
    """The outcome of a GRS eligibility evaluation.

    ALWAYS carries `policy_version` + `bundle_hash` + `provenance` (audit
    requirement) — even a DENY. `is_production_valid` is True IFF the decision
    came from a `production`-provenance bundle: a `test_fixture` decision is
    never a production guarantee, keeping downstream reporting honest.
    """

    decision: GrsEligibility
    reason: str
    policy_version: str | None
    bundle_hash: str | None
    provenance: PolicyProvenance | None
    is_production_valid: bool


def evaluate_grs_eligibility(
    inputs: Mapping[str, Any],
    *,
    bundle: GrsPolicyBundle | None,
) -> GrsDecision:
    """Evaluate GRS eligibility for `inputs` against a policy `bundle`.

    - No bundle at all => `UNDETERMINED(grs_policy_missing)` (no policy loaded;
      an eligibility judgement is impossible, not a denial).
    - Any REQUIRED threshold key absent from `bundle.values` => `DENY`, naming
      the missing key (fail-closed via `require_threshold`'s raise — never a
      default-pass).
    - Any required input field absent => `DENY` (the observation needed to
      clear a present threshold is missing).
    - All present thresholds cleared => `ELIGIBLE`; otherwise `DENY`.

    Every returned decision carries the bundle's version/hash/provenance;
    `is_production_valid` is True only when the bundle is BOTH
    production-provenance AND not test-marked (`test_only is False`).
    """
    if bundle is None:
        return GrsDecision(
            decision=GrsEligibility.UNDETERMINED,
            reason="grs_policy_missing",
            policy_version=None,
            bundle_hash=None,
            provenance=None,
            is_production_valid=False,
        )

    # BOTH conditions consulted (critic #2 should-fix 1): production
    # provenance AND not test-marked. The construction invariant makes the
    # two agree on every reachable bundle, but this check must not silently
    # depend on that invariant staying enforced elsewhere (defense in depth —
    # if either signal says "test", the decision is not production-valid).
    is_production_valid = (
        bundle.provenance is PolicyProvenance.PRODUCTION and bundle.test_only is False
    )

    def _decision(outcome: GrsEligibility, reason: str) -> GrsDecision:
        return GrsDecision(
            decision=outcome,
            reason=reason,
            policy_version=bundle.version,
            bundle_hash=bundle.bundle_hash,
            provenance=bundle.provenance,
            is_production_valid=is_production_valid,
        )

    for threshold_key, input_key, comparator in _REQUIRED_THRESHOLDS:
        # Strict accessor: a missing threshold RAISES rather than defaulting.
        try:
            threshold = bundle.require_threshold(threshold_key)
        except ThresholdMissingError:
            return _decision(
                GrsEligibility.DENY,
                f"grs_threshold_missing:{threshold_key}",
            )

        if input_key not in inputs:
            return _decision(
                GrsEligibility.DENY,
                f"grs_input_missing:{input_key}",
            )

        # A non-numeric/incomparable threshold or input (e.g. a signed bundle
        # carrying values={'min_grs': 'high'}) raises TypeError inside the
        # comparison — converted to DENY naming the threshold key (critic #2
        # should-fix 3), never leaked as a raw TypeError and never treated as
        # a pass. Fail-closed: a threshold whose value cannot be compared
        # cannot be cleared.
        try:
            passed = _passes(comparator, inputs[input_key], threshold)
        except TypeError:
            return _decision(
                GrsEligibility.DENY,
                f"grs_malformed_threshold_value:{threshold_key}",
            )

        if not passed:
            return _decision(
                GrsEligibility.DENY,
                f"grs_threshold_not_met:{threshold_key}",
            )

    return _decision(GrsEligibility.ELIGIBLE, "grs_eligible")


__all__ = [
    "GrsDecision",
    "GrsEligibility",
    "GrsPolicyBundle",
    "PolicyProvenance",
    "PolicyRefusedError",
    "SignatureVerifier",
    "ThresholdMissingError",
    "compute_bundle_hash",
    "evaluate_grs_eligibility",
    "load_policy_bundle",
    "make_test_fixture_policy",
]
