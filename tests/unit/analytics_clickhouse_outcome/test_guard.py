"""Unit tests: `MeasurementOutcomeRow` construction rejects raw/secret content
via `guard_row_fields` (w5-11) — same fail-closed enforcement point every
sibling row in `rows.py` uses (`__post_init__` is where the guard runs, so a
row that fails it can never reach `query.py`'s INSERT builder)."""

from __future__ import annotations

import pytest
from analytics_clickhouse_outcome_factories import make_measurement_outcome_row
from saena_analytics_clickhouse.errors import RawContentRejectedError
from saena_analytics_clickhouse.guard import guard_row_fields


class TestForbiddenFieldNameRejection:
    def test_ordinary_experiment_id_value_is_not_rejected(self) -> None:
        """Control: `guard_row_fields` checks field NAME/VALUE shape, not an
        arbitrary business string — an ordinary `experiment_id` value must
        construct cleanly (this is the negative-control for every positive
        rejection test below)."""
        row = make_measurement_outcome_row(experiment_id="exp-ordinary-123")
        assert row.experiment_id == "exp-ordinary-123"

    def test_evidence_basis_id_holding_a_secret_shaped_value_is_rejected(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_measurement_outcome_row(evidence_basis_id="sk-" + "a" * 40)

    def test_registration_canonical_hash_holding_a_jwt_shaped_value_is_rejected(self) -> None:
        jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ12345678"
        with pytest.raises(RawContentRejectedError):
            make_measurement_outcome_row(registration_canonical_hash=jwt_like)

    def test_grs_policy_provenance_holding_an_aws_key_is_rejected(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_measurement_outcome_row(grs_policy_provenance="AKIA" + "B" * 16)

    def test_oversize_field_value_is_rejected(self) -> None:
        """Exercises `guard_row_fields` directly (not via row construction):
        every string field `rows.py` validates has its own smaller
        `max_length` cap (<=512 chars) that would raise `RowValidationError`
        first, before a 5000-char value could ever reach the guard's own
        4096-char oversize-blob threshold — so this proves the GUARD's
        oversize check itself, the same way `guard_row_fields` is unit-tested
        for every sibling row type in this package."""
        with pytest.raises(RawContentRejectedError) as exc_info:
            guard_row_fields({"metadata": "x" * 5000})
        assert exc_info.value.context["reason"] == "oversize_blob"

    def test_reason_code_holding_a_github_token_is_rejected(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_measurement_outcome_row(reason_codes=("ghp_" + "a" * 36,))

    def test_error_never_echoes_the_offending_value(self) -> None:
        secret = "sk-" + "z" * 40
        with pytest.raises(RawContentRejectedError) as exc_info:
            make_measurement_outcome_row(evidence_basis_id=secret)
        message = str(exc_info.value)
        assert secret not in message
        assert secret not in str(exc_info.value.context)
