"""Tests for saena_observability.naming — span/metric name validators
(ADR-0016 naming rules: `saena.<capability>.<operation>` /
`saena.<domain>.<name>`, low-cardinality only, no embedded identifiers)."""

from __future__ import annotations

import pytest
from saena_observability.naming import (
    is_valid_metric_name,
    is_valid_span_name,
    validate_metric_name,
    validate_span_name,
)


class TestSpanNameValidation:
    def test_valid_two_segment_name(self) -> None:
        assert is_valid_span_name("saena.retrieval.query") is True

    def test_valid_multi_segment_name(self) -> None:
        assert is_valid_span_name("saena.retrieval.query.execute") is True

    def test_missing_namespace_prefix_is_invalid(self) -> None:
        assert is_valid_span_name("retrieval.query") is False

    def test_single_segment_is_invalid(self) -> None:
        assert is_valid_span_name("saena.retrieval") is False

    def test_uppercase_segment_is_invalid(self) -> None:
        assert is_valid_span_name("saena.Retrieval.Query") is False

    def test_segment_starting_with_digit_is_invalid(self) -> None:
        assert is_valid_span_name("saena.1retrieval.query") is False

    def test_embedded_uuid_is_invalid(self) -> None:
        assert is_valid_span_name("saena.retrieval.018f3a1e-7c2b-7c3e-9b1a-4e2f1a9d3c7b") is False

    def test_embedded_long_hex_run_is_invalid(self) -> None:
        assert is_valid_span_name("saena.retrieval.4bf92f3577b34da6") is False

    def test_bare_namespace_with_nothing_after_prefix_is_invalid(self) -> None:
        assert is_valid_span_name("saena.") is False

    def test_validate_raises_with_reason(self) -> None:
        with pytest.raises(ValueError, match="invalid span name"):
            validate_span_name("bad-name")

    def test_validate_raises_with_bare_namespace_reason(self) -> None:
        with pytest.raises(ValueError, match="at least one segment"):
            validate_span_name("saena.")

    def test_validate_raises_with_embedded_identifier_reason(self) -> None:
        # Segment must start with a lowercase letter to pass the base
        # shape check before the identifier-shape heuristic applies —
        # "affe..." starts with a letter but is still a long hex run.
        with pytest.raises(ValueError, match="looks like an embedded identifier"):
            validate_span_name("saena.retrieval.affe92f3577b34da")

    def test_validate_passes_silently_for_valid_name(self) -> None:
        validate_span_name("saena.retrieval.query")  # no raise


class TestMetricNameValidation:
    def test_valid_domain_name(self) -> None:
        assert is_valid_metric_name("saena.retrieval.latency") is True

    def test_missing_prefix_is_invalid(self) -> None:
        assert is_valid_metric_name("retrieval.latency") is False

    def test_single_segment_is_invalid(self) -> None:
        assert is_valid_metric_name("saena.latency") is False

    def test_embedded_identifier_is_invalid(self) -> None:
        assert is_valid_metric_name("saena.retrieval.2b1c7d4a8e6f1a2b") is False

    def test_validate_raises_with_reason(self) -> None:
        with pytest.raises(ValueError, match="invalid metric name"):
            validate_metric_name("saena.onesegment")

    def test_validate_passes_silently_for_valid_name(self) -> None:
        validate_metric_name("saena.retrieval.latency")  # no raise
