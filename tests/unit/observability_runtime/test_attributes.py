"""Tests for saena_observability.attributes — the redaction-routed OTel
Span.set_attribute wrapper (ADR-0016)."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from saena_observability.attributes import set_redacted_attribute, set_redacted_attributes
from saena_observability.context import TelemetryContext, bind_telemetry_context
from saena_observability.redaction import REDACTED_VALUE, RedactionAction


class TestSetRedactedAttribute:
    def test_allowed_attribute_is_set_on_span(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.attributes") as span:
            action = set_redacted_attribute(
                span,
                "saena.tenant_id",
                "acme",
                telemetry_context=TelemetryContext(context="tenant", tenant_id="acme"),
            )
            assert action is RedactionAction.ALLOW
            assert span.attributes["saena.tenant_id"] == "acme"

    def test_dropped_attribute_is_not_set_on_span(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.attributes") as span:
            action = set_redacted_attribute(
                span,
                "saena.tenant_id",
                "acme",
                telemetry_context=TelemetryContext(context="aggregate"),
            )
            assert action is RedactionAction.DROP
            assert "saena.tenant_id" not in (span.attributes or {})

    def test_secret_value_is_redacted_on_span(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.attributes") as span:
            action = set_redacted_attribute(
                span,
                "saena.contract_hash",
                "bearer sometoken",
                telemetry_context=TelemetryContext(context="tenant", tenant_id="acme"),
            )
            assert action is RedactionAction.REDACT_VALUE
            assert span.attributes["saena.contract_hash"] == REDACTED_VALUE

    def test_uses_bound_context_when_not_passed_explicitly(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with (
            bind_telemetry_context("aggregate"),
            tracer.start_as_current_span("saena.test.attributes") as span,
        ):
            action = set_redacted_attribute(span, "saena.tenant_id", "acme")
            assert action is RedactionAction.DROP

    def test_unregistered_attribute_is_dropped(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.attributes") as span:
            action = set_redacted_attribute(
                span,
                "saena.not_a_real_attribute",
                "value",
                telemetry_context=TelemetryContext(context="tenant", tenant_id="acme"),
            )
            assert action is RedactionAction.DROP
            assert "saena.not_a_real_attribute" not in (span.attributes or {})


class TestSetRedactedAttributes:
    def test_batch_applies_per_attribute_decisions(self) -> None:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("saena.test.attributes") as span:
            results = set_redacted_attributes(
                span,
                {
                    "saena.tenant_id": "acme",
                    "saena.not_registered": "x",
                },
                telemetry_context=TelemetryContext(context="tenant", tenant_id="acme"),
            )
            assert results == {
                "saena.tenant_id": RedactionAction.ALLOW,
                "saena.not_registered": RedactionAction.DROP,
            }
            assert span.attributes["saena.tenant_id"] == "acme"
            assert "saena.not_registered" not in span.attributes
