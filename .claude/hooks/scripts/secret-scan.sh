#!/bin/sh
# .claude/hooks/scripts/secret-scan.sh
#
# SessionStart hook. ADR-0019 hook #5.
#
# Runs `gitleaks protect --staged --no-banner --redact` to scan ONLY the
# staged/uncommitted diff (not full repo history — CI owns full-history
# scanning per ADR-0020). This is intentionally cheap and best-effort:
# SessionStart hooks are non-blocking by design (ADR-0019), so this script
# ALWAYS exits 0, but prints a loud warning to stderr if gitleaks finds
# something, or if gitleaks is not installed at all.

_hook_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_repo_root="$(CDPATH= cd -- "$_hook_dir/../../.." && pwd)"

# --- DISABLED kill switch -----------------------------------------------
if [ -f "$_hook_dir/../DISABLED" ]; then
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    _audit_dir="$_repo_root/audit/agent-hooks"
    mkdir -p "$_audit_dir" 2>/dev/null
    printf '{"ts":"%s","tool_name":"SessionStart","hook":"secret-scan","decision":"DISABLED-bypass"}\n' "$_ts" >>"$_audit_dir/$(date -u +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d).jsonl" 2>/dev/null
    exit 0
fi

if ! command -v gitleaks >/dev/null 2>&1; then
    echo "secret-scan: gitleaks not installed — session secret scan skipped (CI covers full history)" >&2
    exit 0
fi

cd "$_repo_root" 2>/dev/null || exit 0

# Do NOT pass --exit-code 0 — we want gitleaks' real exit code (nonzero on
# findings) so we can distinguish "found something" from "clean scan", and
# print the finding context lines as a loud warning either way.
_gitleaks_out="$(gitleaks protect --staged --no-banner --redact 2>&1)"
_gitleaks_rc=$?

if [ "$_gitleaks_rc" -ne 0 ]; then
    echo "secret-scan: WARNING — gitleaks found possible secrets in staged/uncommitted changes (exit $_gitleaks_rc):" >&2
    printf '%s\n' "$_gitleaks_out" >&2
fi

# SessionStart is always non-blocking (ADR-0019) — findings are surfaced as
# a loud warning only, never a block.
exit 0
