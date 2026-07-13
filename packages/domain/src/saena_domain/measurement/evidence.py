"""Evidence-bundle manifest — hash chain, completeness, raw-content guard (w5-08).

Pure, deterministic domain logic. No I/O, no clock, no network. Given the
same logical inputs, every function/model here produces byte-identical
output on every run/process/machine.

Source specification references (READ-ONLY basis):
- SAENA_AEO_Algorithm_and_Harness_Design_v1.md §3.7-3:196 — the evidence a
  measurement bundle must snapshot: snapshot + citation + timestamp +
  client code version + asset hash (per-observation provenance).
- §11.3:674-676 — reproducibility 100%, raw + weighted evidence both retained
  (here: as content-addressed refs + hashes, NEVER raw content itself).
- k3s Gate C:540 — raw evidence bundle + causal reporting; the bundle is the
  audit artifact a B-gate decision rests on.
- wave5-plan.md E5 — "Evidence bundle complete + tamper/reorder/splice-evident;
  no raw customer content/secrets".

## Two reuses, no new rules

1. **Hashing/canonicalization** — reuses `saena_domain.audit.canonical`
   (`canonical_json` + `sha256_hex`) VERBATIM, exactly as
   `saena_domain.experiment.ledger` does. This module invents NO second
   canonicalization or hashing rule; it only adds the same `sha256:<hex>`
   wire-form prefix the ledger uses.

2. **Position-committing chain** — the manifest's tamper-evidence mirrors
   `saena_domain.experiment.ledger.compute_experiment_hash`'s r4-03 precedent:
   each entry's chain commitment commits to BOTH the entry's own content hash
   AND the previous commitment AND the entry's index. This is what makes
   REORDER, SPLICE (middle remove/insert), and TAMPER (any entry content-hash
   change) all detectably change `manifest_hash`:
       commitment[0]   = sha256(canonical_json(
                             {"prev": None, "entry_hash": h0, "index": 0}))
       commitment[i]   = sha256(canonical_json(
                             {"prev": commitment[i-1], "entry_hash": hi, "index": i}))
       manifest_hash   = commitment[last]
   Because each commitment folds in the previous commitment AND the absolute
   index, moving an entry to a different position, removing/inserting an entry
   in the middle, or changing any entry's `content_hash` all propagate into a
   different final commitment. The manifest stores the FULL commitment tuple
   (`entry_commitments`), not just the head — `verify_manifest` recomputes the
   chain from the entries and compares element-wise, so a divergence is
   localized to the FIRST index where the recomputed commitment differs from
   the sealed one (head-only tamper, with every per-entry commitment intact,
   reports index `None`).

## Raw-content guard (fail-closed)

An evidence bundle carries REFS + HASHES only — never raw customer content or
secrets. `guard_evidence_fields` mirrors
`saena_analytics_clickhouse.guard.guard_row_fields`'s denylist discipline
(forbidden field-name markers + oversize-blob + secret-shaped value), applied
to every entry's `ref`/`metadata` payload at construction time, so a smuggled
`raw_content`/`response_body`/`api_key`/... field is rejected before an
`EvidenceEntry` can be built. The error NEVER echoes the offending value.

The guard is HEURISTIC defense-in-depth, not the primary control: the
authoritative privacy control is the ref+hash-only data model (no field is
designed to hold raw content). The guard's residual channel — a free-form
string under 4096 chars matching no known secret shape — is accepted
honestly, not claimed closed.

## Completeness (honest, never silently complete)

A B-gate-bearing bundle requires a fixed set of evidence kinds
(`REQUIRED_B_GATE_KINDS`). `validate_completeness` returns the MISSING kinds
rather than a bare bool — a bundle CAN be valid-but-incomplete for an
UNDETERMINED case, and the completeness result says so explicitly. The
`missingness_report` kind lets a bundle record its own gaps honestly; it is
NOT one of the required kinds and never substitutes for a missing kind.

## Tenant-scoped retrieval (non-leaking)

`entry_for_tenant` requires the caller's `tenant_id` to match the manifest's.
A mismatch returns the same "absent" answer (`None`) as a genuinely-absent
entry — a cross-tenant reader cannot distinguish "wrong tenant" from "no such
entry", so retrieval leaks nothing about another tenant's bundle contents.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saena_domain.audit.canonical import canonical_json, sha256_hex

_SHA256_PREFIX = "sha256:"

#: The `sha256:<hex>` wire-form shape every hash-bearing field in this module
#: must match — single definition, wired into every `Field(pattern=...)`
#: below (matches the `sha256_ref` $def pattern used throughout the contracts).
_SHA256_REF_PATTERN = r"^sha256:[0-9a-f]{64}$"

#: Sentinel `prev` for the first entry's commitment — mirrors
#: `saena_domain.experiment.ledger.GENESIS`.
GENESIS: None = None


class EvidenceKind(str, Enum):
    """The kinds of evidence an evidence bundle can carry (ALG §3.7 / k3s Gate C).

    ``str`` mixin so a kind serializes to its plain string value under
    `model_dump(mode="json")` — the manifest's canonical-JSON hashing then
    hashes the enum VALUE, not a Python repr.
    """

    REGISTRATION = "registration"
    DEPLOYMENT_CONFIRMATION = "deployment_confirmation"
    BASELINE_OBSERVATION = "baseline_observation"
    TREATMENT_OBSERVATION = "treatment_observation"
    CONTROL_OBSERVATION = "control_observation"
    RAW_OBSERVATION_REF = "raw_observation_ref"
    DID_INPUTS = "did_inputs"
    DID_OUTPUTS = "did_outputs"
    B_GATE_DECISION = "b_gate_decision"
    GRS_POLICY = "grs_policy"
    MISSINGNESS_REPORT = "missingness_report"
    REMEDIATION = "remediation"
    ROLLBACK = "rollback"


#: Observation-kind entries carry per-observation provenance (ALG §3.7-3):
#: they REQUIRE timestamp + client_version + asset_hash + explicit citation
#: decision (a citation ref OR an explicit ``citation_present=False``).
_OBSERVATION_KINDS: frozenset[EvidenceKind] = frozenset(
    {
        EvidenceKind.BASELINE_OBSERVATION,
        EvidenceKind.TREATMENT_OBSERVATION,
        EvidenceKind.CONTROL_OBSERVATION,
    }
)

#: The kinds a B-gate-bearing bundle MUST contain to be complete (wave5-plan
#: E5 / directive). ``missingness_report`` is deliberately NOT here — it
#: records gaps, it does not fill them.
REQUIRED_B_GATE_KINDS: frozenset[EvidenceKind] = frozenset(
    {
        EvidenceKind.REGISTRATION,
        EvidenceKind.DEPLOYMENT_CONFIRMATION,
        EvidenceKind.BASELINE_OBSERVATION,
        EvidenceKind.TREATMENT_OBSERVATION,
        EvidenceKind.CONTROL_OBSERVATION,
        EvidenceKind.RAW_OBSERVATION_REF,
        EvidenceKind.DID_INPUTS,
        EvidenceKind.DID_OUTPUTS,
        EvidenceKind.B_GATE_DECISION,
        EvidenceKind.GRS_POLICY,
    }
)


class EvidenceDomainError(Exception):
    """Base class for all `saena_domain.measurement.evidence` errors."""

    error_code: str = "saena.measurement.evidence.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class RawContentRejectedError(EvidenceDomainError):
    """An evidence entry carried a raw-content/secret-shaped field — REJECTED
    fail-closed before an `EvidenceEntry` could be constructed.

    The offending VALUE is never included in the message or `context` — only
    the field NAME and a redacted reason category — so logging this error
    cannot leak the very content it caught. Mirrors
    `saena_analytics_clickhouse.errors.RawContentRejectedError`.
    """

    error_code = "saena.security.raw_content_rejected"


# --- raw-content guard (mirrors saena_analytics_clickhouse.guard) -------------

# A metadata/hash/ref field on an evidence entry has no legitimate reason to
# be large — every legitimate field is a short opaque ref, hash, locale code,
# or ISO timestamp. Chosen well above the longest legitimate field while still
# catching a raw HTML page / screenshot data-URI / full model response
# smuggled into a "metadata" field.
_MAX_FIELD_VALUE_LENGTH = 4096

# Field NAME markers that name raw customer content / secrets outright —
# matched as a substring against the NORMALIZED field name (see
# `_normalize_field_name`: NFKC + casefold + '-'/'_' stripped), never the
# value, so `rawContent`, `raw-content`, `RAW_CONTENT`, and fullwidth
# compatibility forms all hit the same marker. Union of the analytics
# guard's denylist and the observation-domain raw fields the evidence bundle
# must never inline.
_FORBIDDEN_FIELD_NAME_MARKERS: tuple[str, ...] = (
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


def _normalize_field_name(name: str) -> str:
    """Normalize a field name for denylist matching (security-critic SF-1).

    NFKC (folds fullwidth/compatibility forms), `casefold` (stronger than
    `lower` — handles ß etc.), and strips `-`/`_` separators — so
    `rawContent`, `raw-content`, `RAW_CONTENT`, and `ｒａｗ_ｃｏｎｔｅｎｔ` all
    normalize onto the same marker hit. NFKC does NOT fold cross-script
    homoglyphs (e.g. Cyrillic `с` vs Latin `c`); those are killed separately
    by the non-ASCII field-name rejection in `guard_evidence_fields`.
    """
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return normalized.replace("-", "").replace("_", "")


#: Markers pre-normalized with the SAME rule the field name is normalized
#: with, so the substring match compares like with like.
_NORMALIZED_FORBIDDEN_MARKERS: tuple[str, ...] = tuple(
    _normalize_field_name(marker) for marker in _FORBIDDEN_FIELD_NAME_MARKERS
)

# VALUE-shaped secret patterns — checked against string values regardless of
# field name (a caller could name the field innocuously and still smuggle a
# credential through). Each is a well-known, low-false-positive secret shape;
# this is deliberately NOT a general entropy scanner (Ponytail).
_SECRET_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style secret key
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key
    re.compile(r"gh[opsu]_[A-Za-z0-9]{36}"),  # GitHub token (personal/oauth/server/user)
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token (bot/app/personal/legacy)
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),  # Google API key
    re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{10,}"),  # Stripe-style secret/restricted key
)


def guard_evidence_fields(fields: Mapping[str, Any]) -> None:
    """Raise `RawContentRejectedError` if any `(name, value)` in `fields`
    looks like raw customer content or a secret.

    HEURISTIC, defense-in-depth — not a content-scanning oracle. The
    AUTHORITATIVE control is the data model itself: evidence entries carry
    content-addressed refs + hashes only, with no field designed to hold raw
    content. This guard refuses the SHAPES that are obviously unsafe; the
    residual channel it cannot close is a free-form string under
    `_MAX_FIELD_VALUE_LENGTH` (4096) chars that matches no known secret
    pattern — which is why the ref+hash-only model, not this guard, is what
    the bundle's privacy claim rests on.

    Checks, in order (first match wins — the error is raised on the FIRST
    offending field, never a batch report, so no offending value is ever
    accumulated into an error payload):

    1. Field NAME normalizes (`_normalize_field_name`: NFKC + casefold +
       separator strip) onto a forbidden marker — catches `rawContent`,
       `raw-content`, fullwidth forms, etc.
    2. Field NAME still contains non-ASCII after NFKC — rejected fail-closed
       (evidence field names are code-controlled ASCII identifiers; this is
       what kills cross-script homoglyph smuggling, e.g. Cyrillic `с`).
    3. String VALUE exceeds `_MAX_FIELD_VALUE_LENGTH` (oversize-blob heuristic).
    4. String VALUE matches a known secret shape (`_SECRET_SHAPED_PATTERNS`).

    Nested mappings/sequences are walked recursively so a secret hidden one
    level down (e.g. ``metadata={"extra": {"api_key": ...}}``) is still
    caught. The raised error NEVER includes the offending value — only the
    field name and reason category.
    """
    for name, value in fields.items():
        normalized_name = _normalize_field_name(name)
        if any(marker in normalized_name for marker in _NORMALIZED_FORBIDDEN_MARKERS):
            raise RawContentRejectedError(
                f"field {name!r} has a forbidden raw-content-shaped name — value redacted",
                context={"field": name, "reason": "forbidden_field_name"},
            )
        if not normalized_name.isascii():
            raise RawContentRejectedError(
                f"field {name!r} contains non-ASCII characters after NFKC normalization "
                "— rejected fail-closed (homoglyph-smuggling defense), value redacted",
                context={"field": name, "reason": "non_ascii_field_name"},
            )
        _guard_value(name, value)


def _guard_value(name: str, value: Any) -> None:
    """Recursively guard a single value (string shape, or nested container)."""
    if isinstance(value, str):
        if len(value) > _MAX_FIELD_VALUE_LENGTH:
            raise RawContentRejectedError(
                f"field {name!r} exceeds {_MAX_FIELD_VALUE_LENGTH} chars "
                "(oversize-blob heuristic) — value redacted",
                context={
                    "field": name,
                    "reason": "oversize_blob",
                    "length": len(value),
                    "max_length": _MAX_FIELD_VALUE_LENGTH,
                },
            )
        for pattern in _SECRET_SHAPED_PATTERNS:
            if pattern.search(value):
                raise RawContentRejectedError(
                    f"field {name!r} matches a known secret-shaped pattern — value redacted",
                    context={"field": name, "reason": "secret_shaped_value"},
                )
        return
    if isinstance(value, Mapping):
        guard_evidence_fields(value)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _guard_value(name, item)


# --- content-addressed ref + metadata ----------------------------------------


class EvidenceRef(BaseModel):
    """A content-addressed pointer to an evidence artifact — ref + content hash.

    The evidence bundle NEVER inlines raw content; it points to it. `uri` is
    an opaque artifact ref / object-storage URI, and `content_hash` is the
    `sha256:<hex>` digest of the referenced content, so the bundle commits to
    exactly-which-bytes without carrying them. The guard runs over both fields
    at construction time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str = Field(min_length=1, max_length=_MAX_FIELD_VALUE_LENGTH)
    content_hash: str = Field(pattern=_SHA256_REF_PATTERN)

    @model_validator(mode="after")
    def _guard_raw_content(self) -> EvidenceRef:
        guard_evidence_fields({"uri": self.uri, "content_hash": self.content_hash})
        return self


