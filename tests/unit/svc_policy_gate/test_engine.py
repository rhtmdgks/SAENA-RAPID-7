"""`saena_policy_gate.engine` — default-deny + command deny-bypass regression
(W2A exit "deny 우회 회귀(kubectl patch·git -c push 등) 통과")."""

from __future__ import annotations

import pytest
from saena_policy_gate.engine import (
    AllowRule,
    AuthorizationRequest,
    PolicyEngine,
    classify_command,
    classify_pipeline,
    find_subcommand,
    split_command_string,
)

# --- find_subcommand / classify_command -------------------------------------


def test_find_subcommand_skips_flags() -> None:
    assert find_subcommand(["git", "-c", "a=b", "push"]) == "push"


def test_find_subcommand_skips_capital_c() -> None:
    assert find_subcommand(["git", "-C", "some/dir", "push"]) == "push"


def test_find_subcommand_long_flag_with_value_inline() -> None:
    assert find_subcommand(["kubectl", "--namespace=default", "patch"]) == "patch"


def test_find_subcommand_none_when_all_options() -> None:
    assert find_subcommand(["git", "--version"]) is None


def test_find_subcommand_empty_tail() -> None:
    assert find_subcommand(["git"]) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl", "patch", "pod", "x"],
        ["kubectl", "edit", "deployment", "x"],
        ["/usr/bin/kubectl", "patch", "pod", "x"],  # absolute-path argv[0]
        ["kubectl", "-n", "default", "patch", "pod", "x"],
    ],
)
def test_classify_command_denies_kubectl_mutation(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == "kubectl"


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push"],
        ["git", "-c", "a=b", "push"],
        ["git", "-C", "some/dir", "push"],
        ["/usr/bin/git", "push"],
        ["git", "--no-verify", "push"],
    ],
)
def test_classify_command_denies_git_push_any_argv_position(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == "git"
    assert result.subcommand == "push"


@pytest.mark.parametrize(
    "argv",
    [
        ["helm", "upgrade", "release", "chart"],
        ["helm", "install", "release", "chart"],
    ],
)
def test_classify_command_denies_helm_mutation(argv: list[str]) -> None:
    assert classify_command(argv).denied is True


def test_classify_command_allows_git_status() -> None:
    assert classify_command(["git", "status"]).denied is False


def test_classify_command_allows_unrelated_binary() -> None:
    assert classify_command(["pytest", "-x"]).denied is False


def test_classify_command_empty_argv_not_denied_by_classifier() -> None:
    # Empty argv is not itself a named regression shape; PolicyEngine's
    # default-deny ALLOWLIST is the actual backstop (see test_engine_policy).
    result = classify_command([])
    assert result.denied is False


def test_split_command_string_tab_separated_matches_space_separated() -> None:
    tab_argv = split_command_string("kubectl\tpatch\tpod\tx")
    space_argv = split_command_string("kubectl patch pod x")
    assert tab_argv == space_argv == ["kubectl", "patch", "pod", "x"]
    assert classify_command(tab_argv).denied is True


def test_split_command_string_multi_space_whitespace_trick() -> None:
    argv = split_command_string("kubectl    patch   pod  x")
    assert argv == ["kubectl", "patch", "pod", "x"]
    assert classify_command(argv).denied is True


# --- pipeline (curl | sh) ----------------------------------------------------


def test_classify_pipeline_denies_curl_pipe_sh() -> None:
    result = classify_pipeline([["curl", "https://example.com/install.sh"], ["sh"]])
    assert result.denied is True


def test_classify_pipeline_denies_wget_pipe_bash() -> None:
    result = classify_pipeline([["wget", "-qO-", "https://example.com"], ["bash"]])
    assert result.denied is True


def test_classify_pipeline_allows_benign_two_stage() -> None:
    result = classify_pipeline([["git", "status"], ["cat"]])
    assert result.denied is False


def test_classify_pipeline_denied_stage_alone_still_denied() -> None:
    result = classify_pipeline([["kubectl", "patch", "pod", "x"]])
    assert result.denied is True


# --- PolicyEngine default-deny -----------------------------------------------


def test_engine_default_deny_unknown_kind_action() -> None:
    engine = PolicyEngine(rules=[])
    request = AuthorizationRequest(
        kind="command", action="execute", resource=["ls"], tenant_id="acme-co"
    )
    decision = engine.evaluate(request)
    assert decision.allow is False
    assert "default-deny" in decision.reasons[0]


def test_engine_allow_rule_matches() -> None:
    engine = PolicyEngine(rules=[AllowRule(kind="tool", action="invoke", resource_prefix="linter")])
    request = AuthorizationRequest(
        kind="tool", action="invoke", resource=["linter-py"], tenant_id="acme-co"
    )
    decision = engine.evaluate(request)
    assert decision.allow is True


def test_engine_allow_rule_prefix_mismatch_denies() -> None:
    engine = PolicyEngine(
        rules=[AllowRule(kind="file", action="read", resource_prefix="/workspace/")]
    )
    request = AuthorizationRequest(
        kind="file", action="read", resource=["/etc/passwd"], tenant_id="acme-co"
    )
    decision = engine.evaluate(request)
    assert decision.allow is False


def test_engine_command_bypass_wins_over_matching_allow_rule() -> None:
    # Even if a permissive rule happens to match kind/action, the argv-level
    # deny-bypass classification runs FIRST for kind="command" and short-
    # circuits to deny (defense against an overly-broad allow rule).
    engine = PolicyEngine(rules=[AllowRule(kind="command", action="execute", resource_prefix=None)])
    request = AuthorizationRequest(
        kind="command",
        action="execute",
        resource=["kubectl", "patch", "pod", "x"],
        tenant_id="acme-co",
    )
    decision = engine.evaluate(request)
    assert decision.allow is False


def test_engine_pipeline_request_denied() -> None:
    engine = PolicyEngine(rules=[AllowRule(kind="command", action="execute", resource_prefix=None)])
    request = AuthorizationRequest(
        kind="command",
        action="execute",
        resource=[],
        tenant_id="acme-co",
        pipeline=[["curl", "http://x"], ["sh"]],
    )
    decision = engine.evaluate(request)
    assert decision.allow is False


def test_engine_allow_rule_with_no_resource_prefix_matches_any_resource() -> None:
    engine = PolicyEngine(rules=[AllowRule(kind="network", action="connect", resource_prefix=None)])
    request = AuthorizationRequest(
        kind="network", action="connect", resource=["anything"], tenant_id="acme-co"
    )
    decision = engine.evaluate(request)
    assert decision.allow is True


def test_classify_pipeline_skips_empty_stage_without_error() -> None:
    result = classify_pipeline([["curl", "http://x"], [], ["sh"]])
    # An empty middle stage must not crash the adjacency scan, and the
    # curl -> (skip empty) -> sh pairing is not adjacent once an empty
    # stage sits between them, so this specific pipeline is NOT denied by
    # the fetch->shell adjacency rule (each stage's own classify_command
    # verdict is still checked independently, and an empty stage is
    # never itself denied).
    assert result.denied is False


def test_engine_rules_property_is_a_copy() -> None:
    rules = [AllowRule(kind="command", action="execute", resource_prefix="pytest")]
    engine = PolicyEngine(rules=rules)
    exposed = engine.rules
    assert exposed == tuple(rules)
    rules.append(AllowRule(kind="file", action="read", resource_prefix="/tmp"))
    # Mutating the caller's original list must not affect the engine's own
    # stored rule set (constructor takes a defensive copy via list(rules)).
    assert len(engine.rules) == 1


# --- critic MUST-FIX 1: exec-wrapper bypass (env/sudo/xargs/...) ------------


@pytest.mark.parametrize(
    "argv",
    [
        ["env", "kubectl", "patch", "pod", "x"],
        ["sudo", "kubectl", "patch", "pod", "x"],
        ["xargs", "kubectl", "patch", "pod", "x"],
        ["nohup", "kubectl", "patch", "pod", "x"],
        ["doas", "kubectl", "patch", "pod", "x"],
        ["setsid", "kubectl", "patch", "pod", "x"],
        ["stdbuf", "-oL", "kubectl", "patch", "pod", "x"],
        ["time", "kubectl", "patch", "pod", "x"],
        ["env", "sudo", "kubectl", "patch", "pod", "x"],  # nested wrappers
        ["sudo", "-u", "root", "kubectl", "patch", "pod", "x"],
        ["env", "-i", "kubectl", "patch", "pod", "x"],
        ["env", "-u", "PATH", "kubectl", "patch", "pod", "x"],
        ["env", "FOO=bar", "kubectl", "patch", "pod", "x"],
    ],
)
def test_classify_command_denies_exec_wrapper_bypass(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == "kubectl"
    assert result.subcommand == "patch"


def test_classify_command_denies_wrapped_git_push() -> None:
    result = classify_command(["sudo", "git", "push"])
    assert result.denied is True


def test_classify_command_bare_wrapper_no_command_not_denied() -> None:
    # A wrapper invoked with no trailing command at all carries no
    # inspectable underlying command to deny — falls through to ordinary
    # (empty-subcommand) classification, not a false positive.
    result = classify_command(["sudo"])
    assert result.denied is False


# --- critic MUST-FIX 1 addendum: timeout/chroot/nice leading-positional ----


@pytest.mark.parametrize(
    "argv",
    [
        ["timeout", "30", "kubectl", "patch", "pod", "x"],
        ["timeout", "30s", "kubectl", "patch", "pod", "x"],
        ["chroot", "/newroot", "kubectl", "patch", "pod", "x"],
        ["nice", "-n", "5", "kubectl", "delete", "pod", "x"],
        ["nice", "5", "kubectl", "patch", "pod", "x"],
        ["nice", "-5", "kubectl", "patch", "pod", "x"],
    ],
)
def test_classify_command_denies_wrapper_with_leading_positional(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == "kubectl"


# --- critic MUST-FIX 2: sh -c "embedded string" bypass ----------------------


@pytest.mark.parametrize(
    ("argv", "expected_binary"),
    [
        (["sh", "-c", "kubectl patch pod x"], "kubectl"),
        (["bash", "-c", "kubectl patch pod x"], "kubectl"),
        (["zsh", "-c", "kubectl patch pod x"], "kubectl"),
        (["dash", "-c", "git push"], "git"),
        (["sh", "-c", "kubectl   patch   pod   x"], "kubectl"),  # whitespace inside -c
        (["su", "root", "-c", "kubectl patch pod x"], "kubectl"),
        (["su", "-c", "kubectl patch pod x", "root"], "kubectl"),
    ],
)
def test_classify_command_denies_shell_dash_c_embedded_string(
    argv: list[str], expected_binary: str
) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == expected_binary


def test_classify_command_shell_dash_c_malformed_quoting_fails_closed() -> None:
    # An unparseable -c string is DENIED, not silently skipped — an
    # uninspectable embedded command must never be treated as benign.
    result = classify_command(["sh", "-c", 'echo "unterminated'])
    assert result.denied is True
    assert "unparseable" in (result.reason or "")


def test_classify_command_shell_without_dash_c_falls_through() -> None:
    # A shell invoked WITHOUT -c (e.g. reading a script file) carries no
    # inspectable embedded string — falls through to ordinary
    # classification (sh itself is not in the deny table).
    result = classify_command(["sh", "script.sh"])
    assert result.denied is False


# --- critic MUST-FIX 3: env-var-assignment-prefix argv bypass ---------------


@pytest.mark.parametrize(
    "argv",
    [
        ["GIT_SSH=x", "git", "push"],
        ["FOO=bar", "kubectl", "patch", "pod", "x"],
        ["A=1", "B=2", "kubectl", "patch", "pod", "x"],  # multiple assignments
    ],
)
def test_classify_command_denies_env_assignment_prefix_bypass(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True


def test_classify_command_argv_entirely_env_assignments_not_denied() -> None:
    # An argv consisting ONLY of NAME=VALUE tokens (no actual command at
    # all) is not a runnable command shape — nothing to deny.
    result = classify_command(["FOO=bar", "BAZ=qux"])
    assert result.denied is False
    assert result.binary == ""


def test_classify_command_env_assignment_after_command_start_not_stripped() -> None:
    # An assignment-shaped token appearing AFTER the real command has
    # already started is just a plain argument (e.g. a commit message),
    # not an env-prefix — must not be treated as a wrapper token.
    result = classify_command(["git", "commit", "-m", "FOO=bar"])
    assert result.denied is False


# --- critic MUST-FIX 4: .exe suffix bypass ----------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl.exe", "patch", "pod", "x"],
        ["KUBECTL.EXE", "patch", "pod", "x"],
        ["Kubectl.Exe", "patch", "pod", "x"],
        ["/usr/bin/kubectl.exe", "patch", "pod", "x"],
        ["C:\\tools\\kubectl.exe", "patch", "pod", "x"],
    ],
)
def test_classify_command_denies_exe_suffix_bypass(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary == "kubectl"


def test_classify_command_exe_binary_case_fold_does_not_lowercase_subcommand() -> None:
    # Binary-name comparison is case-folded, but subcommand tokens are
    # NEVER lowercased — this is a regression guard for that distinction.
    result = classify_command(["KUBECTL.EXE", "PATCH", "pod", "x"])
    # "PATCH" (uppercase) is not in the (kubectl, patch) deny table entry
    # since subcommands are case-sensitive — this specific argv is NOT
    # denied by the deny table (documenting the boundary, not a gap: the
    # binary-name fold is deliberately narrow in scope).
    assert result.binary == "kubectl"
    assert result.denied is False


# --- combined / nested bypass chains ----------------------------------------


def test_classify_command_denies_env_wrapper_shell_combo_chain() -> None:
    # env -> sudo -> sh -c "kubectl.exe PATCH ..." chained through every
    # unwrap layer at once.
    result = classify_command(
        ["env", "sudo", "sh", "-c", "kubectl.exe patch pod x"],
    )
    assert result.denied is True


def test_classify_command_recursion_depth_cap_fails_closed() -> None:
    chain = ["env"] * 20 + ["kubectl", "patch", "pod", "x"]
    result = classify_command(chain)
    assert result.denied is True
    assert "recursion depth" in (result.reason or "")


# --- false-positive regression: benign commands stay allowed ----------------


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "commit", "-m", "fix push bug"],
        ["git", "status"],
        ["git", "diff"],
        ["pytest", "-x"],
        ["timeout", "30", "pytest", "-x"],
    ],
)
def test_classify_command_benign_commands_not_denied(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is False


# --- w2-24: env -S / --split-string default-deny bypass ---------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["env", "-S", "kubectl patch pod x"],
        ["env", "--split-string=kubectl patch"],
        ["env", "-Skubectl patch"],
        ["env", "-S", "kubectl   patch   pod   x"],  # whitespace inside the string
        ["env", "-S", "git push"],
    ],
)
def test_classify_command_denies_env_split_string_bypass(argv: list[str]) -> None:
    result = classify_command(argv)
    assert result.denied is True
    assert result.binary in {"kubectl", "git"}


