"""Tests for saena_domain.measurement.evidence — manifest hash chain,
completeness, raw-content guard, tenant-scoped retrieval (w5-08).

Discriminating/adversarial first: reorder, splice, single-hash-flip,
append-after-seal, secret smuggling, cross-tenant read, guard mutation.
Pure + deterministic; no I/O, no clock.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from saena_domain.measurement.evidence import (
    GENESIS,
    REQUIRED_B_GATE_KINDS,
    EvidenceBundleManifest,
    EvidenceDomainError,
    EvidenceEntry,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRef,
    RawContentRejectedError,
    compute_entry_content_hash,
    compute_manifest_hash,
    entry_for_tenant,
    guard_evidence_fields,
    validate_completeness,
    verify_manifest,
)

from .conftest import (
    complete_entries,
    entry,
    observation_metadata,
    ref,
    sealed_bundle,
)

# --- EvidenceRef ------------------------------------------------------------


def test_ref_is_frozen() -> None:
    r = ref("a")
    with pytest.raises(ValidationError):
        r.uri = "s3://other"


def test_ref_requires_sha256_content_hash() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(uri="s3://x", content_hash="not-a-hash")


def test_ref_rejects_empty_uri() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(uri="", content_hash="sha256:" + "a" * 64)


# --- raw-content guard: field-name / value-shape / recursion ----------------


@pytest.mark.parametrize(
    "field_name",
    [
        "raw_content",
        "raw_html",
        "screenshot",
        "response_body",
        "response_text",
        "query_text",
        "secret_note",
        "password",
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "private_key",
        "bearer_token",
    ],
)
def test_guard_rejects_forbidden_field_names(field_name: str) -> None:
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({field_name: "harmless-looking-short-value"})
    # error names the field but never echoes the value
    assert field_name in str(exc.value)
    assert exc.value.context["reason"] == "forbidden_field_name"


def test_guard_rejects_oversize_blob() -> None:
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"note": "x" * 5000})
    assert exc.value.context["reason"] == "oversize_blob"
    # value itself never in the error payload
    assert "x" * 5000 not in str(exc.value)
    assert "xxxx" not in str(exc.value)


@pytest.mark.parametrize(
    "secret_value",
    [
        "sk-" + "A" * 30,
        "AKIA" + "A" * 16,
        "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        "-----BEGIN RSA PRIVATE KEY-----",
        "ghp_" + "a" * 36,
    ],
)
def test_guard_rejects_secret_shaped_values(secret_value: str) -> None:
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"innocuous_name": secret_value})
    assert exc.value.context["reason"] == "secret_shaped_value"
    assert secret_value not in str(exc.value)


@pytest.mark.parametrize(
    "field_name",
    [
        "rawContent",  # camelCase — normalization strips nothing but casefolds
        "raw-content",  # kebab-case — separator stripped
        "RAW_CONTENT",  # shouting snake — casefolded
        "Api-Key",  # mixed case + kebab
        "responseBody",  # camelCase response_body
        "ｒａｗ_ｃｏｎｔｅｎｔ",  # fullwidth compatibility forms — NFKC folds to ascii
    ],
)
def test_guard_rejects_normalized_field_name_variants(field_name: str) -> None:
    # security-critic SF-1: name normalization (NFKC + casefold + separator
    # strip) kills camelCase/kebab/fullwidth denylist bypasses
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({field_name: "short"})
    assert exc.value.context["reason"] == "forbidden_field_name"


def test_guard_rejects_cyrillic_homoglyph_field_name() -> None:
    # Cyrillic 'с' (U+0441) in "raw_сontent" survives NFKC — the non-ASCII
    # field-name rejection kills the cross-script homoglyph bypass fail-closed
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"raw_сontent": "short"})
    assert exc.value.context["reason"] == "non_ascii_field_name"


@pytest.mark.parametrize(
    "secret_value",
    [
        "xoxb-" + "1234567890-abcdef",  # Slack bot token
        "xoxp-" + "1234567890-abcdef",  # Slack personal token
        "AIza" + "B" * 35,  # Google API key
        "sk_live_" + "a1b2c3d4e5f6g7h8",  # Stripe live secret key
        "rk_test_" + "a1b2c3d4e5f6g7h8",  # Stripe test restricted key
        "gho_" + "a" * 36,  # GitHub OAuth token (widened gh[opsu]_)
        "ghs_" + "a" * 36,  # GitHub server token
    ],
)
def test_guard_rejects_widened_secret_shapes(secret_value: str) -> None:
    # security-critic SF-2: widened secret-shape corpus
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"innocuous_name": secret_value})
    assert exc.value.context["reason"] == "secret_shaped_value"
    assert secret_value not in str(exc.value)


def test_guard_walks_nested_mapping() -> None:
    with pytest.raises(RawContentRejectedError):
        guard_evidence_fields({"extra": {"nested": {"api_key": "whatever"}}})


def test_guard_walks_nested_sequence_for_secret_shape() -> None:
    with pytest.raises(RawContentRejectedError) as exc:
        guard_evidence_fields({"refs": ["ok", "sk-" + "Z" * 30]})
    assert exc.value.context["reason"] == "secret_shaped_value"


def test_guard_accepts_clean_refs_and_hashes() -> None:
    # no raise
    guard_evidence_fields(
        {"uri": "s3://bundle/x", "content_hash": "sha256:" + "a" * 64, "locale": "en-US"}
    )


def test_guard_ignores_non_string_scalars() -> None:
    guard_evidence_fields({"count": 5, "flag": True, "missing": None})


def test_error_to_dict_is_log_safe() -> None:
    err = RawContentRejectedError("redacted", context={"field": "f", "reason": "x"})
    d = err.to_dict()
    assert d["error_code"] == "saena.security.raw_content_rejected"
    assert d["field"] == "f"


# --- guard enforced at EvidenceRef / EvidenceMetadata construction ----------


def test_ref_construction_rejects_secret_in_uri() -> None:
    # guard raises RawContentRejectedError from within the model_validator;
    # pydantic propagates non-ValueError exceptions unwrapped.
    with pytest.raises(RawContentRejectedError):
        EvidenceRef(uri="s3://x?token=sk-" + "A" * 30, content_hash="sha256:" + "a" * 64)


def test_metadata_construction_rejects_secret_in_extra() -> None:
    with pytest.raises(RawContentRejectedError):
        EvidenceMetadata(extra={"api_key": "leaked"})


def test_metadata_construction_rejects_secret_shaped_citation() -> None:
    with pytest.raises(RawContentRejectedError):
        EvidenceMetadata(citation="ghp_" + "a" * 36)


# --- per-observation provenance requirement (ALG §3.7-3) --------------------


@pytest.mark.parametrize(
    "kind",
    [
        EvidenceKind.BASELINE_OBSERVATION,
        EvidenceKind.TREATMENT_OBSERVATION,
        EvidenceKind.CONTROL_OBSERVATION,
    ],
)
def test_observation_kinds_require_full_provenance(kind: EvidenceKind) -> None:
    # missing everything → invalid
    with pytest.raises(EvidenceDomainError) as exc:
        EvidenceEntry(kind=kind, ref=ref("a"), metadata=EvidenceMetadata())
    missing = exc.value.context["missing"]
    assert set(missing) == {"timestamp", "client_version", "asset_hash", "citation_decision"}


def test_observation_missing_timestamp_only() -> None:
    with pytest.raises(EvidenceDomainError) as exc:
        EvidenceEntry(
            kind=EvidenceKind.BASELINE_OBSERVATION,
            ref=ref("a"),
            metadata=observation_metadata(timestamp=None),
        )
    assert exc.value.context["missing"] == ["timestamp"]


def test_observation_explicit_non_citation_is_valid() -> None:
    # citation=None but citation_present=False is an EXPLICIT decision → valid
    e = EvidenceEntry(
        kind=EvidenceKind.TREATMENT_OBSERVATION,
        ref=ref("a"),
        metadata=observation_metadata(citation=None, citation_present=False),
    )
    assert e.kind is EvidenceKind.TREATMENT_OBSERVATION


def test_observation_undecided_citation_is_invalid() -> None:
    # citation=None AND citation_present=None → undecided → invalid
    with pytest.raises(EvidenceDomainError) as exc:
        EvidenceEntry(
            kind=EvidenceKind.CONTROL_OBSERVATION,
            ref=ref("a"),
            metadata=observation_metadata(citation=None, citation_present=None),
        )
    assert "citation_decision" in exc.value.context["missing"]


def test_non_observation_kind_needs_no_provenance() -> None:
    # a b_gate_decision entry with empty metadata is fine
    e = EvidenceEntry(kind=EvidenceKind.B_GATE_DECISION, ref=ref("a"))
    assert e.metadata.timestamp is None


def test_entry_is_frozen() -> None:
    e = entry(EvidenceKind.REGISTRATION)
    with pytest.raises(ValidationError):
        e.kind = EvidenceKind.ROLLBACK


# --- entry content hash: determinism / sensitivity --------------------------


def test_entry_content_hash_is_deterministic() -> None:
    e = entry(EvidenceKind.REGISTRATION)
    assert compute_entry_content_hash(e) == compute_entry_content_hash(e) == e.content_hash
    assert e.content_hash.startswith("sha256:")
    assert len(e.content_hash) == len("sha256:") + 64


def test_entry_content_hash_changes_with_kind() -> None:
    a = EvidenceEntry(kind=EvidenceKind.REGISTRATION, ref=ref("a"))
    b = EvidenceEntry(kind=EvidenceKind.REMEDIATION, ref=ref("a"))
    assert a.content_hash != b.content_hash


def test_entry_content_hash_changes_with_ref() -> None:
    a = EvidenceEntry(kind=EvidenceKind.REGISTRATION, ref=ref("a"))
    b = EvidenceEntry(kind=EvidenceKind.REGISTRATION, ref=ref("b"))
    assert a.content_hash != b.content_hash


def test_entry_content_hash_changes_with_metadata() -> None:
    a = entry(EvidenceKind.BASELINE_OBSERVATION)
    b = entry(EvidenceKind.BASELINE_OBSERVATION, client_version="different-version")
    assert a.content_hash != b.content_hash


# --- manifest hash chain: seal / determinism / empty ------------------------


def test_seal_computes_matching_manifest_hash() -> None:
    m = sealed_bundle()
    assert m.manifest_hash == compute_manifest_hash(m.entries)
    ok, idx = verify_manifest(m)
    assert (ok, idx) == (True, None)


def test_manifest_hash_is_deterministic_across_independent_builds() -> None:
    assert sealed_bundle().manifest_hash == sealed_bundle().manifest_hash


def test_empty_bundle_has_genesis_manifest_hash() -> None:
    m = EvidenceBundleManifest.seal(tenant_id="t", run_id="r", experiment_id="e", entries=())
    assert m.manifest_hash is GENESIS
    assert verify_manifest(m) == (True, None)


def test_compute_manifest_hash_empty_is_genesis() -> None:
    assert compute_manifest_hash(()) is GENESIS


# --- ADVERSARIAL: reorder / splice / tamper / append ------------------------


def test_reorder_two_entries_changes_manifest_hash() -> None:
    entries = complete_entries()
    m1 = sealed_bundle(entries)
    swapped = (entries[1], entries[0], *entries[2:])
    m2 = sealed_bundle(swapped)
    assert m1.manifest_hash != m2.manifest_hash


def test_reorder_fails_verify_when_hash_reused() -> None:
    # Forge a manifest whose entries are reordered but manifest_hash is the
    # ORIGINAL (attacker reuses the old head) → verify must fail.
    entries = complete_entries()
    original = sealed_bundle(entries)
    reordered = (entries[1], entries[0], *entries[2:])
    with pytest.raises(EvidenceDomainError):
        # construction itself rejects: stored hash != recomputed chain
        EvidenceBundleManifest(
            tenant_id=original.tenant_id,
            run_id=original.run_id,
            experiment_id=original.experiment_id,
            entries=reordered,
            manifest_hash=original.manifest_hash,
        )


def test_splice_removal_changes_manifest_hash() -> None:
    entries = complete_entries()
    m_full = sealed_bundle(entries)
    spliced = (*entries[:3], *entries[4:])  # remove middle entry index 3
    m_spliced = sealed_bundle(spliced)
    assert m_full.manifest_hash != m_spliced.manifest_hash


def test_splice_insertion_changes_manifest_hash() -> None:
    entries = complete_entries()
    m_full = sealed_bundle(entries)
    extra = entry(EvidenceKind.REMEDIATION, suffix="e")
    inserted = (*entries[:3], extra, *entries[3:])
    m_inserted = sealed_bundle(inserted)
    assert m_full.manifest_hash != m_inserted.manifest_hash


def test_single_entry_hash_flip_changes_manifest_hash() -> None:
    entries = complete_entries()
    m1 = sealed_bundle(entries)
    # tamper one entry's content (new ref → new content hash)
    tampered = list(entries)
    tampered[5] = EvidenceEntry(kind=tampered[5].kind, ref=ref("f"))
    m2 = sealed_bundle(tuple(tampered))
    assert m1.manifest_hash != m2.manifest_hash


def test_tamper_with_reused_hash_fails_construction() -> None:
    entries = complete_entries()
    original = sealed_bundle(entries)
    tampered = list(entries)
    tampered[5] = EvidenceEntry(kind=tampered[5].kind, ref=ref("f"))
    with pytest.raises(EvidenceDomainError):
        EvidenceBundleManifest(
            tenant_id=original.tenant_id,
            run_id=original.run_id,
            experiment_id=original.experiment_id,
            entries=tuple(tampered),
            manifest_hash=original.manifest_hash,  # stale head
        )


def test_verify_localizes_first_divergence_index() -> None:
    # tamper entry at index 5 but keep the ORIGINAL sealed chain attached
    # (model_construct bypasses the construction gate, simulating a manifest
    # tampered in-flight) → verify must localize the divergence to index 5.
    entries = complete_entries()
    original = sealed_bundle(entries)
    tampered = list(entries)
    tampered[5] = EvidenceEntry(kind=tampered[5].kind, ref=ref("f"))
    forged = EvidenceBundleManifest.model_construct(
        tenant_id=original.tenant_id,
        run_id=original.run_id,
        experiment_id=original.experiment_id,
        entries=tuple(tampered),
        entry_commitments=original.entry_commitments,
        manifest_hash=original.manifest_hash,
    )
    ok, idx = verify_manifest(forged)
    assert ok is False
    assert idx == 5


def test_verify_localizes_reorder_to_first_moved_position() -> None:
    # swap entries 1 and 2, keep the original sealed chain → the first
    # divergent commitment is at index 1 (index 0 is untouched and matches)
    entries = complete_entries()
    original = sealed_bundle(entries)
    reordered = (entries[0], entries[2], entries[1], *entries[3:])
    forged = EvidenceBundleManifest.model_construct(
        tenant_id=original.tenant_id,
        run_id=original.run_id,
        experiment_id=original.experiment_id,
        entries=reordered,
        entry_commitments=original.entry_commitments,
        manifest_hash=original.manifest_hash,
    )
    ok, idx = verify_manifest(forged)
    assert ok is False
    assert idx == 1


def test_verify_localizes_splice_removal_at_removed_index() -> None:
    # remove the middle entry (index 3), keep the original sealed chain →
    # first divergence is at index 3 where the chains stop lining up
    entries = complete_entries()
    original = sealed_bundle(entries)
    spliced = (*entries[:3], *entries[4:])
    forged = EvidenceBundleManifest.model_construct(
        tenant_id=original.tenant_id,
        run_id=original.run_id,
        experiment_id=original.experiment_id,
        entries=spliced,
        entry_commitments=original.entry_commitments,
        manifest_hash=original.manifest_hash,
    )
    ok, idx = verify_manifest(forged)
    assert ok is False
    assert idx == 3


def test_verify_head_only_tamper_reports_none_index() -> None:
    # per-entry commitments all intact, only the stored head forged →
    # (False, None): no entry diverged, the manifest_hash field itself did
    original = sealed_bundle()
    forged = EvidenceBundleManifest.model_construct(
        tenant_id=original.tenant_id,
        run_id=original.run_id,
        experiment_id=original.experiment_id,
        entries=original.entries,
        entry_commitments=original.entry_commitments,
        manifest_hash="sha256:" + "9" * 64,
    )
    ok, idx = verify_manifest(forged)
    assert ok is False
    assert idx is None


def test_verify_forged_empty_bundle_with_bogus_hash() -> None:
    forged = EvidenceBundleManifest.model_construct(
        tenant_id="t",
        run_id="r",
        experiment_id="e",
        entries=(),
        entry_commitments=(),
        manifest_hash="sha256:" + "9" * 64,
    )
    ok, idx = verify_manifest(forged)
    assert ok is False
    assert idx is None


def test_append_after_seal_frozen_and_forced_append_is_tamper_evident() -> None:
    m = sealed_bundle()
    # ordinary assignment is rejected by the frozen model
    with pytest.raises(ValidationError):
        m.entries = (*m.entries, entry(EvidenceKind.ROLLBACK))
    # a force-mutation bypassing pydantic (object.__setattr__) CAN alter the
    # object in memory — the guarantee is tamper-EVIDENCE, not physical
    # immutability: verify_manifest catches it, localized to the appended
    # position (= original length)
    forced = m.model_copy()
    object.__setattr__(forced, "entries", (*m.entries, entry(EvidenceKind.ROLLBACK)))
    ok, idx = verify_manifest(forced)
    assert ok is False
    assert idx == len(m.entries)


def test_manifest_construction_rejects_wrong_hash() -> None:
    entries = complete_entries()
    with pytest.raises(EvidenceDomainError):
        EvidenceBundleManifest(
            tenant_id="t",
            run_id="r",
            experiment_id="e",
            entries=entries,
            manifest_hash="sha256:" + "0" * 64,
        )


def test_manifest_construction_rejects_none_hash_for_nonempty() -> None:
    with pytest.raises(EvidenceDomainError):
        EvidenceBundleManifest(
            tenant_id="t",
            run_id="r",
            experiment_id="e",
            entries=complete_entries(),
            manifest_hash=None,
        )


# --- completeness -----------------------------------------------------------


def test_complete_bundle_reports_complete() -> None:
    ok, missing = validate_completeness(sealed_bundle())
    assert ok is True
    assert missing == frozenset()


def test_incomplete_bundle_reports_missing_kinds_honestly() -> None:
    entries = tuple(e for e in complete_entries() if e.kind is not EvidenceKind.DID_OUTPUTS)
    m = sealed_bundle(entries)
    ok, missing = validate_completeness(m)
    assert ok is False
    assert EvidenceKind.DID_OUTPUTS in missing


def test_missingness_report_does_not_satisfy_required_kinds() -> None:
    # a bundle with ONLY a missingness_report is incomplete, and the report
    # kind never counts toward any required kind
    m = sealed_bundle((entry(EvidenceKind.MISSINGNESS_REPORT),))
    ok, missing = validate_completeness(m)
    assert ok is False
    assert missing == REQUIRED_B_GATE_KINDS
    assert EvidenceKind.MISSINGNESS_REPORT not in REQUIRED_B_GATE_KINDS


def test_empty_bundle_missing_all_required_kinds() -> None:
    m = EvidenceBundleManifest.seal(tenant_id="t", run_id="r", experiment_id="e", entries=())
    ok, missing = validate_completeness(m)
    assert ok is False
    assert missing == REQUIRED_B_GATE_KINDS


# --- tenant-scoped retrieval: non-leaking -----------------------------------


def test_entry_for_tenant_returns_entry_on_match() -> None:
    m = sealed_bundle()
    got = entry_for_tenant(m, tenant_id="acme-co", index=0)
    assert got is m.entries[0]


def test_cross_tenant_read_returns_none_non_leaking() -> None:
    m = sealed_bundle()
    # wrong tenant → None, indistinguishable from absent
    assert entry_for_tenant(m, tenant_id="other-co", index=0) is None


def test_cross_tenant_read_out_of_range_also_none() -> None:
    m = sealed_bundle()
    # both "wrong tenant" and "out of range" yield the SAME None answer
    assert entry_for_tenant(m, tenant_id="other-co", index=999) is None
    assert entry_for_tenant(m, tenant_id="acme-co", index=999) is None


def test_entry_for_tenant_negative_index_none() -> None:
    m = sealed_bundle()
    assert entry_for_tenant(m, tenant_id="acme-co", index=-1) is None


# --- metadata helper --------------------------------------------------------


def test_has_explicit_citation_decision_variants() -> None:
    assert EvidenceMetadata(citation="x").has_explicit_citation_decision() is True
    assert EvidenceMetadata(citation_present=False).has_explicit_citation_decision() is True
    assert EvidenceMetadata(citation_present=True).has_explicit_citation_decision() is True
    assert EvidenceMetadata().has_explicit_citation_decision() is False


def test_metadata_extra_clean_is_accepted() -> None:
    md = EvidenceMetadata(extra={"snapshot_ref": "s3://snap/1", "locale": "en-US"})
    assert md.extra is not None
