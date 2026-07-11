#!/bin/sh
# .claude/hooks/scripts/deny-deploy-push.sh
#
# PreToolUse hook for Bash. ADR-0019 hook #1.
#
# Verb-scoped subcommand allowlist for git, plus hard denies for
# deploy/push-adjacent tooling (kubectl/helm outside k3d dev context,
# terraform apply/destroy, gh pr merge, curl|sh / wget|sh remote installers).
#
# Contract: stdin = Claude Code PreToolUse JSON
#   {"tool_name":"Bash","tool_input":{"command":"..."}}
# Exit 0 = allow. Exit 2 = deny (stderr shown to model). Parse failure or any
# unrecognized-but-risky shape => exit 2, fail-closed (ADR-0019 engineering
# constraint: "deny hook은 fail-closed").
#
# HOOK_TEST_MOCK_CONTEXT: when set, overrides the live
# `kubectl config current-context` check (used by the test corpus runner to
# simulate k3d vs non-k3d contexts without a real cluster).

_hook_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_lib_dir="$_hook_dir/lib"

# --- DISABLED kill switch -----------------------------------------------
if [ -f "$_hook_dir/../DISABLED" ]; then
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    _audit_dir="$_hook_dir/../../../audit/agent-hooks"
    mkdir -p "$_audit_dir" 2>/dev/null
    printf '{"ts":"%s","tool_name":"Bash","hook":"deny-deploy-push","decision":"DISABLED-bypass"}\n' "$_ts" >>"$_audit_dir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null
    exit 0
fi

# shellcheck source=lib/json-field.sh
. "$_lib_dir/json-field.sh"
# shellcheck source=lib/normalize-command.sh
. "$_lib_dir/normalize-command.sh"

_stdin_json="$(cat)"

_tool_name="$(json_field "$_stdin_json" "tool_name")"
if [ -z "$_tool_name" ]; then
    _tool_name="Bash"
fi

_command="$(json_field "$_stdin_json" "tool_input.command")"
if [ $? -ne 0 ] || [ -z "$_command" ]; then
    echo "deny-deploy-push: could not parse tool_input.command from stdin JSON — fail-closed deny" >&2
    exit 2
fi

_kctx_check() {
    if [ -n "${HOOK_TEST_MOCK_CONTEXT+x}" ]; then
        printf '%s' "$HOOK_TEST_MOCK_CONTEXT"
        return 0
    fi
    if command -v kubectl >/dev/null 2>&1; then
        kubectl config current-context 2>/dev/null
        return 0
    fi
    printf ''
    return 1
}

_deny() {
    echo "deny-deploy-push: blocked — $1" >&2
    exit 2
}

# Raw-text check for `curl ... | ... sh` / `wget ... | ... bash` pipelines.
# Segment-level matching (below) splits on `|`, which destroys the adjacency
# between the fetch command and the interpreter it is piped into — so this
# specific pattern must be checked against the raw command text instead.
case "$_command" in
    *curl*"|"*sh|*curl*"|"*bash|*wget*"|"*sh|*wget*"|"*bash)
        _deny "curl/wget piped into a shell interpreter is forbidden"
        ;;
esac

_segments="$(normalize_command "$_command")"
if [ -z "$_segments" ]; then
    echo "deny-deploy-push: could not normalize command — fail-closed deny" >&2
    exit 2
fi

printf '%s\n' "$_segments" | while IFS= read -r _seg; do
    [ -z "$_seg" ] && continue

    _first="$(printf '%s' "$_seg" | awk '{print $1}')"

    case "$_first" in
        git)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                push)
                    _deny "git push is forbidden in dev-repo sessions (CLAUDE.md #10)"
                    ;;
                merge)
                    _deny "git merge is forbidden in dev-repo sessions"
                    ;;
                remote)
                    _sub2="$(printf '%s' "$_seg" | awk '{print $3}')"
                    if [ "$_sub2" = "set-url" ]; then
                        _deny "git remote set-url is forbidden (push-target rewrite)"
                    fi
                    ;;
                filter-repo)
                    _deny "git filter-repo is forbidden (history rewrite)"
                    ;;
                reset)
                    case "$_seg" in
                        *--hard*origin*)
                            _deny "git reset --hard origin* is forbidden"
                            ;;
                    esac
                    ;;
                status|log|diff|show|add|commit|branch|checkout|switch|restore|fetch|stash|worktree|rev-parse|merge-base|describe|tag|blame|grep|ls-files|check-ignore|config)
                    : # allowed subcommands (tag: read tag -l and tag creation both allowed per spec; config: read-only intent, not enforced further here)
                    ;;
                "")
                    : # bare `git` with no subcommand — not actionable, allow through
                    ;;
                *)
                    _deny "git subcommand '$_sub' is not in the dev-repo allowlist"
                    ;;
            esac
            ;;
        kubectl|helm)
            _kctx="$(_kctx_check)"
            case "$_kctx" in
                k3d-*)
                    : # allowed — local k3d dev cluster
                    ;;
                *)
                    _deny "$_first is only allowed against a k3d-* context (current: '${_kctx:-<none>}')"
                    ;;
            esac
            ;;
        k3d)
            : # k3d itself always allowed
            ;;
        terraform)
            case "$_seg" in
                *apply*|*destroy*)
                    _deny "terraform apply/destroy is forbidden in dev-repo sessions"
                    ;;
            esac
            ;;
        gh)
            case "$_seg" in
                gh\ pr\ merge*)
                    _deny "gh pr merge is forbidden in dev-repo sessions"
                    ;;
            esac
            ;;
        vercel)
            case "$_seg" in
                *deploy*)
                    _deny "vercel deploy is forbidden in dev-repo sessions"
                    ;;
            esac
            ;;
        flyctl)
            case "$_seg" in
                *deploy*)
                    _deny "flyctl deploy is forbidden in dev-repo sessions"
                    ;;
            esac
            ;;
    esac
done
_rc=$?
exit "$_rc"
