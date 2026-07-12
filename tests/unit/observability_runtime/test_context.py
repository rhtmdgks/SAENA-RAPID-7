"""Tests for saena_observability.context (ADR-0016 required attrs, ADR-0013
context rules)."""

from __future__ import annotations

import pytest
from saena_observability.context import (
    TelemetryContext,
    bind_telemetry_context,
    current_telemetry_context,
)


class TestBindTenantContext:
    def test_tenant_context_binds_tenant_and_run_id(self) -> None:
        assert current_telemetry_context() is None
        with bind_telemetry_context("tenant", tenant_id="acme", run_id="run-1") as ctx:
            assert ctx == TelemetryContext(
                context="tenant", tenant_id="acme", run_id="run-1", engine_id=None
            )
            assert current_telemetry_context() == ctx
        assert current_telemetry_context() is None

    def test_tenant_context_requires_tenant_id(self) -> None:
        with (
            pytest.raises(ValueError, match="requires saena.tenant_id"),
            bind_telemetry_context("tenant", run_id="run-1"),
        ):
            pass

    def test_tenant_context_accepts_engine_id(self) -> None:
        with bind_telemetry_context(
            "tenant", tenant_id="acme", run_id="run-1", engine_id="chatgpt-search"
        ) as ctx:
            assert ctx.engine_id == "chatgpt-search"


class TestBindSystemContext:
    def test_system_context_forbids_tenant_id(self) -> None:
        with (
            pytest.raises(ValueError, match="tenant_id"),
            bind_telemetry_context("system", tenant_id="acme"),
        ):
            pass

    def test_system_context_forbids_run_id(self) -> None:
        with (
            pytest.raises(ValueError, match="run_id"),
            bind_telemetry_context("system", run_id="run-1"),
        ):
            pass

    def test_system_context_binds_with_no_identifiers(self) -> None:
        with bind_telemetry_context("system") as ctx:
            assert ctx.tenant_id is None
            assert ctx.run_id is None
            assert ctx.context == "system"


class TestBindAggregateContext:
    def test_aggregate_context_forbids_tenant_id(self) -> None:
        with (
            pytest.raises(ValueError, match="tenant_id"),
            bind_telemetry_context("aggregate", tenant_id="acme"),
        ):
            pass

    def test_aggregate_context_forbids_run_id(self) -> None:
        with (
            pytest.raises(ValueError, match="run_id"),
            bind_telemetry_context("aggregate", run_id="run-1"),
        ):
            pass

    def test_aggregate_context_forbids_both_at_once(self) -> None:
        with (
            pytest.raises(ValueError) as exc_info,
            bind_telemetry_context("aggregate", tenant_id="acme", run_id="run-1"),
        ):
            pass
        assert "tenant_id" in str(exc_info.value)
        assert "run_id" in str(exc_info.value)

    def test_aggregate_context_binds_with_no_identifiers(self) -> None:
        with bind_telemetry_context("aggregate") as ctx:
            assert ctx.tenant_id is None
            assert ctx.run_id is None
            assert ctx.context == "aggregate"


class TestContextIsolation:
    def test_nested_context_restores_outer_on_exit(self) -> None:
        with bind_telemetry_context("tenant", tenant_id="outer", run_id="run-outer") as outer:
            with bind_telemetry_context("system") as inner:
                assert current_telemetry_context() == inner
            assert current_telemetry_context() == outer
        assert current_telemetry_context() is None

    def test_failed_bind_does_not_leak_context(self) -> None:
        with bind_telemetry_context("tenant", tenant_id="acme", run_id="run-1") as outer:
            with pytest.raises(ValueError), bind_telemetry_context("aggregate", tenant_id="acme"):
                pass
            # The failed inner bind must not have mutated the outer context.
            assert current_telemetry_context() == outer
