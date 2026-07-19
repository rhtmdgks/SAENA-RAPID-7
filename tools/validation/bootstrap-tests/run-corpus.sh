#!/bin/sh
# tools/validation/bootstrap-tests/run-corpus.sh
#
# POSIX sh corpus runner for scripts/bootstrap-claude.sh (w6-10), mirroring
# the tools/validation/hook-tests/run-corpus.sh style.
#
# For each tools/validation/bootstrap-tests/corpus/*.json fixture:
#   - build the script's argv from the fixture's "argv" field
#     (default "--check"; flags only, intentionally word-split)
#   - apply "env" overrides for that invocation only:
#       PATH_SHIMS   name of a shims/<set> dir; child PATH becomes
#                    <shims/set>:/usr/bin:/bin (deterministic tool
#                    visibility: uv/claude come from stubs, git from the OS)
#       TMP_HOME     "1" => fresh mktemp HOME for the invocation
#       TMP_CLAUDE_CONFIG_DIR  "1" => fresh mktemp CLAUDE_CONFIG_DIR
#       RUN_FROM     working directory for the invocation (default: this dir)
#   - compare actual exit code to "expect_exit"
#   - assert "expect_stdout_contains" / "expect_stdout_not_contains"
#   - print a PASS/FAIL table row per fixture
#
# Exit 0 if all fixtures pass, nonzero if any fixture fails.
#
# No jq (ADR-0019 constraint) — fixture JSON is small and flat enough for
# the same awk-based brace-matching extractor as hook-tests (duplicated
# deliberately so this runner has no dependency on hook internals).

_runner_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
_repo_root="$(CDPATH='' cd -- "$_runner_dir/../../.." && pwd)"
_script="$_repo_root/scripts/bootstrap-claude.sh"
_corpus_dir="$_runner_dir/corpus"
_shims_dir="$_runner_dir/shims"

if [ ! -f "$_script" ]; then
    echo "run-corpus: bootstrap script not found: $_script" >&2
    exit 1
fi
if [ ! -d "$_corpus_dir" ]; then
    echo "run-corpus: corpus directory not found: $_corpus_dir" >&2
    exit 1
fi

