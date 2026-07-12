"""Execution-context dataclasses + contextvars-based tenant propagation:
bind_tenant/current_tenant/require_tenant, asyncio task isolation.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import make_tenant_context_payload
from saena_domain.identity.errors import TenantMismatchError, UnboundTenantContextError
from saena_domain.identity.execution_context import (
    AggregateExecutionContext,
    SystemExecutionContext,
    TenantExecutionContext,
    bind_tenant,
    current_tenant,
    require_tenant,
)
from saena_domain.identity.tenant import TenantContext


def _tenant_context(tenant_id: str = "acme-corp") -> TenantContext:
    payload = make_tenant_context_payload(
        tenant_id=tenant_id, namespace=f"saena-tenant-{tenant_id}"
    )
    return TenantContext.from_payload(payload)


class TestTenantExecutionContext:
    def test_requires_tenant_and_run_id(self) -> None:
        ctx = TenantExecutionContext(tenant=_tenant_context(), run_id="run-0001")
        assert ctx.run_id == "run-0001"
        assert ctx.actor is None

    def test_is_frozen(self) -> None:
        ctx = TenantExecutionContext(tenant=_tenant_context(), run_id="run-0001")
        with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
            ctx.run_id = "run-0002"  # type: ignore[misc]


class TestSystemExecutionContext:
    def test_has_no_tenant_or_run_id_fields(self) -> None:
        ctx = SystemExecutionContext(producer="policy-gate")
        assert not hasattr(ctx, "tenant_id")
        assert not hasattr(ctx, "run_id")
        assert ctx.producer == "policy-gate"


class TestAggregateExecutionContext:
    def test_valid_construction(self) -> None:
        ctx = AggregateExecutionContext(
            aggregate_scope_id="aggregate-scope-014",
            cohort_size=12,
            privacy_threshold=5,
            lineage_audit_ref="sha256:" + "a" * 64,
        )
        assert ctx.cohort_size == 12

    def test_has_no_tenant_or_run_id_fields(self) -> None:
        ctx = AggregateExecutionContext(
            aggregate_scope_id="aggregate-scope-014",
            cohort_size=12,
            privacy_threshold=5,
            lineage_audit_ref="sha256:" + "a" * 64,
        )
        assert not hasattr(ctx, "tenant_id")
        assert not hasattr(ctx, "run_id")

    def test_rejects_cohort_size_below_one(self) -> None:
        with pytest.raises(ValueError, match="cohort_size"):
            AggregateExecutionContext(
                aggregate_scope_id="scope",
                cohort_size=0,
                privacy_threshold=5,
                lineage_audit_ref="sha256:" + "a" * 64,
            )

    def test_rejects_privacy_threshold_below_one(self) -> None:
        with pytest.raises(ValueError, match="privacy_threshold"):
            AggregateExecutionContext(
                aggregate_scope_id="scope",
                cohort_size=12,
                privacy_threshold=0,
                lineage_audit_ref="sha256:" + "a" * 64,
            )


class TestBindAndCurrentTenant:
    def test_current_tenant_raises_when_unbound(self) -> None:
        with pytest.raises(UnboundTenantContextError):
            current_tenant()

    def test_bind_tenant_makes_it_current(self) -> None:
        ctx = _tenant_context()
        with bind_tenant(ctx):
            assert current_tenant() is ctx

    def test_bind_tenant_restores_previous_binding_on_exit(self) -> None:
        with pytest.raises(UnboundTenantContextError):
            current_tenant()
        with bind_tenant(_tenant_context()):
            pass
        with pytest.raises(UnboundTenantContextError):
            current_tenant()

    def test_bind_tenant_restores_on_exception(self) -> None:
        with pytest.raises(RuntimeError), bind_tenant(_tenant_context()):
            raise RuntimeError("boom")
        with pytest.raises(UnboundTenantContextError):
            current_tenant()

    def test_nested_bind_tenant_restores_outer_binding(self) -> None:
        outer = _tenant_context("acme-corp")
        inner = _tenant_context("other-corp")
        with bind_tenant(outer):
            assert current_tenant() is outer
            with bind_tenant(inner):
                assert current_tenant() is inner
            assert current_tenant() is outer


class TestRequireTenant:
    def test_matching_tenant_returns_bound_context(self) -> None:
        ctx = _tenant_context("acme-corp")
        with bind_tenant(ctx):
            assert require_tenant("acme-corp") is ctx

    def test_mismatched_tenant_raises(self) -> None:
        with (
            bind_tenant(_tenant_context("acme-corp")),
            pytest.raises(TenantMismatchError) as exc_info,
        ):
            require_tenant("other-corp")
        assert exc_info.value.context["bound_tenant_id"] == "acme-corp"
        assert exc_info.value.context["expected_tenant_id"] == "other-corp"
        assert exc_info.value.error_code == "saena.identity.tenant_mismatch"

    def test_unbound_raises_unbound_error_not_mismatch(self) -> None:
        with pytest.raises(UnboundTenantContextError):
            require_tenant("acme-corp")


class TestAsyncioTaskIsolation:
    """Cross-tenant isolation guarantee: a tenant bound in one asyncio task
    must never leak into a sibling task started independently (only into
    tasks spawned *from within* the bound `with` block, per contextvars'
    copy-on-task-creation semantics)."""

    def test_sibling_tasks_do_not_see_each_others_binding(self) -> None:
        async def scenario() -> tuple[str, str]:
            async def bind_and_read(tenant_id: str, delay: float) -> str:
                with bind_tenant(_tenant_context(tenant_id)):
                    await asyncio.sleep(delay)
                    return current_tenant().tenant_id.value

            # Two independently-created tasks (not nested inside one
            # another's bind_tenant block) must each see only their own
            # binding, even when interleaved via sleep.
            task_a = asyncio.create_task(bind_and_read("acme-corp", 0.02))
            task_b = asyncio.create_task(bind_and_read("other-corp", 0.01))
            return await task_a, await task_b

        result_a, result_b = asyncio.run(scenario())
        assert result_a == "acme-corp"
        assert result_b == "other-corp"

    def test_task_spawned_inside_bind_block_inherits_binding(self) -> None:
        async def scenario() -> str:
            with bind_tenant(_tenant_context("acme-corp")):

                async def read_current() -> str:
                    return current_tenant().tenant_id.value

                # Spawned from inside the bind_tenant block -> inherits the
                # copied context, per contextvars semantics.
                return await asyncio.create_task(read_current())

        assert asyncio.run(scenario()) == "acme-corp"

    def test_unbound_sibling_task_still_raises(self) -> None:
        async def scenario() -> None:
            async def bound_task() -> None:
                with bind_tenant(_tenant_context("acme-corp")):
                    await asyncio.sleep(0.01)

            async def unbound_task() -> bool:
                await asyncio.sleep(0.0)
                try:
                    current_tenant()
                except UnboundTenantContextError:
                    return True
                return False

            _, unbound_result = await asyncio.gather(bound_task(), unbound_task())
            assert unbound_result is True

        asyncio.run(scenario())
