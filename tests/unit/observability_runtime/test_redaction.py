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
    redact_text,
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

    def test_int_scalar_value_is_allowed(self) -> None:
        # int is a registry-contracted scalar type (attributes.schema.json
        # type enum: string|int|double|boolean) — passes through untouched
        # when it doesn't match any (string-only) denylist value pattern.
        decision = decide_redaction("saena.contract_hash", 12345, context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_float_scalar_value_is_allowed(self) -> None:
        decision = decide_redaction("saena.contract_hash", 3.14, context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_bool_scalar_value_is_allowed(self) -> None:
        decision = decide_redaction("saena.contract_hash", True, context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_none_value_is_allowed(self) -> None:
        decision = decide_redaction("saena.contract_hash", None, context="tenant")
        assert decision.action is RedactionAction.ALLOW


class TestFailClosedNonScalarValues:
    """MUST-FIX 2 (critic): a value that is not a registry-contracted
    scalar type (str/int/float/bool) or None must never be allowed through
    — dict/list/nested structures could carry a secret field the denylist
    regex (which only runs on `str`) never gets a chance to inspect."""

    def test_dict_value_is_redacted_not_allowed(self) -> None:
        decision = decide_redaction(
            "saena.contract_hash", {"nested": "secret-token-abc"}, context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-NON-SCALAR-VALUE" in decision.reason

    def test_list_value_is_redacted_not_allowed(self) -> None:
        decision = decide_redaction(
            "saena.contract_hash", ["item1", "secret-token"], context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-NON-SCALAR-VALUE" in decision.reason

    def test_bytes_value_is_redacted_not_allowed(self) -> None:
        decision = decide_redaction("saena.contract_hash", b"raw-bytes", context="tenant")
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-NON-SCALAR-VALUE" in decision.reason

    def test_custom_object_value_is_redacted_not_allowed(self) -> None:
        class _Custom:
            pass

        decision = decide_redaction("saena.contract_hash", _Custom(), context="tenant")
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-NON-SCALAR-VALUE" in decision.reason

    def test_dict_value_never_reaches_redact_attributes_output_raw(self) -> None:
        result = redact_attributes(
            {"saena.contract_hash": {"leak": "should-not-appear"}}, context="tenant"
        )
        assert result == {"saena.contract_hash": REDACTED_VALUE}
        assert "should-not-appear" not in str(result)

    def test_non_scalar_takes_priority_over_allow_but_not_over_drop(self) -> None:
        # A non-scalar value on a non-allowlisted attribute is still DROP
        # (the stronger outcome) — the fail-closed scalar check only
        # applies once the attribute has already passed the allowlist and
        # structural-violation gates.
        decision = decide_redaction("saena.not_registered_at_all", {"x": 1}, context="tenant")
        assert decision.action is RedactionAction.DROP


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
        from types import MappingProxyType

        import saena_observability.redaction as redaction_module
        from saena_observability.registry import AttributeEntry

        fake_registry = dict(redaction_module.load_attribute_registry())
        fake_registry["saena.api_token"] = AttributeEntry(
            name="saena.api_token",
            type="string",
            cardinality="high",
            pii=False,
            contexts=MappingProxyType(
                {"tenant": "optional", "system": "optional", "aggregate": "optional"}
            ),
            description="test-only fixture attribute",
        )
        monkeypatch.setattr(redaction_module, "load_attribute_registry", lambda: fake_registry)

        decision = redaction_module.decide_redaction(
            "saena.api_token", "harmless-value", context="tenant"
        )
        assert decision.action is RedactionAction.REDACT_VALUE
        assert "R-SECRET-TOKEN" in decision.reason


class TestRedactText:
    """MUST-FIX 1 (critic): free-text log bodies must be scrubbed against
    the VALUE-applicable denylist patterns. `key=value`/`key: value`
    assignment-shaped secrets (the common `"token=%s" % token` /
    f-string-interpolated-after-a-colon shape) are covered end to end
    (keyword + value both redacted); content-shaped patterns (email) match
    and redact their own span directly. See `redact_text`'s docstring for
    the documented out-of-scope case (filler-word phrases with no
    assignment operator, e.g. "token was X")."""

    def test_token_via_percent_interpolation_is_redacted(self) -> None:
        # Simulates stdlib logging's lazy %-style interpolation shape
        # (`logger.info("token=%s", secret)`), applied eagerly here since
        # redact_text operates on an already-formatted message string.
        body = "token=%s" % ("abc123secret",)  # noqa: UP031
        result = redact_text(body)
        assert "abc123secret" not in result
        assert REDACTED_VALUE in result

    def test_token_via_fstring_is_redacted(self) -> None:
        secret = "abc123secret"
        body = f"user auth token={secret}"
        result = redact_text(body)
        assert secret not in result
        assert REDACTED_VALUE in result

    def test_password_in_free_text_is_redacted(self) -> None:
        result = redact_text("login failed: password incorrect")
        assert REDACTED_VALUE in result

    def test_email_in_free_text_is_redacted(self) -> None:
        result = redact_text("contact a@example.com for help")
        assert "a@example.com" not in result
        assert REDACTED_VALUE in result

    def test_clean_message_is_untouched(self) -> None:
        body = "run completed successfully in 4.2s"
        assert redact_text(body) == body

    def test_only_matched_span_is_replaced_rest_preserved(self) -> None:
        result = redact_text("prefix-text token=abc123 suffix-text")
        assert result.startswith("prefix-text ")
        assert result.endswith(" suffix-text")
        assert "abc123" not in result

    def test_multiple_matches_are_all_redacted(self) -> None:
        result = redact_text("token=aaa and password=bbb both leaked")
        assert "aaa" not in result
        assert "bbb" not in result
        assert result.count(REDACTED_VALUE) >= 2

    def test_bare_keyword_with_no_assignment_operator_is_still_redacted_as_keyword(
        self,
    ) -> None:
        # No "=" / ":" present, so the assignment-value expansion cannot
        # apply — the bare keyword pattern still matches and redacts the
        # keyword itself (documented scope: the trailing filler-word value
        # in this shape is not covered, only the keyword is).
        result = redact_text("token was granted successfully")
        assert REDACTED_VALUE in result
        assert "token" not in result.lower()

    def test_redacts_across_embedded_newlines(self) -> None:
        # SHOULD-FIX (critic re-verify): redact_text must scan the whole
        # multi-line string (regexes here have no MULTILINE-sensitive
        # anchors, so this is mostly a non-regression guard), and a clean
        # line elsewhere in the same message must not be affected by a
        # secret on another line.
        body = "line one is clean\ntoken=abc123secret\nline three is clean too"
        result = redact_text(body)
        assert "abc123secret" not in result
        assert "line one is clean" in result
        assert "line three is clean too" in result
        assert result.count("\n") == 2


class TestRedactTextBearerWhitespaceForm:
    """Critic re-verify MUST-FIX: R-SECRET-BEARER's own canonical leak
    shape (redaction-rules.yaml:53-57, "Bearer <token> scheme strings") is
    whitespace-separated, not "="/":"-separated — the general
    assignment-only expansion missed it. `Bearer <token>` (RFC 6750) is
    covered end to end (keyword + token both redacted) while ordinary
    prose use of the word "bearer" is not over-redacted."""

    def test_bearer_space_form_is_fully_redacted(self) -> None:
        result = redact_text("Bearer abc123token")
        assert "abc123token" not in result
        assert result == REDACTED_VALUE

    def test_authorization_header_dump_with_bearer_is_fully_redacted(self) -> None:
        result = redact_text("Authorization: Bearer abc123token")
        assert "abc123token" not in result
        assert "Bearer" not in result

    def test_authorization_assignment_with_bearer_is_fully_redacted(self) -> None:
        result = redact_text("authorization=Bearer xyz")
        assert "xyz" not in result
        assert "Bearer" not in result

    def test_plain_prose_bearer_without_following_token_is_not_over_redacted(
        self,
    ) -> None:
        # "bearer" used as an ordinary English noun, followed only by
        # common filler words ("of", "good", "news") — must not be
        # mistaken for a credential; only the keyword itself is redacted,
        # the surrounding sentence is preserved.
        result = redact_text("the bearer of good news arrived")
        assert result == f"the {REDACTED_VALUE} of good news arrived"

    def test_bare_bearer_word_alone_redacts_only_keyword(self) -> None:
        assert redact_text("bearer") == REDACTED_VALUE

    def test_bearer_at_end_of_sentence_with_punctuation_redacts_only_keyword(
        self,
    ) -> None:
        assert redact_text("bearer.") == f"{REDACTED_VALUE}."

    def test_lowercase_bearer_scheme_is_case_insensitive(self) -> None:
        result = redact_text("bearer abc123token")
        assert "abc123token" not in result

    def test_key_only_pattern_is_skipped_for_text_scrubbing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A denylist pattern whose applies_to is key-only (no "value") must
        # be skipped entirely by redact_text — every currently-registered
        # pattern applies to value too, so this exercises that skip branch
        # directly against a patched rule set.
        import re

        import saena_observability.redaction as redaction_module
        from saena_observability.registry import DenylistPattern, RedactionRules

        key_only_rules = RedactionRules(
            export_policy="allowlist",
            denylist_patterns=(
                DenylistPattern(
                    id="R-KEY-ONLY-TEST",
                    pattern=re.compile(r"(?i)keyonlysecret"),
                    applies_to=("key",),
                    description="test-only key-only fixture pattern",
                ),
            ),
            violation_rules=(),
        )
        monkeypatch.setattr(redaction_module, "load_redaction_rules", lambda: key_only_rules)

        text = "message mentioning keyonlysecret in free text"
        assert redaction_module.redact_text(text) == text


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
