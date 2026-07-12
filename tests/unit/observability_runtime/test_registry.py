"""Tests for saena_observability.registry — read-only loader for the W0
attribute registry and redaction rules (ADR-0016)."""

from __future__ import annotations

from saena_observability.registry import (
    AttributeEntry,
    is_allowlisted,
    load_attribute_registry,
    load_redaction_rules,
)


class TestLoadAttributeRegistry:
    def test_returns_name_keyed_mapping(self) -> None:
        registry = load_attribute_registry()
        assert isinstance(registry, dict)
        assert "saena.tenant_id" in registry
        assert isinstance(registry["saena.tenant_id"], AttributeEntry)

    def test_known_entries_present(self) -> None:
        registry = load_attribute_registry()
        for name in (
            "saena.tenant_id",
            "saena.run_id",
            "saena.engine_id",
            "saena.context",
        ):
            assert name in registry

    def test_tenant_id_context_rules_match_adr(self) -> None:
        entry = load_attribute_registry()["saena.tenant_id"]
        assert entry.contexts == {
            "tenant": "required",
            "system": "forbidden",
            "aggregate": "forbidden",
        }

    def test_is_cached_returns_same_object(self) -> None:
        # lru_cache identity check — confirms registry is not re-parsed
        # per call (read-only W0 input, safe to cache).
        assert load_attribute_registry() is load_attribute_registry()


class TestLoadRedactionRules:
    def test_export_policy_is_allowlist(self) -> None:
        rules = load_redaction_rules()
        assert rules.export_policy == "allowlist"

    def test_denylist_patterns_loaded(self) -> None:
        rules = load_redaction_rules()
        ids = {p.id for p in rules.denylist_patterns}
        assert "R-SECRET-TOKEN" in ids
        assert "R-PII-EMAIL" in ids

    def test_violation_rules_include_v_agg_tenant(self) -> None:
        rules = load_redaction_rules()
        v_agg = next(r for r in rules.violation_rules if r.id == "V-AGG-TENANT")
        assert v_agg.context == "aggregate"
        assert "saena.tenant_id" in v_agg.forbidden_attributes
        assert "saena.run_id" in v_agg.forbidden_attributes


class TestIsAllowlisted:
    def test_registered_attribute_is_allowlisted(self) -> None:
        assert is_allowlisted("saena.tenant_id") is True

    def test_unregistered_attribute_is_not_allowlisted(self) -> None:
        assert is_allowlisted("saena.totally_made_up_attribute") is False

    def test_non_saena_key_is_not_allowlisted(self) -> None:
        assert is_allowlisted("http.method") is False
