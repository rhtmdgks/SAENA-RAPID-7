#!/bin/sh
# .claude/hooks/scripts/deny-unpinned-install.sh
#
# PreToolUse hook for Bash. ADR-0019 hook #2.
#
# Hybrid policy for package-install commands:
#   - allowlist (exit 0): uv sync (any flags), uv lock, npm ci,
#     version-pinned `uv tool install <pkg>==<ver>`, `uvx --from <pkg> ...`,
#     `brew list*` / `brew --version`.
#   - ask (JSON permissionDecision ask): uv add, pip install, npm install
#     <pkg>, pnpm add, brew install, cargo install, unpinned
#     `uv tool install <pkg>` (no ==).
#   - deny (exit 2): curl|sh-style remote installers, `pip install` with a
#     URL argument.
#   - non-install commands: exit 0 (out of scope for this hook).
#
# Contract: stdin = Claude Code PreToolUse JSON
#   {"tool_name":"Bash","tool_input":{"command":"..."}}
# Parse failure => exit 2, fail-closed.

_hook_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_lib_dir="$_hook_dir/lib"

# --- DISABLED kill switch -----------------------------------------------
if [ -f "$_hook_dir/../DISABLED" ]; then
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    _audit_dir="$_hook_dir/../../../audit/agent-hooks"
    mkdir -p "$_audit_dir" 2>/dev/null
    printf '{"ts":"%s","tool_name":"Bash","hook":"deny-unpinned-install","decision":"DISABLED-bypass"}\n' "$_ts" >>"$_audit_dir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null
    exit 0
fi

# shellcheck source=lib/json-field.sh
. "$_lib_dir/json-field.sh"
# shellcheck source=lib/normalize-command.sh
. "$_lib_dir/normalize-command.sh"

_stdin_json="$(cat)"

_command="$(json_field "$_stdin_json" "tool_input.command")"
if [ $? -ne 0 ] || [ -z "$_command" ]; then
    echo "deny-unpinned-install: could not parse tool_input.command from stdin JSON — fail-closed deny" >&2
    exit 2
fi

_ask_reason=""

_ask_json() {
    _reason="$1"
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}\n' "$_reason"
    exit 0
}

_deny() {
    echo "deny-unpinned-install: blocked — $1" >&2
    exit 2
}

# Raw-text check: curl|sh / wget|sh remote installers (adjacency destroyed
# by segment split, same rationale as deny-deploy-push.sh).
case "$_command" in
    *curl*"|"*sh|*curl*"|"*bash|*wget*"|"*sh|*wget*"|"*bash)
        _deny "curl/wget piped into a shell interpreter is forbidden (unpinned remote installer)"
        ;;
esac

_segments="$(normalize_command "$_command")"
if [ -z "$_segments" ]; then
    echo "deny-unpinned-install: could not normalize command — fail-closed deny" >&2
    exit 2
fi

# We need to inspect segments and possibly emit an ask-JSON and stop (ask
# takes priority the moment any segment matches ask, unless a later segment
# hard-denies — deny always wins). Since a `while read` on a pipe runs in a
# subshell (bash 3.2 / POSIX sh), we collect a verdict via a temp file
# rather than relying on subshell-local variables leaking out.
_verdict_file="$(mktemp 2>/dev/null || echo "/tmp/deny-unpinned-install.$$")"
: >"$_verdict_file"

printf '%s\n' "$_segments" | while IFS= read -r _seg; do
    [ -z "$_seg" ] && continue

    _first="$(printf '%s' "$_seg" | awk '{print $1}')"

    case "$_first" in
        uv)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                sync)
                    : # allowlisted, any flags
                    ;;
                lock)
                    : # allowlisted
                    ;;
                add)
                    echo "ask:uv add installs an unpinned/loosely-pinned dependency — requires human approval" >>"$_verdict_file"
                    ;;
                tool)
                    _sub2="$(printf '%s' "$_seg" | awk '{print $3}')"
                    if [ "$_sub2" = "install" ]; then
                        _pkgspec="$(printf '%s' "$_seg" | awk '{print $4}')"
                        case "$_pkgspec" in
                            *==*)
                                : # version-pinned, allowlisted
                                ;;
                            *)
                                echo "ask:uv tool install without ==<version> pin — requires human approval" >>"$_verdict_file"
                                ;;
                        esac
                    fi
                    ;;
            esac
            ;;
        uvx)
            : # allowlisted — ephemeral, resolved/locked by uv
            ;;
        npm)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                ci)
                    : # allowlisted
                    ;;
                install|i)
                    _rest="$(printf '%s' "$_seg" | awk '{ $1=""; $2=""; print }' | awk '{ gsub(/^[ \t]+/, ""); print }')"
                    if [ -n "$_rest" ]; then
                        echo "ask:npm install <pkg> — requires human approval" >>"$_verdict_file"
                    fi
                    ;;
            esac
            ;;
        pnpm)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                add)
                    echo "ask:pnpm add — requires human approval" >>"$_verdict_file"
                    ;;
            esac
            ;;
        pip|pip3)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            if [ "$_sub" = "install" ]; then
                case "$_seg" in
                    *http://*|*https://*|*git+*)
                        echo "deny:pip install with a URL/VCS argument is forbidden (unauditable source)" >>"$_verdict_file"
                        ;;
                    *)
                        echo "ask:pip install — requires human approval" >>"$_verdict_file"
                        ;;
                esac
            fi
            ;;
        brew)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                list)
                    : # allowlisted
                    ;;
                --version)
                    : # allowlisted
                    ;;
                install)
                    echo "ask:brew install — requires human approval" >>"$_verdict_file"
                    ;;
            esac
            ;;
        cargo)
            _sub="$(printf '%s' "$_seg" | awk '{print $2}')"
            case "$_sub" in
                install)
                    echo "ask:cargo install — requires human approval" >>"$_verdict_file"
                    ;;
            esac
            ;;
    esac
done

_deny_line="$(grep '^deny:' "$_verdict_file" 2>/dev/null | head -1)"
_ask_line="$(grep '^ask:' "$_verdict_file" 2>/dev/null | head -1)"
rm -f "$_verdict_file" 2>/dev/null

if [ -n "$_deny_line" ]; then
    _deny "${_deny_line#deny:}"
fi
if [ -n "$_ask_line" ]; then
    _ask_json "${_ask_line#ask:}"
fi

exit 0
