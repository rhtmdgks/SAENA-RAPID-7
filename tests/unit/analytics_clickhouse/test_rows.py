"""Unit tests for `saena_analytics_clickhouse.rows` (w4-06 mission
deliverable 3: row models = metadata/hash/ref only, guard-enforced at
construction)."""

from __future__ import annotations

import datetime as dt

import pytest
from analytics_clickhouse_factories import (
    make_citation_row,
    make_experiment_registration_row,
    make_observation_row,
)
from saena_analytics_clickhouse.errors import RawContentRejectedError, RowValidationError


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

    def test_query_text_over_max_length_rejected(self) -> None:
        with pytest.raises(RowValidationError):
            make_observation_row(query_text="x" * 2001)

    def test_raw_secret_shaped_object_ref_rejected_fail_closed(self) -> None:
        with pytest.raises(RawContentRejectedError):
            make_observation_row(raw_object_ref="sk-" + "a" * 30)

    def test_forbidden_field_shaped_query_text_content_is_not_itself_blocked_by_name(
        self,
    ) -> None:
        # query_text is a legitimate field name (not in the forbidden-name
        # list) — only VALUE-shaped secrets or oversize blobs in it trigger
        # the guard, never the field's own name.
        row = make_observation_row(query_text="how do I rotate my api key safely")
        assert "api key" in row.query_text


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
