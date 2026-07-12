"""Tests for saena_observability.redaction — allowlist-first engine driven
by the W0 registry (ADR-0016)."""

from __future__ import annotations

import pytest
from saena_observability.redaction import (
    REDACTED_VALUE,
    RedactionAction,
    _matches_denylist_key,
    decide_redaction,
    redact_attributes,
)
from saena_observability.registry import load_redaction_rules


class TestAllowlistedAttributePassesThrough:
    def test_registered_attribute_with_clean_value_is_allowed(self) -> None:
        decision = decide_redaction("saena.contract_hash", "sha256:abcdef", context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_engine_id_is_allowed_in_all_contexts(self) -> None:
        for context in ("tenant", "system", "aggregate"):
            decision = decide_redaction("saena.engine_id", "chatgpt-search", context=context)
            assert decision.action is RedactionAction.ALLOW


class TestNonAllowlistedAttributeIsDropped:
    def test_unregistered_saena_attribute_is_dropped(self) -> None:
        decision = decide_redaction("saena.made_up_field", "value", context="tenant")
        assert decision.action is RedactionAction.DROP
        assert "not in attribute registry allowlist" in decision.reason

    def test_non_saena_namespace_attribute_is_dropped(self) -> None:
        decision = decide_redaction("http.method", "GET", context="tenant")
        assert decision.action is RedactionAction.DROP


class TestSecretPatternDenylist:
    def test_secret_looking_key_is_value_redacted(self) -> None:
        # saena.contract_hash is allowlisted; key itself doesn't match, but
        # a token-shaped value must still be caught by the value denylist.
        decision = decide_redaction(
            "saena.contract_hash", "bearer abc.def.token123", context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_password_value_is_redacted(self) -> None:
        decision = decide_redaction(
            "saena.contract_hash", "my-password-is-hunter2", context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_email_like_value_is_redacted(self) -> None:
        decision = decide_redaction(
            "saena.contract_hash", "contact me at a@example.com", context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_api_key_value_is_redacted(self) -> None:
        decision = decide_redaction("saena.contract_hash", "api_key=xyz123", context="tenant")
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_clean_value_is_not_redacted(self) -> None:
        decision = decide_redaction("saena.contract_hash", "sha256:deadbeef", context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_non_string_value_does_not_crash_value_matcher(self) -> None:
        decision = decide_redaction("saena.contract_hash", 12345, context="tenant")
        assert decision.action is RedactionAction.ALLOW


class TestDenylistKeyMatch:
    """No currently-registered saena.* attribute name matches a denylist
    key pattern by design (that would itself be a producer bug caught at
    registry-authoring time) — this test exercises the key-match branch
    directly against the loaded denylist patterns, using a hypothetical
    secret-shaped attribute name, to prove the branch is reachable and
    correct independent of the current registry contents."""

    def test_secret_shaped_key_matches_denylist(self) -> None:
        rules = load_redaction_rules()
        match = _matches_denylist_key("saena.api_token", rules.denylist_patterns)
        assert match is not None
        assert match.id == "R-SECRET-TOKEN"

    def test_clean_key_does_not_match_denylist(self) -> None:
        rules = load_redaction_rules()
        match = _matches_denylist_key("saena.tenant_id", rules.denylist_patterns)
        assert match is None

    def test_decide_redaction_redacts_value_on_key_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercises decide_redaction's key_match branch end-to-end: a
        # registered (allowlisted) but secret-shaped attribute key must be
        # REDACT_VALUE even with an innocuous value, because the *key*
        # itself matched a denylist pattern. No currently-registered
        # attribute name is secret-shaped by design, so a hypothetical
        # allowlist entry is patched in for this one test.
        import saena_observability.redaction as redaction_module
        from saena_observability.registry import AttributeEntry

        fake_registry = dict(redaction_module.load_attribute_registry())
        fake_registry["saena.api_token"] = AttributeEntry(
            name="saena.api_token",
            type="string",
            cardinality="high",
            pii=False,
            contexts={"tenant": "optional", "system": "optional", "aggregate": "optional"},
            description="test-only fixture attribute",
        )
        monkeypatch.setattr(redaction_module, "load_attribute_registry", lambda: fake_registry)

        decision = redaction_module.decide_redaction(
            "saena.api_token", "harmless-value", context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-SECRET-TOKEN" in decision.reason


class TestStructuralViolationRuleVAggTenant:
    def test_tenant_id_forbidden_in_aggregate_context(self) -> None:
        decision = decide_redaction("saena.tenant_id", "acme", context="aggregate")
        assert decision.action is RedactionAction.DROP
        assert "V-AGG-TENANT" in decision.reason

    def test_run_id_forbidden_in_aggregate_context(self) -> None:
        decision = decide_redaction("saena.run_id", "run-1", context="aggregate")
        assert decision.action is RedactionAction.DROP
        assert "V-AGG-TENANT" in decision.reason

    def test_tenant_id_allowed_in_tenant_context(self) -> None:
        decision = decide_redaction("saena.tenant_id", "acme", context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_violation_rule_skipped_when_context_unknown(self) -> None:
        # No structural rule can be evaluated without a context; the
        # attribute is still allowlisted so it passes through. Callers that
        # care about V-AGG-TENANT must always pass context explicitly.
        decision = decide_redaction("saena.tenant_id", "acme", context=None)
        assert decision.action is RedactionAction.ALLOW


class TestRedactAttributes:
    def test_mixed_batch_applies_all_three_outcomes(self) -> None:
        result = redact_attributes(
            {
                "saena.tenant_id": "acme",  # allow
                "saena.contract_hash": "token abc123",  # redact-value
                "saena.not_registered": "x",  # drop
            },
            context="tenant",
        )
        assert result == {
            "saena.tenant_id": "acme",
            "saena.contract_hash": REDACTED_VALUE,
        }
        assert "saena.not_registered" not in result

    def test_aggregate_batch_drops_tenant_and_run_id(self) -> None:
        result = redact_attributes(
            {
                "saena.tenant_id": "acme",
                "saena.run_id": "run-1",
                "saena.aggregate_scope_id": "scope-1",
            },
            context="aggregate",
        )
        assert result == {"saena.aggregate_scope_id": "scope-1"}

    def test_empty_input_returns_empty_output(self) -> None:
        assert redact_attributes({}, context="tenant") == {}