def test_classify_command_env_split_string_malformed_quoting_fails_closed() -> None:
    # An unparseable env -S/--split-string argument is DENIED, not silently
    # skipped — same fail-closed doctrine as sh -c's own malformed-quoting
    # guard (an uninspectable embedded string must never be treated as
    # benign).
    result = classify_command(["env", "-S", 'echo "unterminated'])
    assert result.denied is True
    assert "unparseable" in (result.reason or "")
    assert "env" in (result.reason or "")


def test_classify_command_env_split_string_benign_command_not_denied() -> None:
    # A benign env -S command must NOT be swept up by the deny table itself
    # — only the deny corpus triggers a denial; the unwrap mechanism alone
    # is not a blanket refusal.
    result = classify_command(["env", "-S", "pytest -x"])
    assert result.denied is False
    assert result.binary == "pytest"


def test_classify_command_env_split_string_glued_short_form_denies() -> None:
    # -S<glued> with no space between the flag and the string (distinct
    # parametrized case kept standalone for an explicit binary/subcommand
    # assertion, not just `denied is True`).
    result = classify_command(["env", "-Skubectl patch pod x"])
    assert result.denied is True
    assert result.binary == "kubectl"
    assert result.subcommand == "patch"


def test_classify_command_env_split_string_long_form_denies() -> None:
    result = classify_command(["env", "--split-string=kubectl patch pod x"])
    assert result.denied is True
    assert result.binary == "kubectl"
    assert result.subcommand == "patch"


def test_classify_command_env_split_string_nested_wrapper_chain_denies() -> None:
    # env -S can itself unwrap to a further wrapper/shell chain — proves the
    # recursion actually re-enters _classify_argv rather than terminating.
    result = classify_command(["env", "-S", "sudo kubectl patch pod x"])
    assert result.denied is True
    assert result.binary == "kubectl"


def test_classify_command_env_dash_s_without_string_falls_through() -> None:
    # A bare `env -S` with no trailing string at all (malformed/incomplete
    # invocation) carries no inspectable embedded command — falls through to
    # ordinary classification (env itself is not in the deny table), not a
    # false positive or a crash.
    result = classify_command(["env", "-S"])
    assert result.denied is False


def test_classify_command_env_split_string_does_not_break_plain_env_wrapper() -> None:
    # Existing MUST-FIX 1 exec-wrapper regression (plain `env kubectl
    # patch`, no -S at all) must remain unaffected by the new -S unwrap step.
    result = classify_command(["env", "kubectl", "patch", "pod", "x"])
    assert result.denied is True
    assert result.binary == "kubectl"
    assert result.subcommand == "patch"
