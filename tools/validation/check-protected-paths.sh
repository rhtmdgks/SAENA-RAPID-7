#!/bin/sh
# check-protected-paths.sh — single matching implementation for protected
# paths (ADR-0019). Wrapped by the Claude Code PreToolUse hook, the
# pre-commit guard, and CI.
#
# POSIX sh only (macOS bash 3.2 safe). No jq, no network access.
#
# Usage: check-protected-paths.sh <path>...
#
# For each path argument, match against every non-comment glob line in
# tools/validation/policy/protected-paths.txt (override with $POLICY_FILE).
#
# Exit 0 — no path matched a protected glob.
# Exit 3 — at least one path matched; prints "PROTECTED:<path> matched <glob>"
#          for every match found (a path may match more than one glob).
# Exit 2 — usage / policy file error (fail-closed, per ADR-0019 engineering
#          constraint: deny hooks are fail-closed).

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
POLICY_FILE="${POLICY_FILE:-"$SCRIPT_DIR/policy/protected-paths.txt"}"

if [ "$#" -eq 0 ]; then
    echo "usage: check-protected-paths.sh <path>..." >&2
    exit 2
fi

if [ ! -f "$POLICY_FILE" ]; then
    echo "check-protected-paths: policy file not found: $POLICY_FILE" >&2
    exit 2
fi

# match_one PATH GLOB — returns 0 (true) if PATH matches GLOB.
# Supports '**' as "this prefix, at any depth" in addition to plain shell
# glob matching via a case statement.
match_one() {
    _mo_path="$1"
    _mo_glob="$2"

    case "$_mo_path" in
        $_mo_glob)
            return 0
            ;;
    esac

    # If the glob ends in "/**", also treat it as a prefix match on the
    # directory itself (e.g. "docs/specs/**" matches "docs/specs" and
    # "docs/specs/x" via the case above, but be defensive about the exact
    # directory path with no trailing content already handled above).
    case "$_mo_glob" in
        */\*\*)
            _mo_prefix=${_mo_glob%/\*\*}
            case "$_mo_path" in
                "$_mo_prefix" | "$_mo_prefix"/*)
                    return 0
                    ;;
            esac
            ;;
    esac

    return 1
}

found=0

# Read policy globs into a temp-free loop (POSIX sh: use a while-read on fd 3
# to avoid clobbering the outer path-argument loop / positional params).
for target in "$@"; do
    while IFS= read -r line <&3 || [ -n "$line" ]; do
        # strip comments and blank lines
        case "$line" in
            ''|'#'*) continue ;;
        esac
        glob=$line

        if match_one "$target" "$glob"; then
            echo "PROTECTED:$target matched $glob"
            found=1
        fi
    done 3< "$POLICY_FILE"
done

if [ "$found" -eq 1 ]; then
    exit 3
fi

exit 0
