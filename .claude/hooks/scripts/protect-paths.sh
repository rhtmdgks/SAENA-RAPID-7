#!/bin/sh
# .claude/hooks/scripts/protect-paths.sh
#
# PreToolUse hook for Write|Edit|MultiEdit. ADR-0019 hook #3.
#
# Resolves the target file_path relative to repo root and matches it against
# the protected-paths policy list. If protected, emits an ask-JSON response
# (inline human-approval routing — NOT a hard deny) with a reason naming the
# matched glob. Otherwise exits 0.
#
# Policy source precedence:
#   1. ${POLICY_FILE} if set and exists.
#   2. tools/validation/policy/protected-paths.txt if it exists (T08).
#   3. Built-in fallback list (noted in the ask reason as a fallback).
#
# If tools/validation/check-protected-paths.sh exists and is executable,
# delegate matching to it (single implementation, T08) — this script only
# reformats its verdict into the ask-JSON shape. Otherwise use the internal
# matcher against the policy list above.
#
# Fail-to-ask: on any parse/resolution error, still emit ask-JSON rather
# than silently allowing (ADR-0019: "protect-paths는 fail-to-ask").
#
# Contract: stdin = Claude Code PreToolUse JSON
#   {"tool_name":"Write","tool_input":{"file_path":"..."}}
#   (MultiEdit may carry file_path at the same top-level tool_input key.)

_hook_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_lib_dir="$_hook_dir/lib"
_repo_root="$(CDPATH= cd -- "$_hook_dir/../../.." && pwd)"

# --- DISABLED kill switch -----------------------------------------------
if [ -f "$_hook_dir/../DISABLED" ]; then
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    _audit_dir="$_repo_root/audit/agent-hooks"
    mkdir -p "$_audit_dir" 2>/dev/null
    printf '{"ts":"%s","tool_name":"Write|Edit|MultiEdit","hook":"protect-paths","decision":"DISABLED-bypass"}\n' "$_ts" >>"$_audit_dir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null
    exit 0
fi

# shellcheck source=lib/json-field.sh
. "$_lib_dir/json-field.sh"

_ask_json() {
    _reason="$1"
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}\n' "$_reason"
    exit 0
}

_stdin_json="$(cat)"

_file_path="$(json_field "$_stdin_json" "tool_input.file_path")"
if [ $? -ne 0 ] || [ -z "$_file_path" ]; then
    _ask_json "protect-paths: could not parse tool_input.file_path from stdin JSON — fail-to-ask (ADR-0019)"
fi

# Resolve relative to repo root: strip a leading repo-root prefix if the
# path is already absolute; otherwise treat as already-relative.
case "$_file_path" in
    "$_repo_root"/*)
        _rel_path="${_file_path#"$_repo_root"/}"
        ;;
    /*)
        # Absolute path outside repo root — cannot classify, fail-to-ask.
        _ask_json "protect-paths: absolute file_path outside repo root — fail-to-ask (ADR-0019)"
        ;;
    *)
        _rel_path="$_file_path"
        ;;
esac

# Prefer delegating to tools/validation/check-protected-paths.sh (T08,
# single implementation) if it exists and is executable.
_delegate="$_repo_root/tools/validation/check-protected-paths.sh"
if [ -x "$_delegate" ]; then
    if "$_delegate" "$_rel_path" >/tmp/protect-paths.delegate.$$ 2>&1; then
        rm -f /tmp/protect-paths.delegate.$$ 2>/dev/null
        exit 0
    else
        _matched="$(cat /tmp/protect-paths.delegate.$$ 2>/dev/null)"
        rm -f /tmp/protect-paths.delegate.$$ 2>/dev/null
        [ -z "$_matched" ] && _matched="protected path (see tools/validation/check-protected-paths.sh)"
        _ask_json "protected path matched: $_matched — human approval required (ADR-0019 hook #3, delegated match)"
    fi
fi

# Internal matcher: resolve the policy file.
_policy_file="${POLICY_FILE:-}"
_policy_source="POLICY_FILE env"
if [ -z "$_policy_file" ] || [ ! -f "$_policy_file" ]; then
    if [ -f "$_repo_root/tools/validation/policy/protected-paths.txt" ]; then
        _policy_file="$_repo_root/tools/validation/policy/protected-paths.txt"
        _policy_source="tools/validation/policy/protected-paths.txt"
    else
        _policy_file=""
        _policy_source="built-in fallback list (canonical policy file not found)"
    fi
fi

_match_glob() {
    # _match_glob PATTERN PATH — POSIX glob-ish match where trailing /**
    # means "this dir and everything under it", and trailing /* means
    # "direct children only". No external dependency.
    _mg_pat="$1"
    _mg_path="$2"
    case "$_mg_pat" in
        */\*\*)
            _mg_prefix="${_mg_pat%/\*\*}"
            case "$_mg_path" in
                "$_mg_prefix"|"$_mg_prefix"/*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        */\*)
            _mg_prefix="${_mg_pat%/\*}"
            case "$_mg_path" in
                "$_mg_prefix"/*)
                    _mg_tail="${_mg_path#"$_mg_prefix"/}"
                    case "$_mg_tail" in
                        */*) return 1 ;;
                        *) return 0 ;;
                    esac
                    ;;
                *) return 1 ;;
            esac
            ;;
        *\*)
            _mg_prefix="${_mg_pat%\*}"
            case "$_mg_path" in
                "$_mg_prefix"*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        *)
            [ "$_mg_path" = "$_mg_pat" ] && return 0
            return 1
            ;;
    esac
}

if [ -n "$_policy_file" ]; then
    while IFS= read -r _pat || [ -n "$_pat" ]; do
        case "$_pat" in
            ""|\#*) continue ;;
        esac
        if _match_glob "$_pat" "$_rel_path"; then
            _ask_json "protected path matched '$_pat' (source: $_policy_source) — human approval required (ADR-0019 hook #3)"
        fi
    done <"$_policy_file"
    exit 0
fi

# Built-in fallback list (used only if no policy file resolvable at all).
for _pat in \
    "docs/specs/**" \
    "packages/contracts/**" \
    "packages/schemas/**" \
    "events/**" \
    "workflows/**" \
    "deploy/**" \
    ".cursor/rules/**" \
    ".claude/*"
do
    if _match_glob "$_pat" "$_rel_path"; then
        _ask_json "protected path matched '$_pat' (source: built-in fallback — canonical policy file not found) — human approval required (ADR-0019 hook #3)"
    fi
done

exit 0
