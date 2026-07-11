#!/bin/sh
# .claude/hooks/scripts/lib/normalize-command.sh
#
# Sourced helper — NOT executable standalone. Given a raw shell command
# string, produce a normalized set of "segments" (one per line on stdout)
# suitable for per-segment policy matching by deny-deploy-push.sh and
# deny-unpinned-install.sh.
#
# Normalization steps (ADR-0019 C-1: allowlist-first, must not be
# bypassable by trivial wrapping):
#   1. Split the raw command on `&&`, `;`, `|` into segments.
#   2. Per segment: strip leading environment-variable assignments
#      (FOO=bar BAZ=qux realcmd ...).
#   3. Unwrap a leading `env ...` invocation (env FOO=bar realcmd ...).
#   4. Unwrap `sh -c "..."` / `bash -c '...'` — extract the inner string and
#      recurse the whole normalization ONCE on that inner string (its
#      resulting segments are appended in place of the wrapper segment).
#   5. Collapse `git -c key=val` option pairs — drop each `-c key=val` pair,
#      keep the verb (git) and subcommand so `git -c http.extraHeader=x
#      push` normalizes to `git push`.
#   6. Case is preserved (no lowercasing) per spec.
#
# Usage:
#   normalize_command "$raw_command"
#   # prints one normalized segment per line to stdout
#
# This is intentionally conservative: it recurses into sh -c/bash -c
# exactly once (not unboundedly) to bound execution time and avoid
# unbounded recursion on adversarial input, per <100ms target.

normalize_command() {
    _nc_raw="$1"
    _nc_depth="${2:-0}"

    # Split on && ; | (top-level only — good enough for our matching needs;
    # we are not writing a full shell parser, just enough to defeat the
    # documented C-1 bypass patterns).
    printf '%s' "$_nc_raw" | awk '
        BEGIN { seg = ""; n = 0 }
        {
            line = $0
            len = length(line)
            i = 1
            instr = 0
            qc = ""
            esc = 0
            buf = ""
            while (i <= len) {
                c = substr(line, i, 1)
                c2 = substr(line, i, 2)
                if (instr == 1) {
                    buf = buf c
                    if (esc == 1) { esc = 0 }
                    else if (c == "\\") { esc = 1 }
                    else if (c == qc) { instr = 0 }
                    i++
                    continue
                }
                if (c == "\"" || c == "'"'"'") {
                    instr = 1
                    qc = c
                    buf = buf c
                    i++
                    continue
                }
                if (c2 == "&&" || c2 == "||") {
                    print buf
                    buf = ""
                    i += 2
                    continue
                }
                if (c == ";" || c == "|") {
                    print buf
                    buf = ""
                    i++
                    continue
                }
                buf = buf c
                i++
            }
            print buf
        }
    ' | while IFS= read -r _nc_seg; do
        _nc_normalize_one_segment "$_nc_seg" "$_nc_depth"
    done
}

# _nc_normalize_one_segment SEGMENT DEPTH
_nc_normalize_one_segment() {
    _nos_seg="$1"
    _nos_depth="$2"

    # trim leading/trailing whitespace
    _nos_seg="$(printf '%s' "$_nos_seg" | awk '{ gsub(/^[ \t]+|[ \t]+$/, ""); print }')"
    [ -z "$_nos_seg" ] && return 0

    # Strip leading VAR=val assignments (may be several in a row).
    _nos_seg="$(printf '%s' "$_nos_seg" | awk '
        {
            n = split($0, parts, " ")
            i = 1
            while (i <= n && parts[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { i++ }
            out = ""
            for (j = i; j <= n; j++) {
                out = (out == "" ? parts[j] : out " " parts[j])
            }
            print out
        }
    ')"
    [ -z "$_nos_seg" ] && return 0

    # Unwrap leading `env ...` — env itself may take -i/-u/VAR=val args
    # before the real command; strip `env` plus any VAR=val tokens that
    # follow it.
    case "$_nos_seg" in
        env\ *)
            _nos_seg="$(printf '%s' "$_nos_seg" | awk '
                {
                    n = split($0, parts, " ")
                    i = 2
                    while (i <= n && (parts[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || parts[i] == "-i" || parts[i] == "-u")) { i++ }
                    out = ""
                    for (j = i; j <= n; j++) {
                        out = (out == "" ? parts[j] : out " " parts[j])
                    }
                    print out
                }
            ')"
            ;;
    esac
    [ -z "$_nos_seg" ] && return 0

    # Unwrap `sh -c "..."` / `bash -c '...'` — recurse ONCE on inner string.
    case "$_nos_seg" in
        sh\ -c\ \"*\"|bash\ -c\ \"*\"|sh\ -c\ \'*\'|bash\ -c\ \'*\')
            if [ "$_nos_depth" -lt 1 ]; then
                _nos_inner="$(printf '%s' "$_nos_seg" | awk '
                    {
                        line = $0
                        # find first quote char after "-c "
                        idx = index(line, "-c ")
                        if (idx == 0) { exit 1 }
                        rest = substr(line, idx + 3)
                        qc = substr(rest, 1, 1)
                        if (qc != "\"" && qc != "'"'"'") { exit 1 }
                        rest = substr(rest, 2)
                        # strip trailing matching quote
                        rlen = length(rest)
                        if (substr(rest, rlen, 1) == qc) {
                            rest = substr(rest, 1, rlen - 1)
                        }
                        print rest
                    }
                ')"
                if [ -n "$_nos_inner" ]; then
                    normalize_command "$_nos_inner" "$((_nos_depth + 1))"
                    return 0
                fi
            fi
            ;;
    esac

    # Collapse `git -c key=val` pairs: drop each `-c key=val` token pair
    # that immediately follows `git`, keep verb + subcommand.
    case "$_nos_seg" in
        git\ -c\ *)
            _nos_seg="$(printf '%s' "$_nos_seg" | awk '
                {
                    n = split($0, parts, " ")
                    out = parts[1]
                    i = 2
                    while (i <= n) {
                        if (parts[i] == "-c" && i + 1 <= n) {
                            i += 2
                            continue
                        }
                        out = out " " parts[i]
                        i++
                    }
                    print out
                }
            ')"
            ;;
    esac

    printf '%s\n' "$_nos_seg"
}
