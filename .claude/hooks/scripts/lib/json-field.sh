#!/bin/sh
# .claude/hooks/scripts/lib/json-field.sh
#
# Sourced helper — NOT executable standalone. Extracts a single top-level or
# one-level-nested string field from a small Claude Code hook JSON payload
# without jq (ADR-0019 constraint: no jq, no network, <100ms, POSIX sh /
# macOS bash 3.2 compatible).
#
# This is a DELIBERATELY NARROW parser. It only supports what Claude Code
# hook payloads actually send: a flat JSON object of string/object fields,
# where the field we want is a JSON string value (possibly containing
# backslash-escaped quotes). It does NOT implement general JSON parsing.
#
# Usage:
#   value="$(json_field "$json_text" "tool_name")"
#   value="$(json_field "$json_text" "tool_input.command")"
#
# On success: prints the unescaped string value, returns 0.
# On failure (field absent, or ambiguous/unparseable): prints nothing,
# returns 1. Callers MUST treat return 1 as "parse failure" and apply their
# own fail-closed (deny) or fail-to-ask policy — this helper never decides
# policy itself.

# json_field TEXT DOTTED_PATH
json_field() {
    _jf_text="$1"
    _jf_path="$2"

    case "$_jf_path" in
        *.*)
            _jf_outer="${_jf_path%%.*}"
            _jf_inner="${_jf_path#*.}"
            _jf_obj="$(_jf_extract_raw "$_jf_text" "$_jf_outer")" || return 1
            _jf_extract_string "$_jf_obj" "$_jf_inner"
            return $?
            ;;
        *)
            _jf_extract_string "$_jf_text" "$_jf_path"
            return $?
            ;;
    esac
}

# _jf_extract_raw TEXT KEY
# Extract the raw (still-JSON) value for KEY, whether it is a string or an
# object — used to descend into one level of nesting (e.g. tool_input).
_jf_extract_raw() {
    _jfr_text="$1"
    _jfr_key="$2"

    printf '%s' "$_jfr_text" | awk -v key="$_jfr_key" '
        BEGIN { found = 0 }
        {
            buf = buf $0 "\n"
        }
        END {
            text = buf
            keypat = "\"" key "\""
            idx = index(text, keypat)
            if (idx == 0) { exit 1 }
            rest = substr(text, idx + length(keypat))
            # skip whitespace and colon
            i = 1
            n = length(rest)
            while (i <= n) {
                c = substr(rest, i, 1)
                if (c == ":" || c == " " || c == "\t" || c == "\n" || c == "\r") { i++ } else { break }
            }
            rest = substr(rest, i)
            if (rest == "") { exit 1 }
            first = substr(rest, 1, 1)
            if (first == "\"") {
                # string value — copy including surrounding quotes,
                # honoring backslash escapes
                out = "\""
                i = 2
                n = length(rest)
                esc = 0
                closed = 0
                while (i <= n) {
                    c = substr(rest, i, 1)
                    out = out c
                    if (esc == 1) {
                        esc = 0
                    } else if (c == "\\") {
                        esc = 1
                    } else if (c == "\"") {
                        closed = 1
                        i++
                        break
                    }
                    i++
                }
                if (closed != 1) { exit 1 }
                print out
                exit 0
            } else if (first == "{") {
                depth = 0
                i = 1
                n = length(rest)
                out = ""
                instr = 0
                esc = 0
                while (i <= n) {
                    c = substr(rest, i, 1)
                    out = out c
                    if (instr == 1) {
                        if (esc == 1) { esc = 0 }
                        else if (c == "\\") { esc = 1 }
                        else if (c == "\"") { instr = 0 }
                    } else {
                        if (c == "\"") { instr = 1 }
                        else if (c == "{") { depth++ }
                        else if (c == "}") {
                            depth--
                            if (depth == 0) { i++; break }
                        }
                    }
                    i++
                }
                if (depth != 0) { exit 1 }
                print out
                exit 0
            } else {
                exit 1
            }
        }
    '
}

# _jf_extract_string TEXT KEY
# Extract a JSON string value for KEY from TEXT (TEXT is a JSON object
# fragment, possibly without well-formed outer braces — we just scan for the
# key). Prints the UNESCAPED value.
_jf_extract_string() {
    _jfs_text="$1"
    _jfs_key="$2"

    printf '%s' "$_jfs_text" | awk -v key="$_jfs_key" '
        BEGIN { buf = "" }
        { buf = buf $0 "\n" }
        END {
            text = buf
            keypat = "\"" key "\""
            idx = index(text, keypat)
            if (idx == 0) { exit 1 }
            rest = substr(text, idx + length(keypat))
            i = 1
            n = length(rest)
            while (i <= n) {
                c = substr(rest, i, 1)
                if (c == ":" || c == " " || c == "\t" || c == "\n" || c == "\r") { i++ } else { break }
            }
            rest = substr(rest, i)
            if (rest == "" || substr(rest, 1, 1) != "\"") { exit 1 }
            i = 2
            n = length(rest)
            out = ""
            esc = 0
            closed = 0
            while (i <= n) {
                c = substr(rest, i, 1)
                if (esc == 1) {
                    if (c == "n") { out = out "\n" }
                    else if (c == "t") { out = out "\t" }
                    else if (c == "\"") { out = out "\"" }
                    else if (c == "\\") { out = out "\\" }
                    else if (c == "/") { out = out "/" }
                    else { out = out c }
                    esc = 0
                } else if (c == "\\") {
                    esc = 1
                } else if (c == "\"") {
                    closed = 1
                    break
                } else {
                    out = out c
                }
                i++
            }
            if (closed != 1) { exit 1 }
            print out
            exit 0
        }
    '
}
