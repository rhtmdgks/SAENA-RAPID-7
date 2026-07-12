"""`saena_policy_gate.rules` — reference allowlist shape (coordinator
SHOULD-FIX, post-implementation review: prior `git status`/`git diff`
entries were dead code — `resource_prefix` matches `resource[0]` only, so
`"git".startswith("git status")` was always `False`)."""

from __future__ import annotations

from saena_policy_gate.engine import AuthorizationRequest, PolicyEngine
from saena_policy_gate.rules import DEFAULT_RULES, default_engine_rules


def test_default_engine_rules_returns_fresh_mutable_copy() -> None:
    rules_a = default_engine_rules()
    rules_b = default_engine_rules()
    assert rules_a == list(DEFAULT_RULES)
    assert rules_a is not rules_b
    rules_a.append(DEFAULT_RULES[0])
    assert len(default_engine_rules()) == len(DEFAULT_RULES)


def test_git_command_allow_rule_is_not_dead_code() -> None:
    """`git` allow rule matches `resource[0]` (the binary name) — this is
    the fix: the rule is reachable at all, unlike the prior
    `"git status"`/`"git diff"` prefix entries which could never match."""
    engine = PolicyEngine(rules=default_engine_rules())
    for resource in (["git", "status"], ["git", "diff"]):
        request = AuthorizationRequest(
            kind="command", action="execute", resource=resource, tenant_id="acme-co"
        )
        decision = engine.evaluate(request)
        assert decision.allow is True, resource


def test_git_push_still_denied_despite_blanket_git_allow_rule() -> None:
    """The deny-bypass classification runs BEFORE allowlist matching
    (engine.py's own evaluate() ordering) — a blanket `git` allow rule must
    never let `git push` (or any other denied subcommand) through."""
    engine = PolicyEngine(rules=default_engine_rules())
    request = AuthorizationRequest(
        kind="command", action="execute", resource=["git", "push"], tenant_id="acme-co"
    )
    decision = engine.evaluate(request)
    assert decision.allow is False


def test_git_commit_allowed_by_blanket_git_rule() -> None:
    engine = PolicyEngine(rules=default_engine_rules())
    request = AuthorizationRequest(
        kind="command",
        action="execute",
        resource=["git", "commit", "-m", "fix push bug"],
        tenant_id="acme-co",
    )
    decision = engine.evaluate(request)
    assert decision.allow is True