# _extract_raw_field TEXT KEY — prints the raw JSON value (string or object)
# for top-level KEY in TEXT (same technique as hook-tests/run-corpus.sh).
_extract_raw_field() {
    _erf_text="$1"
    _erf_key="$2"
    printf '%s' "$_erf_text" | awk -v key="$_erf_key" '
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
            if (rest == "") { exit 1 }
            first = substr(rest, 1, 1)
            if (first == "\"") {
                out = ""
                i = 2
                n = length(rest)
                esc = 0
                closed = 0
                while (i <= n) {
                    c = substr(rest, i, 1)
                    if (esc == 1) {
                        if (c == "n") { out = out "\n" }
                        else if (c == "t") { out = out "\t" }
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
            } else if (first == "{" || first == "[") {
                openc = first
                closec = (first == "{") ? "}" : "]"
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
                        else if (c == openc) { depth++ }
                        else if (c == closec) {
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
                i = 1
                n = length(rest)
                out = ""
                while (i <= n) {
                    c = substr(rest, i, 1)
                    if (c == "," || c == "}" || c == " " || c == "\n") { break }
                    out = out c
                    i++
                }
                print out
                exit 0
            }
        }
    '
}

_pass_count=0
_fail_count=0
_rows=""

for _fixture in "$_corpus_dir"/*.json; do
    [ -f "$_fixture" ] || continue
    _fixture_name="$(basename "$_fixture")"
    _fixture_text="$(cat "$_fixture")"

    _argv="$(_extract_raw_field "$_fixture_text" "argv")"
    [ -n "$_argv" ] || _argv="--check"

    _expect_exit="$(_extract_raw_field "$_fixture_text" "expect_exit")"
    [ -n "$_expect_exit" ] || _expect_exit=0

    _expect_contains="$(_extract_raw_field "$_fixture_text" "expect_stdout_contains")"
    _expect_not_contains="$(_extract_raw_field "$_fixture_text" "expect_stdout_not_contains")"

    _env_json="$(_extract_raw_field "$_fixture_text" "env")"
    _path_shims=""
    _tmp_home=""
    _tmp_ccd=""
    _run_from=""
    if [ -n "$_env_json" ]; then
        _path_shims="$(_extract_raw_field "$_env_json" "PATH_SHIMS")"
        _tmp_home="$(_extract_raw_field "$_env_json" "TMP_HOME")"
        _tmp_ccd="$(_extract_raw_field "$_env_json" "TMP_CLAUDE_CONFIG_DIR")"
        _run_from="$(_extract_raw_field "$_env_json" "RUN_FROM")"
    fi

    _child_path="$PATH"
    if [ -n "$_path_shims" ]; then
        if [ ! -d "$_shims_dir/$_path_shims" ]; then
            _rows="$_rows
FAIL | $_fixture_name | unknown shim set: $_path_shims"
            _fail_count=$((_fail_count + 1))
            continue
        fi
        _child_path="$_shims_dir/$_path_shims:/usr/bin:/bin"
    fi

    _child_home="$HOME"
    _made_home=""
    if [ "$_tmp_home" = "1" ]; then
        _child_home="$(mktemp -d)"
        _made_home="$_child_home"
    fi

    _child_ccd="${CLAUDE_CONFIG_DIR:-}"
    _made_ccd=""
    if [ "$_tmp_ccd" = "1" ]; then
        _child_ccd="$(mktemp -d)"
        _made_ccd="$_child_ccd"
    fi

    _child_cwd="$_runner_dir"
    if [ -n "$_run_from" ]; then
        _child_cwd="$_run_from"
    fi

    # argv holds whitespace-separated flags only; word-splitting is the point.
    # shellcheck disable=SC2086
    _actual_stdout="$(cd "$_child_cwd" && PATH="$_child_path" HOME="$_child_home" CLAUDE_CONFIG_DIR="$_child_ccd" sh "$_script" $_argv 2>/dev/null)"
    _actual_exit=$?

    [ -n "$_made_home" ] && rm -rf "$_made_home" 2>/dev/null
    [ -n "$_made_ccd" ] && rm -rf "$_made_ccd" 2>/dev/null

    _status="PASS"
    _reason=""

    if [ "$_actual_exit" != "$_expect_exit" ]; then
        _status="FAIL"
        _reason="exit=$_actual_exit expected=$_expect_exit"
    fi

    if [ "$_status" = "PASS" ] && [ -n "$_expect_contains" ]; then
        case "$_actual_stdout" in
            *"$_expect_contains"*) ;;
            *)
                _status="FAIL"
                _reason="stdout missing expected substring: $_expect_contains"
                ;;
        esac
    fi

    if [ "$_status" = "PASS" ] && [ -n "$_expect_not_contains" ]; then
        case "$_actual_stdout" in
            *"$_expect_not_contains"*)
                _status="FAIL"
                _reason="stdout unexpectedly contains: $_expect_not_contains"
                ;;
        esac
    fi

    if [ "$_status" = "PASS" ]; then
        _pass_count=$((_pass_count + 1))
        _rows="$_rows
PASS | $_fixture_name | exit=$_actual_exit"
    else
        _fail_count=$((_fail_count + 1))
        _rows="$_rows
FAIL | $_fixture_name | $_reason"
    fi
done

echo "STATUS | FIXTURE | DETAIL"
echo "------ | ------- | ------"
printf '%s\n' "$_rows" | awk 'NF > 0'

echo ""
echo "Total: $((_pass_count + _fail_count))  Pass: $_pass_count  Fail: $_fail_count"

if [ "$_fail_count" -gt 0 ]; then
    exit 1
fi
exit 0
