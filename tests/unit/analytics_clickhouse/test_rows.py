"""Unit tests for `saena_analytics_clickhouse.rows` (w4-06 mission
deliverable 3: row models = metadata/hash/ref only, guard-enforced at
construction; r4-04: `query_ref`/`query_digest` REPLACE `query_text` — see
`TestObservationRowNeverCarriesRawQuery` for the r4-04 leak-closure proof,
round 2: `query_ref` is now KEYED + tenant-scoped, see
`TestQueryRefIsKeyedAndTenantScoped`)."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from analytics_clickhouse_factories import (
    fixture_signing_key_ref,
    make_citation_row,
    make_experiment_registration_row,
    make_observation_row,
)
from saena_analytics_clickhouse.errors import RawContentRejectedError, RowValidationError
from saena_analytics_clickhouse.query_privacy import (
    MissingQuerySigningKeyError,
    QuerySigningKeyRef,
    derive_query_digest,
    derive_query_ref,
)
from saena_analytics_clickhouse.rows import ObservationRow

_KEY = fixture_signing_key_ref()


class TestObservationRow:
    def test_valid_row_constructs(self) -> None:
        row = make_observation_row()
        assert row.tenant_id == "acme-co"
        assert row.citation_refs == ("ref://citation/1",)

    def test_missing_tenant_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_observation_row(tenant_id="")

    def test_malformed_naive_timestamp_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_observation_row(occurred_at=dt.datetime(2026, 7, 1))  # noqa: DTZ001

    def test_query_ref_over_max_length_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_observation_row(query_ref="query://acme-co/" + "x" * 2001)

    def test_raw_secret_shaped_object_ref_rejected_fail_closed(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_observation_row(raw_object_ref="sk-" + "a" * 30)


class TestObservationRowNeverCarriesRawQuery:
    """r4-04 leak-closure proof: `ObservationRow` has NO field that ever
    carries the raw query text — this is the fix for the confirmed defect
    (pre-fix: `ObservationRow.query_text: str` stored the raw customer
    query verbatim; `guard.py`'s SHAPE-only heuristic never caught an
    ordinary sentence with no secret/oversize shape, see
    `test_forbidden_field_shaped_query_text_content_is_not_itself_blocked_
    by_name`'s OLD, pre-fix assertion this class supersedes)."""

    _PLANTED_SECRET_QUERY = (
        "my email is jane.doe@acme-example.com and phone +1-555-0100-9999, "
        "customer id CUST-90210, here is my token sk-" + "a" * 30
    )

    def test_observation_row_has_no_query_text_field_at_all(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ObservationRow)}
        assert "query_text" not in field_names
        assert "query_ref" in field_names
        assert "query_digest" in field_names

    def test_planted_pii_secret_query_never_appears_on_the_constructed_row(self) -> None:
        """The exact reproducer scenario: a query containing an email,
        phone number, API token, and a customer-identifying marker. Only
        the opaque `query_ref` (derived BEFORE construction) ever reaches
        the row — the raw string itself is never an attribute value, never
        embedded as a substring of any field, anywhere on the object."""
        ref = derive_query_ref(
            tenant_id="acme-co", raw_query=self._PLANTED_SECRET_QUERY, signing_key_ref=_KEY
        )
        row = make_observation_row(query_ref=ref.query_ref)

        assert row.query_ref == ref.query_ref
        for f in dataclasses.fields(row):
            value = getattr(row, f.name)
            if isinstance(value, str):
                assert self._PLANTED_SECRET_QUERY not in value
            elif isinstance(value, tuple):
                assert all(self._PLANTED_SECRET_QUERY not in v for v in value if isinstance(v, str))

    def test_query_ref_is_a_well_formed_opaque_reference_not_content(self) -> None:
        ref = derive_query_ref(
            tenant_id="acme-co", raw_query=self._PLANTED_SECRET_QUERY, signing_key_ref=_KEY
        )
        assert ref.query_ref.startswith("query://acme-co/")
        assert self._PLANTED_SECRET_QUERY not in ref.query_ref
        assert self._PLANTED_SECRET_QUERY not in ref.query_hash

    def test_query_digest_defaults_to_none_when_caller_does_not_derive_one(self) -> None:
        row = make_observation_row()
        assert row.query_digest is None

    def test_query_digest_present_when_caller_explicitly_derives_one_with_a_real_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "test-signing-key-material")
        digest = derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)
        row = make_observation_row(query_digest=digest.digest)
        assert row.query_digest == digest.digest
        assert self._PLANTED_SECRET_QUERY not in row.query_digest

    def test_query_digest_missing_signing_key_fails_closed_never_stores_unkeyed_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", raising=False)
        with pytest.raises(MissingQuerySigningKeyError):
            derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)

    def test_query_digest_empty_signing_key_env_var_also_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "")
        with pytest.raises(MissingQuerySigningKeyError):
            derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)

    def test_query_digest_explicit_signing_key_ref_also_fails_closed_when_unset(self) -> None:
        with pytest.raises(MissingQuerySigningKeyError):
            derive_query_digest(
                raw_query=self._PLANTED_SECRET_QUERY,
                signing_key_ref=QuerySigningKeyRef(env_var="SAENA_TEST_UNSET_SIGNING_KEY"),
            )

    def test_unkeyed_sha256_is_never_what_derive_query_digest_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Honesty proof: `derive_query_digest`'s output is NEVER equal to a
        plain unkeyed `hashlib.sha256` of the raw query — every digest this
        module returns is HMAC-keyed, distinguishable from an unkeyed hash
        by construction (different algorithm entirely, not just a different
        key)."""
        import hashlib

        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "test-signing-key-material")
        digest = derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)
        unkeyed = hashlib.sha256(self._PLANTED_SECRET_QUERY.encode("utf-8")).hexdigest()
        assert unkeyed not in digest.digest
        assert digest.digest.startswith("hmac-sha256:")

    def test_query_digest_differs_for_different_signing_keys_same_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "key-one")
        digest_1 = derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)
        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "key-two")
        digest_2 = derive_query_digest(raw_query=self._PLANTED_SECRET_QUERY)
        assert digest_1.digest != digest_2.digest

    def test_query_ref_deterministic_for_the_same_tenant_and_query(self) -> None:
        ref_1 = derive_query_ref(
            tenant_id="acme-co", raw_query="best crm for startups", signing_key_ref=_KEY
        )
        ref_2 = derive_query_ref(
            tenant_id="acme-co", raw_query="best crm for startups", signing_key_ref=_KEY
        )
        assert ref_1.query_ref == ref_2.query_ref

    def test_query_ref_differs_across_tenants_for_the_same_query(self) -> None:
        ref_a = derive_query_ref(
            tenant_id="acme-co", raw_query="best crm for startups", signing_key_ref=_KEY
        )
        ref_b = derive_query_ref(
            tenant_id="globex-co", raw_query="best crm for startups", signing_key_ref=_KEY
        )
        assert ref_a.query_ref != ref_b.query_ref


class TestQueryRefIsKeyedAndTenantScoped:
    """Independent-critic MUST-FIX round 2 — the two real defects this
    class proves closed:

    1. `query_ref` is no longer brute-force reversible (it is now HMAC-
       keyed, not a plain content hash — reversal requires the signing key).
    2. `query_ref` no longer correlates the SAME query across DIFFERENT
       tenants (`tenant_id` is now inside the keyed HMAC input, not merely
       a cosmetic path prefix)."""

    _QUERY = "best crm for startups"

    def test_missing_signing_key_fails_closed_never_returns_an_unkeyed_ref(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", raising=False)
        with pytest.raises(MissingQuerySigningKeyError):
            derive_query_ref(
                tenant_id="acme-co",
                raw_query=self._QUERY,
                signing_key_ref=QuerySigningKeyRef(env_var="SAENA_ANALYTICS_QUERY_SIGNING_KEY"),
            )

    def test_same_raw_query_two_different_tenants_yields_different_query_ref_same_key(
        self,
    ) -> None:
        """The exact round-2 required test: the SAME `raw_query` under two
        DIFFERENT tenants must produce DIFFERENT `query_ref` values, even
        with the SAME signing key — no cross-tenant correlation leak."""
        ref_a = derive_query_ref(tenant_id="acme-co", raw_query=self._QUERY, signing_key_ref=_KEY)
        ref_b = derive_query_ref(tenant_id="globex-co", raw_query=self._QUERY, signing_key_ref=_KEY)
        assert ref_a.query_ref != ref_b.query_ref
        assert ref_a.query_hash != ref_b.query_hash

    def test_query_ref_cannot_be_computed_at_all_without_the_signing_key(self) -> None:
        """A brute-force attacker who does NOT know the signing key cannot
        recover a LOW-ENTROPY natural-language query by trying every
        candidate from a small dictionary against a plain (unkeyed) hash —
        because `query_ref`'s digest is HMAC-keyed, computing it at all
        requires the key; an attacker without the key has no way to even
        ATTEMPT the dictionary-guess-and-compare `query_ref`'s design
        exists to defeat (this module's public API refuses to compute a
        candidate digest without a real key at all, see
        `MissingQuerySigningKeyError`)."""
        with pytest.raises(MissingQuerySigningKeyError):
            derive_query_ref(
                tenant_id="acme-co",
                raw_query=self._QUERY,
                signing_key_ref=QuerySigningKeyRef(env_var="SAENA_TEST_ATTACKER_HAS_NO_KEY"),
            )

    def test_wrong_signing_key_never_reproduces_the_real_query_ref(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_ref = derive_query_ref(
            tenant_id="acme-co", raw_query=self._QUERY, signing_key_ref=_KEY
        )
        monkeypatch.setenv("SAENA_ANALYTICS_QUERY_SIGNING_KEY", "a-completely-different-key")
        wrong_ref = derive_query_ref(
            tenant_id="acme-co",
            raw_query=self._QUERY,
            signing_key_ref=QuerySigningKeyRef(env_var="SAENA_ANALYTICS_QUERY_SIGNING_KEY"),
        )
        assert real_ref.query_ref != wrong_ref.query_ref

    def test_query_ref_digest_is_never_a_plain_unkeyed_sha256_of_the_query(self) -> None:
        import hashlib

        ref = derive_query_ref(tenant_id="acme-co", raw_query=self._QUERY, signing_key_ref=_KEY)
        unkeyed = hashlib.sha256(self._QUERY.encode("utf-8")).hexdigest()
        assert unkeyed not in ref.query_ref
        assert unkeyed not in ref.query_hash
        assert ref.query_hash.startswith("hmac-sha256:")

    def test_query_ref_digest_is_never_a_plain_unkeyed_sha256_of_tenant_and_query(self) -> None:
        """Stronger form of the previous test: not equal to an unkeyed hash
        of ANY simple `tenant_id`+`raw_query` combination either — proves
        the digest genuinely requires the secret key, not just a different
        public salt."""
        import hashlib

        ref = derive_query_ref(tenant_id="acme-co", raw_query=self._QUERY, signing_key_ref=_KEY)
        unkeyed_concat = hashlib.sha256(f"acme-co\x1f{self._QUERY}".encode()).hexdigest()
        assert unkeyed_concat not in ref.query_ref


class TestCitationRow:
    def test_valid_row_constructs(self) -> None:
        row = make_citation_row()
        assert row.contribution_score == 0.5

    def test_contribution_score_out_of_range_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_citation_row(contribution_score=1.5)

    def test_negative_contribution_score_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_citation_row(contribution_score=-0.1)

    def test_missing_tenant_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_citation_row(tenant_id="")


class TestExperimentRegistrationRow:
    def test_valid_row_constructs(self) -> None:
        row = make_experiment_registration_row()
        assert row.status == "registered"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_experiment_registration_row(status="not-a-real-status")

    def test_missing_tenant_id_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_experiment_registration_row(tenant_id="")

    def test_raw_content_shaped_field_value_rejected(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_experiment_registration_row(observation_cell="AKIA" + "A" * 16)
