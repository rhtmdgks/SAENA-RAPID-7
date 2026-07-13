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
    # Audit the denial (ADR-0019: block AND log). Best-effort — audit failure
    # must never turn a deny into an allow.
    _adir="$_hook_dir/../../../audit/agent-hooks"
    mkdir -p "$_adir" 2>/dev/null
    _dts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)"
    _reason_esc="$(printf '%s' "$1" | tr '"' "'" | cut -c1-160)"
    printf '{"ts":"%s","tool_name":"Bash","hook":"deny-deploy-push","decision":"deny","reason":"%s"}\n' \
        "$_dts" "$_reason_esc" >>"$_adir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null || true
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
                    # Precision rule (user-approved 2026-07-13, Wave 3 entry
                    # gate): the ONLY permitted push is a checkpoint push of a
                    # wave integration branch to origin — exactly
                    # `git push [-u|--set-upstream] origin wave<N>-<name>`.
                    # Any other flag (--force/-f/--force-with-lease/--delete/
                    # --tags/--all/--mirror/...), any refspec containing `:`,
                    # any non-origin remote, any non-wave branch (main/master/
                    # HEAD/tags/unit/*) stays denied. main lands via human PR
                    # only (CLAUDE.md #10).
                    _push_ok=1
                    _push_remote=""
                    _push_branch=""
                    _push_rest="$(printf '%s' "$_seg" | awk '{$1=""; $2=""; print}')"
                    for _push_tok in $_push_rest; do
                        case "$_push_tok" in
                            *\>*|\<*)
                                : # shell redirection (2>&1, >file, <in) — no push semantics
                                ;;
                            -u|--set-upstream)
                                : # upstream tracking on first checkpoint push — harmless
                                ;;
                            -*)
                                _push_ok=0 # every other flag: force/delete/tags/all/mirror/... fail-closed
                                ;;
                            *:*)
                                _push_ok=0 # refspec rewrite (e.g. wave3-x:main)
                                ;;
                            *)
                                if [ -z "$_push_remote" ]; then
                                    _push_remote="$_push_tok"
                                elif [ -z "$_push_branch" ]; then
                                    _push_branch="$_push_tok"
                                else
                                    _push_ok=0 # extra positional args
                                fi
                                ;;
                        esac
                    done
                    [ "$_push_remote" = "origin" ] || _push_ok=0
                    case "$_push_branch" in
                        wave[0-9]*-*)
                            : # wave integration branch — permitted target
                            ;;
                        *)
                            _push_ok=0
                            ;;
                    esac
                    if [ "$_push_ok" -ne 1 ]; then
                        _deny "git push is allowed ONLY as 'git push [-u] origin wave<N>-<branch>' (checkpoint push, user-approved 2026-07-13); everything else forbidden (CLAUDE.md #10)"
                    fi
                    ;;
                merge)
                    # Precision rule (W1, user-approved 2026-07-12): the ONLY
                    # permitted merge is Integrator wave-branch integration —
                    # current branch matches ^wave[0-9]+- AND the merge source
                    # is a unit/* branch AND no main/master/origin token
                    # appears. Everything else stays denied (main protection
                    # continues at hook level after the deny-rule removal).
                    _cur_branch="${HOOK_TEST_MOCK_BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null)}"
                    case "$_cur_branch" in
                        wave[0-9]*-*)
                            case "$_seg" in
                                *\ main|*\ main\ *|*origin/*|*\ master|*\ master\ *)
                                    _deny "git merge of main/master/origin is forbidden even on wave branches (human PR only)"
                                    ;;
                                *unit/w[0-9]*)
                                    : # allowed — integration merge of a patch-unit branch
                                    ;;
                                *)
                                    _deny "git merge on wave branches is allowed only from unit/* branches"
                                    ;;
                            esac
                            ;;
                        *)
                            _deny "git merge is forbidden outside wave integration branches (current: '${_cur_branch:-<none>}')"
                            ;;
                    esac
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
                status|log|diff|show|add|commit|branch|checkout|switch|restore|fetch|stash|worktree|rev-parse|merge-base|describe|tag|blame|grep|ls-files|check-ignore|config|cat-file|ls-tree|rev-list|show-ref)
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
                    # Precision rule (user-approved 2026-07-13, nonstop
                    # directive): merging a PR is allowed ONLY when the PR's
                    # live-resolved head branch is a wave integration branch
                    # (wave<N>-*) and its base is main — the designed landing
                    # path. No --admin (branch-protection bypass). Anything
                    # unresolvable fails closed.
                    case "$_seg" in
                        *--admin*)
                            _deny "gh pr merge --admin is forbidden (branch-protection bypass)"
                            ;;
                    esac
                    _pr_num=""
                    for _pr_tok in $(printf '%s' "$_seg" | awk '{$1=""; $2=""; $3=""; print}'); do
                        case "$_pr_tok" in
                            [0-9]*) _pr_num="$_pr_tok"; break ;;
                        esac
                    done
                    if [ -z "$_pr_num" ]; then
                        _deny "gh pr merge without an explicit PR number is forbidden (fail-closed)"
                    fi
                    if [ -n "${HOOK_TEST_MOCK_PR_HEAD+x}" ]; then
                        _pr_head="$HOOK_TEST_MOCK_PR_HEAD"
                        _pr_base="${HOOK_TEST_MOCK_PR_BASE:-main}"
                    elif command -v gh >/dev/null 2>&1; then
                        _pr_head="$(gh pr view "$_pr_num" --json headRefName --jq .headRefName 2>/dev/null)"
                        _pr_base="$(gh pr view "$_pr_num" --json baseRefName --jq .baseRefName 2>/dev/null)"
                    else
                        _pr_head=""
                        _pr_base=""
                    fi
                    case "$_pr_head" in
                        wave[0-9]*-*)
                            : # wave integration branch — permitted source
                            ;;
                        *)
                            _deny "gh pr merge allowed only for wave<N>-* head branches (resolved head: '${_pr_head:-<unresolved>}')"
                            ;;
                    esac
                    if [ "$_pr_base" != "main" ]; then
                        _deny "gh pr merge allowed only into main (resolved base: '${_pr_base:-<unresolved>}')"
                    fi
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
