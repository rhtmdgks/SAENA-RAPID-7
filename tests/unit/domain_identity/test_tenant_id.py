"""`TenantId` value object — ADR-0014 slug pattern edges + immutability.

Pattern under test (ADR-0014, verbatim in
packages/contracts/json-schema/common/identifiers/v1/identifiers.schema.json
$defs.tenant_id and the generated TenantId RootModel):
`^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$`

Encoded truth (verified against the compiled pattern directly, not assumed):
minimum valid length is 3 chars (1 start + >=1 middle + 1 end), maximum
valid length is 32 chars (1 + 30 + 1).
"""

from __future__ import annotations

import dataclasses

import pytest
from saena_domain.identity.errors import InvalidTenantIdError
from saena_domain.identity.tenant import TenantId


class TestValidTenantId:
    @pytest.mark.parametrize(
        "value",
        [
            "a-1",  # minimum valid length (3 chars)
            "a" * 32,  # maximum valid length (32 chars)
            "acme-corp",
            "example-tenant",
        ],
    )
    def test_accepts_pattern_conformant_slugs(self, value: str) -> None:
        tenant_id = TenantId(value)
        assert tenant_id.value == value
        assert str(tenant_id) == value

    def test_min_length_three_chars_is_valid(self) -> None:
        TenantId("a-1")

    def test_max_length_32_chars_is_valid(self) -> None:
        TenantId("a" * 32)

    def test_digits_allowed_at_boundaries(self) -> None:
        TenantId("0-9")

    def test_internal_hyphens_allowed(self) -> None:
        TenantId("a-b-c-d")


class TestInvalidTenantId:
    def test_rejects_length_two(self) -> None:
        # 2-char strings can never satisfy start(1) + middle(>=1) + end(1).
        with pytest.raises(InvalidTenantIdError):
            TenantId("a1")

    def test_rejects_length_one(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("a")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("")

    def test_rejects_length_33_chars(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("a" * 33)

    def test_rejects_leading_hyphen(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("-abc")

    def test_rejects_trailing_hyphen(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("abc-")

    def test_rejects_uppercase(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("Abc-de")

    def test_rejects_underscore(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("abc_de")

    def test_rejects_whitespace(self) -> None:
        with pytest.raises(InvalidTenantIdError):
            TenantId("abc de")

    def test_error_context_carries_offending_value(self) -> None:
        with pytest.raises(InvalidTenantIdError) as exc_info:
            TenantId("BAD")
        assert exc_info.value.context["tenant_id"] == "BAD"
        assert exc_info.value.error_code == "saena.identity.invalid_tenant_id"

    def test_pathologically_long_value_is_truncated_in_context_and_message(self) -> None:
        # SHOULD-FIX 1 (critic, w2-01 review): the raw rejected value must
        # never be echoed back unbounded -- a caller can pass an arbitrarily
        # long (attacker-controlled or accidental) string, and interpolating
        # it verbatim into an error/log/audit sink is its own hazard.
        pathological = "A" * 10_000
        with pytest.raises(InvalidTenantIdError) as exc_info:
            TenantId(pathological)
        echoed = exc_info.value.context["tenant_id"]
        assert len(echoed) < len(pathological)
        assert echoed.startswith("A" * 64)
        assert "10000 chars total" in echoed
        # The formatted exception message must not carry the full 10k chars
        # either -- only the truncated form.
        assert pathological not in str(exc_info.value)

    def test_short_invalid_value_is_echoed_verbatim_not_truncated(self) -> None:
        # Truncation must only kick in above the cap -- short invalid values
        # (the overwhelmingly common case) keep full diagnostic fidelity.
        with pytest.raises(InvalidTenantIdError) as exc_info:
            TenantId("BAD-Value-123")
        assert exc_info.value.context["tenant_id"] == "BAD-Value-123"

    def test_value_exactly_at_truncation_boundary_is_not_marked_truncated(self) -> None:
        # 64 chars is the cap itself -- values at or below it pass through
        # unmodified (only values STRICTLY longer than the cap are marked).
        boundary_value = "A" * 64
        with pytest.raises(InvalidTenantIdError) as exc_info:
            TenantId(boundary_value)
        assert exc_info.value.context["tenant_id"] == boundary_value
        assert "truncated" not in exc_info.value.context["tenant_id"]


class TestTenantIdImmutability:
    def test_is_frozen_dataclass(self) -> None:
        tenant_id = TenantId("acme-corp")
        with pytest.raises(dataclasses.FrozenInstanceError):
            tenant_id.value = "other-corp"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert TenantId("acme-corp") == TenantId("acme-corp")
        assert TenantId("acme-corp") != TenantId("other-corp")

    def test_hashable(self) -> None:
        assert hash(TenantId("acme-corp")) == hash(TenantId("acme-corp"))
        assert len({TenantId("acme-corp"), TenantId("acme-corp")}) == 1
