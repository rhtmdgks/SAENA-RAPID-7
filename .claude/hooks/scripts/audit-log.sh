#!/bin/sh
# .claude/hooks/scripts/audit-log.sh
#
# PostToolUse hook (any tool). ADR-0019 hook #4.
#
# Appends one JSONL line to audit/agent-hooks/<YYYY-MM-DD>.jsonl:
#   {"ts":ISO8601,"tool_name":...,"decision":"observed","summary":...}
# summary = first 160 chars of command/file_path AFTER redaction.
#
# IMPORTANT — honest label (ADR-0019 hook #4 / CLAUDE.md #11): this JSONL
# trail is a dev-repo debugging aid ONLY. It is NOT the FORGE immutable
# audit ledger (that is a W3 runtime artifact with different guarantees).
# The file header line makes this explicit on first creation of each daily
# file.
#
# Never logs full env or the complete stdin payload — only a short,
# redacted summary field.
#
# Contract: stdin = Claude Code PostToolUse JSON, at minimum
#   {"tool_name":"...","tool_input":{"command":"..."}}  (Bash)
#   {"tool_name":"...","tool_input":{"file_path":"..."}} (Write/Edit)
# This hook is observational/non-blocking: it always exits 0, even on parse
# failure (best-effort logging must never break the user's tool call).

_hook_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_lib_dir="$_hook_dir/lib"
_repo_root="$(CDPATH= cd -- "$_hook_dir/../../.." && pwd)"
_audit_dir="${HOOK_TEST_AUDIT_DIR:-$_repo_root/audit/agent-hooks}"

# --- DISABLED kill switch -----------------------------------------------
if [ -f "$_hook_dir/../DISABLED" ]; then
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    mkdir -p "$_audit_dir" 2>/dev/null
    printf '{"ts":"%s","tool_name":"unknown","hook":"audit-log","decision":"DISABLED-bypass"}\n' "$_ts" >>"$_audit_dir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null
    exit 0
fi

# shellcheck source=lib/json-field.sh
. "$_lib_dir/json-field.sh"

_stdin_json="$(cat)"

_tool_name="$(json_field "$_stdin_json" "tool_name")"
[ -z "$_tool_name" ] && _tool_name="unknown"

_raw_summary="$(json_field "$_stdin_json" "tool_input.command")"
if [ -z "$_raw_summary" ]; then
    _raw_summary="$(json_field "$_stdin_json" "tool_input.file_path")"
fi
[ -z "$_raw_summary" ] && _raw_summary="(no command/file_path field found)"

# Redaction (ADR-0019 hook #4): mask secret-shaped tokens before truncation
# so a secret spanning the 160-char cut point cannot leak a partial value.
#   (?i)(token|secret|password|api[_-]?key|authorization|bearer)[=: ][^ ]* -> \1=REDACTED
#   AKIA[0-9A-Z]{16} -> AKIA_REDACTED
_redacted="$(printf '%s' "$_raw_summary" | awk '
    {
        line = $0
        # Case-insensitive-ish: build a lowercase shadow to find match
        # positions, but keep original casing for output outside matches.
        result = ""
        rest = line
        while (1) {
            lower_rest = tolower(rest)
            best_pos = 0
            best_key = ""
            n = split("token secret password api_key api-key apikey authorization bearer", keys, " ")
            for (k = 1; k <= n; k++) {
                p = index(lower_rest, keys[k])
                if (p > 0 && (best_pos == 0 || p < best_pos)) {
                    best_pos = p
                    best_key = keys[k]
                }
            }
            if (best_pos == 0) {
                result = result rest
                break
            }
            result = result substr(rest, 1, best_pos - 1)
            after_key = substr(rest, best_pos + length(best_key))
            # require a following [=: ] separator per spec pattern
            sep = substr(after_key, 1, 1)
            if (sep == "=" || sep == ":" || sep == " ") {
                result = result substr(rest, best_pos, length(best_key)) sep "REDACTED"
                tail = substr(after_key, 2)
                # skip the rest of the original token (non-space run) that we just redacted
                i = 1
                tn = length(tail)
                while (i <= tn) {
                    c = substr(tail, i, 1)
                    if (c == " ") { break }
                    i++
                }
                rest = substr(tail, i)
            } else {
                # not actually a key=value shape here — emit key literally and continue
                result = result substr(rest, best_pos, length(best_key))
                rest = after_key
            }
        }
        print result
    }
' | awk '
    {
        line = $0
        result = ""
        rest = line
        while (1) {
            p = match(rest, /AKIA[0-9A-Z]{16}/)
            if (p == 0) {
                result = result rest
                break
            }
            result = result substr(rest, 1, p - 1) "AKIA_REDACTED"
            rest = substr(rest, p + RLENGTH)
        }
        print result
    }
')"

_summary="$(printf '%s' "$_redacted" | awk '{ print substr($0, 1, 160) }')"

_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
_day="$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)"

mkdir -p "$_audit_dir" 2>/dev/null

_log_file="$_audit_dir/$_day.jsonl"
if [ ! -f "$_log_file" ]; then
    printf '{"_note":"dev-repo hook audit trail — NOT the FORGE immutable audit ledger"}\n' >"$_log_file" 2>/dev/null
fi

# Escape double quotes and backslashes in summary for safe JSON embedding.
_summary_escaped="$(printf '%s' "$_summary" | awk '{ gsub(/\\/, "\\\\\\\\"); gsub(/"/, "\\\""); print }')"

printf '{"ts":"%s","tool_name":"%s","decision":"observed","summary":"%s"}\n' \
    "$_ts" "$_tool_name" "$_summary_escaped" >>"$_log_file" 2>/dev/null

exit 0