class EvidenceMetadata(BaseModel):
    """Per-entry provenance metadata (ALG §3.7-3: timestamp + client code
    version + asset hash + citation).

    All fields optional AT THE MODEL LEVEL — per-kind requirements (e.g.
    observation kinds require timestamp/client_version/asset_hash/citation
    decision) are enforced by `EvidenceEntry`, not here, so non-observation
    kinds can carry a lighter metadata footprint. `extra` is a free-form,
    guarded map for kind-specific provenance; it is walked by the raw-content
    guard so it cannot become a smuggling channel.

    Citation decision is explicit-or-none: a `citation` ref records "this
    observation was cited HERE"; `citation_present=False` records "explicitly
    checked, not cited". A None citation with `citation_present` left None is
    an UNDECIDED citation — invalid for observation kinds (see `EvidenceEntry`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: str | None = Field(default=None, min_length=1, max_length=64)
    client_version: str | None = Field(default=None, min_length=1, max_length=256)
    asset_hash: str | None = Field(default=None, pattern=_SHA256_REF_PATTERN)
    citation: str | None = Field(default=None, min_length=1, max_length=_MAX_FIELD_VALUE_LENGTH)
    citation_present: bool | None = Field(default=None)
    extra: Mapping[str, Any] | None = Field(default=None)

    @model_validator(mode="after")
    def _guard_raw_content(self) -> EvidenceMetadata:
        payload: dict[str, Any] = {
            "timestamp": self.timestamp,
            "client_version": self.client_version,
            "asset_hash": self.asset_hash,
            "citation": self.citation,
        }
        if self.extra is not None:
            payload["extra"] = dict(self.extra)
        guard_evidence_fields({k: v for k, v in payload.items() if v is not None})
        return self

    def has_explicit_citation_decision(self) -> bool:
        """True iff a citation ref is present OR non-citation was explicitly recorded."""
        return self.citation is not None or self.citation_present is not None


class EvidenceEntry(BaseModel):
    """One evidence entry: a kind + a content-addressed ref + provenance metadata.

    Frozen. `content_hash` is the entry's OWN content hash — the value the
    manifest's chain commitment folds in at this entry's position. It is
    computed deterministically from the entry's canonical content (kind + ref
    + metadata) via `compute_entry_content_hash`; a caller does not supply it.
    Any change to kind/ref/metadata → a different `content_hash` → a different
    manifest chain commitment downstream (TAMPER-evident).

    Per-kind requirement: observation kinds (baseline/treatment/control) REQUIRE
    full provenance — timestamp + client_version + asset_hash + an explicit
    citation decision — enforced fail-closed here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    ref: EvidenceRef
    metadata: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    @model_validator(mode="after")
    def _check_observation_provenance(self) -> EvidenceEntry:
        if self.kind in _OBSERVATION_KINDS:
            missing: list[str] = []
            if self.metadata.timestamp is None:
                missing.append("timestamp")
            if self.metadata.client_version is None:
                missing.append("client_version")
            if self.metadata.asset_hash is None:
                missing.append("asset_hash")
            if not self.metadata.has_explicit_citation_decision():
                missing.append("citation_decision")
            if missing:
                raise EvidenceDomainError(
                    f"observation-kind entry {self.kind.value!r} is missing required "
                    f"provenance: {sorted(missing)}",
                    context={"kind": self.kind.value, "missing": sorted(missing)},
                )
        return self

    def content_material(self) -> dict[str, Any]:
        """The canonical content this entry's content hash commits to.

        EXCLUDES nothing derived — kind + ref + metadata are the whole entry.
        Deterministic dict (JSON-mode dump); `canonical_json` sorts keys.
        """
        return self.model_dump(mode="json")

    @property
    def content_hash(self) -> str:
        """The entry's own `sha256:<hex>` content hash (deterministic)."""
        return compute_entry_content_hash(self)


