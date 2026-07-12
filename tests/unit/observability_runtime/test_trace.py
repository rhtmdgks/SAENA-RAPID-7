"""Tests for saena_observability.trace — trace_id validation/generation,
W3C traceparent parse/build, 3-way correlation helpers (ADR-0016)."""

from __future__ import annotations

import pytest
from saena_observability.trace import (
    build_traceparent,
    current_span_id,
    current_trace_id,
    generate_span_id,
    generate_trace_id,
    is_valid_span_id,
    is_valid_trace_id,
    parse_traceparent,
)

VALID_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
VALID_SPAN_ID = "00f067aa0ba902b7"


class TestTraceIdValidation:
    def test_valid_lowercase_hex_32(self) -> None:
        assert is_valid_trace_id(VALID_TRACE_ID) is True

    def test_all_zero_is_invalid(self) -> None:
        assert is_valid_trace_id("0" * 32) is False

    def test_uppercase_is_invalid(self) -> None:
        assert is_valid_trace_id(VALID_TRACE_ID.upper()) is False

    def test_wrong_length_is_invalid(self) -> None:
        assert is_valid_trace_id(VALID_TRACE_ID[:-1]) is False

    def test_non_hex_chars_invalid(self) -> None:
        assert is_valid_trace_id("g" * 32) is False


class TestSpanIdValidation:
    def test_valid_lowercase_hex_16(self) -> None:
        assert is_valid_span_id(VALID_SPAN_ID) is True

    def test_all_zero_is_invalid(self) -> None:
        assert is_valid_span_id("0" * 16) is False

    def test_wrong_length_is_invalid(self) -> None:
        assert is_valid_span_id(VALID_SPAN_ID + "0") is False


class TestGeneration:
    def test_generate_trace_id_is_valid(self) -> None:
        assert is_valid_trace_id(generate_trace_id()) is True

    def test_generate_trace_id_is_not_deterministic(self) -> None:
        assert generate_trace_id() != generate_trace_id()

    def test_generate_span_id_is_valid(self) -> None:
        assert is_valid_span_id(generate_span_id()) is True


class TestTraceparentBuildParse:
    def test_build_then_parse_round_trips(self) -> None:
        header = build_traceparent(VALID_TRACE_ID, VALID_SPAN_ID, sampled=True)
        assert header == f"00-{VALID_TRACE_ID}-{VALID_SPAN_ID}-01"
        parsed = parse_traceparent(header)
        assert parsed.trace_id == VALID_TRACE_ID
        assert parsed.span_id == VALID_SPAN_ID
        assert parsed.is_sampled() is True

    def test_unsampled_flag(self) -> None:
        header = build_traceparent(VALID_TRACE_ID, VALID_SPAN_ID, sampled=False)
        parsed = parse_traceparent(header)
        assert parsed.is_sampled() is False

    def test_build_rejects_invalid_trace_id(self) -> None:
        with pytest.raises(ValueError, match="invalid trace_id"):
            build_traceparent("not-hex", VALID_SPAN_ID)

    def test_build_rejects_invalid_span_id(self) -> None:
        with pytest.raises(ValueError, match="invalid span_id"):
            build_traceparent(VALID_TRACE_ID, "not-hex")

    def test_parse_rejects_malformed_header(self) -> None:
        with pytest.raises(ValueError, match="malformed traceparent"):
            parse_traceparent("not-a-traceparent-header")

    def test_parse_rejects_all_zero_trace_id(self) -> None:
        with pytest.raises(ValueError, match="invalid .* trace_id"):
            parse_traceparent(f"00-{'0' * 32}-{VALID_SPAN_ID}-01")

    def test_parse_rejects_all_zero_span_id(self) -> None:
        with pytest.raises(ValueError, match="invalid .* span_id"):
            parse_traceparent(f"00-{VALID_TRACE_ID}-{'0' * 16}-01")

    def test_parse_example_from_w3c_spec(self) -> None:
        # Canonical example from the W3C Trace Context specification.
        header = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        parsed = parse_traceparent(header)
        assert parsed.version == "00"
        assert parsed.trace_id == VALID_TRACE_ID
        assert parsed.span_id == VALID_SPAN_ID


class TestCurrentTraceCorrelation:
    def test_current_trace_id_none_without_active_span(self) -> None:
        assert current_trace_id() is None

    def test_current_span_id_none_without_active_span(self) -> None:
        assert current_span_id() is None

    def test_current_trace_id_matches_active_sdk_span(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.correlation") as span:
            expected_trace_id = f"{span.get_span_context().trace_id:032x}"
            expected_span_id = f"{span.get_span_context().span_id:016x}"
            assert current_trace_id() == expected_trace_id
            assert current_span_id() == expected_span_id
        assert current_trace_id() is None
