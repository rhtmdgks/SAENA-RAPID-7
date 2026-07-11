#!/bin/sh
# check-policy-symmetry.sh — verifies the canonical protected-paths list
# (ADR-0019) stays in sync with the three human-readable surfaces that
# describe it: CLAUDE.md, .cursor/rules/20-protected-paths.mdc, CODEOWNERS.
#
# POSIX sh only (macOS bash 3.2 safe). No jq, no network access.
#
# For every ACTIVE (non-comment) glob line in the policy file, checks that a
# normalized form of the glob appears (as a substring) in all three files.
# For CODEOWNERS, the check uses the glob's prefix up to its first glob
# metacharacter (*, ?, [) since CODEOWNERS entries are directory prefixes,
# not full globs.
#
# Exit 0 — every active glob found in all three files (or explicitly
#          allowlisted as a known gap, see below).
# Exit 4 — at least one active glob missing from at least one file it is not
#          allowlisted against; prints "MISSING:<file>:<glob>" per gap.
# Exit 2 — usage / file-not-found error (fail-closed).
#
# Known, intentional gaps (e.g. database/migrations/** not yet in CODEOWNERS)
# MUST NOT be fixed by editing CLAUDE.md, .cursor/rules/**, or CODEOWNERS from
# this script/path (those are not this unit's exclusive paths). Instead the
# glob stays ACTIVE (still enforced by check-protected-paths.sh) and the
# policy file's "# pending-symmetry:" comment block records one
# "allow-missing:" annotation line per gap, in the form:
#
#   # <glob> -> allow-missing: <FILE-KEY>[, <FILE-KEY> ...]
#
# where <FILE-KEY> is one of "CLAUDE.md", "CODEOWNERS", or "cursor rule"
# (matches the .cursor/rules/20-protected-paths.mdc check). Any file listed
# there is skipped for that glob's symmetry check (the gap is allowlisted,
# not hidden) — every other glob/file combination is still checked normally.
#
# Usage: check-policy-symmetry.sh
# Env overrides (for testability):
#   POLICY_FILE   — path to protected-paths.txt (default: tools/validation/policy/protected-paths.txt)
#   CLAUDE_FILE   — path to CLAUDE.md (default: repo root CLAUDE.md)
#   CURSOR_FILE   — path to .cursor/rules/20-protected-paths.mdc
#   CODEOWNERS_FILE — path to CODEOWNERS

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

POLICY_FILE="${POLICY_FILE:-"$SCRIPT_DIR/policy/protected-paths.txt"}"
CLAUDE_FILE="${CLAUDE_FILE:-"$REPO_ROOT/CLAUDE.md"}"
CURSOR_FILE="${CURSOR_FILE:-"$REPO_ROOT/.cursor/rules/20-protected-paths.mdc"}"
CODEOWNERS_FILE="${CODEOWNERS_FILE:-"$REPO_ROOT/CODEOWNERS"}"

for f in "$POLICY_FILE" "$CLAUDE_FILE" "$CURSOR_FILE" "$CODEOWNERS_FILE"; do
    if [ ! -f "$f" ]; then
        echo "check-policy-symmetry: file not found: $f" >&2
        exit 2
    fi
done

# glob_prefix GLOB — strip from the first glob metacharacter onward, and
# strip a trailing '/' so "packages/contracts/**" -> "packages/contracts".
glob_prefix() {
    _gp_glob="$1"
    _gp_prefix=$_gp_glob
    # cut at first '*'
    _gp_prefix=${_gp_prefix%%\**}
    # cut at first '?'
    _gp_prefix=${_gp_prefix%%\?*}
    # strip trailing slash
    case "$_gp_prefix" in
        */) _gp_prefix=${_gp_prefix%/} ;;
    esac
    printf '%s' "$_gp_prefix"
}

# dir_prefix PATH — the first path segment (top-level directory), used as a
# last-resort normalized match against CODEOWNERS-style directory entries.
dir_prefix() {
    _dp_path="$1"
    _dp_first=${_dp_path%%/*}
    printf '%s' "$_dp_first"
}

# found_in FILE NEEDLE — literal substring search, tolerant of a leading '/'
# on NEEDLE (CODEOWNERS convention) by trying both forms.
found_in() {
    _fi_file="$1"
    _fi_needle="$2"
    if grep -qF -- "$_fi_needle" "$_fi_file"; then
        return 0
    fi
    if grep -qF -- "/$_fi_needle" "$_fi_file"; then
        return 0
    fi
    return 1
}

# allow_missing GLOB FILE-KEY-SUBSTR — true if the policy file's
# "# pending-symmetry:" block contains a line of the form
# "# <glob> -> allow-missing: ..." whose allow-missing list contains a token
# matching FILE-KEY-SUBSTR (substring match, case-sensitive).
allow_missing() {
    _am_glob="$1"
    _am_key="$2"
    _am_line=$(grep -F -- "# $_am_glob -> allow-missing:" "$POLICY_FILE" 2>/dev/null || true)
    [ -n "$_am_line" ] || return 1
    case "$_am_line" in
        *"$_am_key"*) return 0 ;;
        *) return 1 ;;
    esac
}

missing=0

while IFS= read -r line; do
    case "$line" in
        ''|'#'*) continue ;;
    esac
    glob=$line
    prefix=$(glob_prefix "$glob")

    # CLAUDE.md / cursor rule: substring match on the raw glob text, falling
    # back to the metacharacter-stripped prefix (normalized form) so a
    # literal filename glob like ".claude/settings.json" still matches a
    # broader documented glob like ".claude/settings*.json" or ".claude/**"
    # in prose form is not required to be identical text.
    if found_in "$CLAUDE_FILE" "$glob" || found_in "$CLAUDE_FILE" "$prefix"; then
        :
    elif allow_missing "$glob" "CLAUDE.md"; then
        echo "ALLOWLISTED-GAP:$CLAUDE_FILE:$glob"
    else
        echo "MISSING:$CLAUDE_FILE:$glob"
        missing=1
    fi

    if found_in "$CURSOR_FILE" "$glob" || found_in "$CURSOR_FILE" "$prefix"; then
        :
    elif allow_missing "$glob" "cursor rule"; then
        echo "ALLOWLISTED-GAP:$CURSOR_FILE:$glob"
    else
        echo "MISSING:$CURSOR_FILE:$glob"
        missing=1
    fi

    # CODEOWNERS: match on the path prefix before glob metacharacters
    # (tolerating a leading '/' in CODEOWNERS entries), falling back to the
    # top-level directory segment (e.g. ".claude/settings.json" -> ".claude").
    top=$(dir_prefix "$prefix")
    if found_in "$CODEOWNERS_FILE" "$prefix" || found_in "$CODEOWNERS_FILE" "$top"; then
        :
    elif allow_missing "$glob" "CODEOWNERS"; then
        echo "ALLOWLISTED-GAP:$CODEOWNERS_FILE:$glob"
    else
        echo "MISSING:$CODEOWNERS_FILE:$glob"
        missing=1
    fi
done < "$POLICY_FILE"

if [ "$missing" -eq 1 ]; then
    exit 4
fi

exit 0