def compute_entry_content_hash(entry: EvidenceEntry) -> str:
    """Deterministic `sha256:<hex>` content hash of one evidence entry.

    Reuses `canonical_json` + `sha256_hex` verbatim (no new hashing rule).
    Two byte-identical entries hash identically; any change to kind/ref/
    metadata → a different hash.
    """
    digest = sha256_hex(canonical_json(entry.content_material()))
    return f"{_SHA256_PREFIX}{digest}"


def _compute_commitment(prev: str | None, entry_content_hash: str, index: int) -> str:
    """One link of the position-committing chain (r4-03 precedent shape).

    Commits to the previous commitment, the entry's own content hash, AND the
    entry's absolute index simultaneously — reproducing a given commitment
    requires reproducing all three, which is what makes reorder/splice/tamper
    all detectable.
    """
    material = {"prev": prev, "entry_hash": entry_content_hash, "index": index}
    digest = sha256_hex(canonical_json(material))
    return f"{_SHA256_PREFIX}{digest}"


def compute_entry_commitments(entries: tuple[EvidenceEntry, ...]) -> tuple[str, ...]:
    """Compute the FULL position-committing commitment chain for `entries`.

    `result[i]` is `commitment[i]` per the module-docstring recurrence. The
    manifest seals this whole tuple (`entry_commitments`) so `verify_manifest`
    can localize a divergence to its first index, not just detect it at the
    head. Deterministic; reuses `canonical_json`/`sha256_hex` via
    `_compute_commitment`.
    """
    commitments: list[str] = []
    prev: str | None = GENESIS
    for index, entry in enumerate(entries):
        prev = _compute_commitment(prev, entry.content_hash, index)
        commitments.append(prev)
    return tuple(commitments)


