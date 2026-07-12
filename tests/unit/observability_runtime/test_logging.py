"""Tests for saena_observability.logging — structured single-line JSON logs
with implicit context pickup and redaction (ADR-0016)."""

from __future__ import annotations

import json
import logging as stdlib_logging

from saena_observability.context import bind_telemetry_context
from saena_observability.logging import SaenaJsonFormatter, get_logger
from saena_observability.redaction import REDACTED_VALUE


def _make_record(
    msg: str = "hello",
    *,
    args: tuple[object, ...] | None = None,
    **extra: object,
) -> stdlib_logging.LogRecord:
    record = stdlib_logging.LogRecord(
        name="test",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestBaseShape:
    def test_emits_single_line_json_with_required_fields(self) -> None:
        formatter = SaenaJsonFormatter()
        line = formatter.format(_make_record("hello world"))
        assert "\n" not in line
        payload = json.loads(line)
        assert payload["body"] == "hello world"
        assert payload["severity"] == "INFO"
        assert payload["timestamp"].endswith("Z")

    def test_timestamp_is_rfc3339_z_terminated(self) -> None:
        formatter = SaenaJsonFormatter()
        payload = json.loads(formatter.format(_make_record()))
        # RFC3339 Z-terminated per ADR-0013 rev.2 canonicalization — no
        # "+00:00" offset form.
        assert payload["timestamp"].endswith("Z")
        assert "+00:00" not in payload["timestamp"]


class TestLogBodyRedaction:
    """MUST-FIX 1 (critic): `logger.info("token=%s", token)` and f-string
    bodies must never leak a secret through the `body` field — the
    formatted message is scrubbed via `redact_text` before emission."""

    def test_secret_via_percent_style_interpolation_is_redacted(self) -> None:
        formatter = SaenaJsonFormatter()
        record = _make_record("token=%s", args=("abc123secretvalue",))
        line = formatter.format(record)
        assert "abc123secretvalue" not in line
        payload = json.loads(line)
        assert REDACTED_VALUE in payload["body"]

    def test_secret_via_fstring_body_is_redacted(self) -> None:
        formatter = SaenaJsonFormatter()
        secret = "abc123secretvalue"
        record = _make_record(f"authenticating with token={secret}")
        line = formatter.format(record)
        assert secret not in line
        payload = json.loads(line)
        assert REDACTED_VALUE in payload["body"]

    def test_clean_message_body_is_untouched(self) -> None:
        formatter = SaenaJsonFormatter()
        record = _make_record("run completed successfully")
        payload = json.loads(formatter.format(record))
        assert payload["body"] == "run completed successfully"

    def test_password_via_percent_style_interpolation_is_redacted(self) -> None:
        formatter = SaenaJsonFormatter()
        record = _make_record("login with password=%s", args=("hunter2secret",))
        line = formatter.format(record)
        assert "hunter2secret" not in line


class TestTenantContextCarriesTenantId:
    def test_tenant_context_log_carries_tenant_id_and_run_id(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("tenant", tenant_id="acme-co", run_id="run-1"):
            payload = json.loads(formatter.format(_make_record("tenant event")))
        assert payload["saena.tenant_id"] == "acme-co"
        assert payload["saena.run_id"] == "run-1"
        assert payload["saena.context"] == "tenant"

    def test_bound_engine_id_is_carried(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context(
            "tenant", tenant_id="acme-co", run_id="run-1", engine_id="chatgpt-search"
        ):
            payload = json.loads(formatter.format(_make_record("tenant event")))
        assert payload["saena.engine_id"] == "chatgpt-search"


class TestTraceCorrelationFields:
    def test_active_span_adds_trace_id_and_span_id_to_log(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        formatter = SaenaJsonFormatter()
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.logging") as span:
            expected_trace_id = f"{span.get_span_context().trace_id:032x}"
            expected_span_id = f"{span.get_span_context().span_id:016x}"
            payload = json.loads(formatter.format(_make_record("traced event")))
        assert payload["trace_id"] == expected_trace_id
        assert payload["span_id"] == expected_span_id

    def test_no_active_span_omits_trace_and_span_id(self) -> None:
        formatter = SaenaJsonFormatter()
        payload = json.loads(formatter.format(_make_record("untraced event")))
        assert "trace_id" not in payload
        assert "span_id" not in payload


class TestSystemContextHasNoTenantIdKey:
    def test_system_context_log_has_no_tenant_id_key(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("system"):
            payload = json.loads(formatter.format(_make_record("system event")))
        assert "saena.tenant_id" not in payload
        assert "saena.run_id" not in payload
        assert payload["saena.context"] == "system"

    def test_aggregate_context_log_has_no_tenant_id_key(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("aggregate"):
            payload = json.loads(
                formatter.format(
                    _make_record(
                        "aggregate event",
                        saena_attributes={"saena.aggregate_scope_id": "scope-1"},
                    )
                )
            )
        assert "saena.tenant_id" not in payload
        assert "saena.run_id" not in payload
        assert payload["saena.context"] == "aggregate"
        assert payload["saena.aggregate_scope_id"] == "scope-1"


class TestSecretLookingAttributeNeverAppears:
    def test_secret_value_is_redacted_not_raw(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("tenant", tenant_id="acme", run_id="run-1"):
            record = _make_record(
                "event",
                saena_attributes={"saena.contract_hash": "bearer abc123token"},
            )
            line = formatter.format(record)
        assert "abc123token" not in line
        payload = json.loads(line)
        assert payload["saena.contract_hash"] == REDACTED_VALUE

    def test_email_like_value_never_appears_raw(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("tenant", tenant_id="acme", run_id="run-1"):
            record = _make_record(
                "event",
                saena_attributes={"saena.contract_hash": "owner is a@example.com"},
            )
            line = formatter.format(record)
        assert "a@example.com" not in line


class TestNonAllowlistedAttributeSuppressed:
    def test_unregistered_attribute_is_absent_from_output(self) -> None:
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("tenant", tenant_id="acme", run_id="run-1"):
            record = _make_record("event", saena_attributes={"saena.totally_unregistered": "value"})
            payload = json.loads(formatter.format(record))
        assert "saena.totally_unregistered" not in payload

    def test_aggregate_context_drops_tenant_id_even_if_explicitly_passed_as_extra(
        self,
    ) -> None:
        # Defense in depth: even if a caller mistakenly attaches
        # saena.tenant_id via extra attributes under aggregate context, the
        # redaction engine's V-AGG-TENANT rule must still drop it.
        formatter = SaenaJsonFormatter()
        with bind_telemetry_context("aggregate"):
            record = _make_record("event", saena_attributes={"saena.tenant_id": "leaked-acme"})
            line = formatter.format(record)
        assert "leaked-acme" not in line
        payload = json.loads(line)
        assert "saena.tenant_id" not in payload


class TestGetLoggerIdempotent:
    def test_repeated_calls_do_not_stack_handlers(self) -> None:
        logger1 = get_logger("saena.observability.test_logger_idempotent")
        logger2 = get_logger("saena.observability.test_logger_idempotent")
        assert logger1 is logger2
        json_handlers = [h for h in logger1.handlers if isinstance(h.formatter, SaenaJsonFormatter)]
        assert len(json_handlers) == 1

    def test_logger_does_not_propagate_to_root(self) -> None:
        logger = get_logger("saena.observability.test_logger_no_propagate")
        assert logger.propagate is False
