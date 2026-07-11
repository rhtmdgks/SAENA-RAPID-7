#!/bin/sh
# check-adr-status.sh — pre-commit/CI guard: block ADR Status transitions to
# "accepted" from automation (CLAUDE.md: "accepted 전환은 인간 결정만").
#
# POSIX sh only (macOS bash 3.2 safe). No jq, no network access.
#
# Detects changes to the front-matter "- Status: <value>" line and the
# "## Status" section body in docs/decisions/ADR-*.md. If any such change
# introduces a transition to "accepted", the guard blocks.
#
# Usage:
#   check-adr-status.sh              # inspects `git diff --cached` (staged)
#   check-adr-status.sh <range>      # inspects `git diff <range>` instead,
#                                     # e.g. check-adr-status.sh main..HEAD
#
# Exit 0 — no ADR Status line transitioned to "accepted" (non-Status edits,
#          or Status edits to values other than "accepted", are allowed).
# Exit 5 — a Status line transitioned to "accepted"; prints
#          "ADR Status→accepted is a human-only transition (CLAUDE.md)"
#          plus the offending file(s).
# Exit 2 — usage / git error (fail-closed).

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)

RANGE="${1:-}"

cd "$REPO_ROOT"

TMP_DIFF=$(mktemp "${TMPDIR:-/tmp}/check-adr-status.diff.XXXXXX")
TMP_HITS=$(mktemp "${TMPDIR:-/tmp}/check-adr-status.hits.XXXXXX")
trap 'rm -f "$TMP_DIFF" "$TMP_HITS"' EXIT INT TERM

if [ -n "$RANGE" ]; then
    if ! git diff -U0 "$RANGE" -- docs/decisions/ADR-*.md > "$TMP_DIFF" 2>/dev/null; then
        echo "check-adr-status: git diff failed for range '$RANGE'" >&2
        exit 2
    fi
else
    if ! git diff --cached -U0 -- docs/decisions/ADR-*.md > "$TMP_DIFF" 2>/dev/null; then
        echo "check-adr-status: git diff --cached failed" >&2
        exit 2
    fi
fi

if [ ! -s "$TMP_DIFF" ]; then
    exit 0
fi

: > "$TMP_HITS"
current_file="(unknown)"
# Newly added ADR files (--- /dev/null) may land already-accepted when a human
# authored the decision in the same change set. Block only Status flips on
# *existing* ADRs (automation cannot promote proposed→accepted).
is_new_file=0

while IFS= read -r line; do
    case "$line" in
        "diff --git "*)
            is_new_file=0
            continue
            ;;
        "--- /dev/null")
            is_new_file=1
            continue
            ;;
        "+++ b/"*)
            current_file=${line#+++ b/}
            continue
            ;;
    esac

    # Skip Status checks for brand-new ADR files.
    if [ "$is_new_file" -eq 1 ]; then
        continue
    fi

    case "$line" in
        "+- Status:"*)
            value=${line#+- Status:}
            value=$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            case "$value" in
                accepted|accepted\ *)
                    echo "VIOLATION:${current_file}: front-matter '- Status:' line -> accepted" >> "$TMP_HITS"
                    ;;
            esac
            ;;
        "+accepted"|"+accepted "*)
            # -U0 hunks only show changed lines, so a bare added "accepted"
            # line within the docs/decisions/ADR-*.md pathspec is the
            # "## Status" section-body value changing to accepted.
            echo "VIOLATION:${current_file}: '## Status' section body -> accepted" >> "$TMP_HITS"
            ;;
    esac
done < "$TMP_DIFF"

if [ -s "$TMP_HITS" ]; then
    echo "ADR Status→accepted is a human-only transition (CLAUDE.md)" >&2
    cat "$TMP_HITS" >&2
    exit 5
fi

exit 0