def compute_manifest_hash(entries: tuple[EvidenceEntry, ...]) -> str | None:
    """Fold `entries` into the final position-committing chain commitment.

    Returns the last commitment (`sha256:<hex>`), or `None` (`GENESIS`) for an
    empty entry tuple. Deterministic; reuses `compute_entry_commitments`.
    """
    commitments = compute_entry_commitments(entries)
    return commitments[-1] if commitments else GENESIS


class EvidenceBundleManifest(BaseModel):
    """Frozen evidence-bundle manifest: tenant/run/experiment scope + ordered
    entries + sealed commitment chain (`entry_commitments` + `manifest_hash`).

    `entry_commitments` MUST equal `compute_entry_commitments(entries)` and
    `manifest_hash` MUST equal its last element (`GENESIS`/`None` when empty) —
    both enforced at construction. A tampered/reordered/spliced entry tuple
    whose sealed chain was not recomputed fails construction (or, for a
    manifest deserialized/forged elsewhere, `verify_manifest`). Use `seal` to
    build one from entries (it computes the chain for you); direct
    construction requires the already-correct chain.

    Tamper-evident after sealing: the model is frozen, so ordinary attribute
    assignment (including appending entries) is rejected by pydantic. A caller
    that force-mutates anyway (``object.__setattr__``, ``model_construct``,
    ``model_copy(update=...)``) CAN alter the object in memory — the guarantee
    is not physical immutability but fail-closed detection: any such mutation
    that touches the entries no longer matches the sealed commitment chain,
    and `verify_manifest` reports it. A legitimately extended bundle is a NEW
    manifest sealed over the new entry tuple, never a mutation of an existing
    one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    entries: tuple[EvidenceEntry, ...] = Field(default_factory=tuple)
    entry_commitments: tuple[str, ...] = Field(default_factory=tuple)
    manifest_hash: str | None = Field(default=None)

    @model_validator(mode="after")
    def _check_commitment_chain(self) -> EvidenceBundleManifest:
        expected_commitments = compute_entry_commitments(self.entries)
        expected_head = expected_commitments[-1] if expected_commitments else GENESIS
        if self.entry_commitments != expected_commitments or self.manifest_hash != expected_head:
            raise EvidenceDomainError(
                "entry_commitments/manifest_hash do not match the position-committing "
                "chain recomputed from entries (tamper/reorder/splice or unsealed manifest)",
                context={"tenant_id": self.tenant_id, "run_id": self.run_id},
            )
        return self

    @classmethod
    def seal(
        cls,
        *,
        tenant_id: str,
        run_id: str,
        experiment_id: str,
        entries: tuple[EvidenceEntry, ...],
    ) -> EvidenceBundleManifest:
        """Build a sealed manifest, computing the commitment chain from `entries`.

        The ONLY constructor callers should use — it guarantees
        `entry_commitments` is the correct position-committing chain and
        `manifest_hash` its head for the given entries.
        """
        entry_commitments = compute_entry_commitments(entries)
        manifest_hash = entry_commitments[-1] if entry_commitments else GENESIS
        return cls(
            tenant_id=tenant_id,
            run_id=run_id,
            experiment_id=experiment_id,
            entries=entries,
            entry_commitments=entry_commitments,
            manifest_hash=manifest_hash,
        )


def verify_manifest(manifest: EvidenceBundleManifest) -> tuple[bool, int | None]:
    """Recompute the commitment chain from `entries` and compare to the sealed one.

    Returns `(True, None)` if intact. Otherwise `(False, i)` where `i`
    localizes the FIRST divergence:

    - `i` = the first index where the recomputed commitment differs from the
      sealed `entry_commitments[i]` (a tampered/reordered entry at or before
      that position);
    - `i` = `min(len(recomputed), len(sealed))` when one chain is a strict
      prefix of the other (splice/append after seal — the first position
      where one chain has a commitment and the other does not);
    - `i` = `None` when every per-entry commitment matches but the stored
      `manifest_hash` itself was tampered (head-only forgery, including an
      empty bundle carrying a bogus non-None head).

    Because construction already enforces the full chain, a manifest built via
    `seal`/construction is always `(True, None)`; this function is the
    explicit re-verification a consumer runs on a manifest it received or
    deserialized from elsewhere, and the fail-closed detector for force-mutated
    (``object.__setattr__``/``model_construct``) objects.
    """
    recomputed = compute_entry_commitments(manifest.entries)
    recomputed_head = recomputed[-1] if recomputed else GENESIS
    sealed = manifest.entry_commitments
    if recomputed == sealed and recomputed_head == manifest.manifest_hash:
        return True, None
    for index in range(min(len(recomputed), len(sealed))):
        if recomputed[index] != sealed[index]:
            return False, index
    if len(recomputed) != len(sealed):
        return False, min(len(recomputed), len(sealed))
    # Per-entry commitments all match — only the stored head diverges.
    return False, None


def validate_completeness(
    manifest: EvidenceBundleManifest,
) -> tuple[bool, frozenset[EvidenceKind]]:
    """Return `(is_complete, missing_kinds)` for a B-gate-bearing bundle.

    `is_complete` is `True` iff every kind in `REQUIRED_B_GATE_KINDS` is
    present at least once in `manifest.entries`. `missing_kinds` is the set of
    required kinds NOT present — non-empty exactly when incomplete.

    A bundle CAN be valid-but-incomplete (UNDETERMINED cases): this function
    NEVER silently reports complete when kinds are missing. A
    `missingness_report` entry is the bundle's own honest record of its gaps;
    it does NOT satisfy any required kind (it is not in `REQUIRED_B_GATE_KINDS`).
    """
    present = {entry.kind for entry in manifest.entries}
    missing = frozenset(REQUIRED_B_GATE_KINDS - present)
    return (not missing, missing)


def entry_for_tenant(
    manifest: EvidenceBundleManifest, *, tenant_id: str, index: int
) -> EvidenceEntry | None:
    """Tenant-scoped retrieval of one entry — non-leaking on mismatch.

    Returns `manifest.entries[index]` ONLY when `tenant_id` matches the
    manifest's tenant AND `index` is in range. A tenant mismatch returns the
    SAME `None` as an out-of-range index — a cross-tenant reader cannot
    distinguish "wrong tenant" from "no such entry", so retrieval leaks
    nothing about another tenant's bundle (tenancy-model.md: cross-tenant
    access target 0; the denial is indistinguishable from absence).
    """
    if tenant_id != manifest.tenant_id:
        return None
    if index < 0 or index >= len(manifest.entries):
        return None
    return manifest.entries[index]


__all__ = [
    "GENESIS",
    "REQUIRED_B_GATE_KINDS",
    "EvidenceBundleManifest",
    "EvidenceDomainError",
    "EvidenceEntry",
    "EvidenceKind",
    "EvidenceMetadata",
    "EvidenceRef",
    "RawContentRejectedError",
    "compute_entry_commitments",
    "compute_entry_content_hash",
    "compute_manifest_hash",
    "entry_for_tenant",
    "guard_evidence_fields",
    "validate_completeness",
    "verify_manifest",
]
