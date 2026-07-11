#!/bin/sh
# tools/validation/hook-tests/run-corpus.sh
#
# POSIX sh corpus runner for the ADR-0019 dev-repo safety hook scripts.
#
# For each tools/validation/hook-tests/corpus/*.json fixture:
#   - resolve which .claude/hooks/scripts/<hook>.sh to invoke from the
#     fixture's "hook" field
#   - extract the fixture's "stdin" object (raw JSON) and pipe it to the
#     script's stdin
#   - apply any "env" overrides from the fixture (HOOK_TEST_MOCK_CONTEXT,
#     POLICY_FILE, ...) for that invocation only
#   - compare actual exit code to "expect_exit"
#   - if "expect_stdout_contains" is set, assert the script's stdout
#     contains that substring
#   - if "expect_stdout_not_contains" is set, assert the script's stdout
#     does NOT contain that substring
#   - print a PASS/FAIL table row per fixture
#
# Exit 0 if all fixtures pass, nonzero if any fixture fails.
#
# No jq (ADR-0019 constraint) — fixture JSON is small and flat enough for
# an awk-based brace-matching extractor, same technique as
# .claude/hooks/scripts/lib/json-field.sh.

_runner_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
_repo_root="$(CDPATH= cd -- "$_runner_dir/../../.." && pwd)"
_scripts_dir="$_repo_root/.claude/hooks/scripts"
_corpus_dir="$_runner_dir/corpus"
_fixtures_dir="$_runner_dir/fixtures"

if [ ! -d "$_corpus_dir" ]; then
    echo "run-corpus: corpus directory not found: $_corpus_dir" >&2
    exit 1
fi

# _extract_raw_field TEXT KEY — prints the raw JSON value (string or object)
# for top-level KEY in TEXT. Same brace/quote-aware scan as
# lib/json-field.sh's _jf_extract_raw, duplicated here so the test runner
# has no dependency on sourcing hook internals (keeps the runner decoupled
# from hook implementation changes).
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
                # bare literal (number/true/false/null) — read until , or }
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

    _hook_name="$(_extract_raw_field "$_fixture_text" "hook")"
    if [ -z "$_hook_name" ]; then
        _rows="$_rows
FAIL | $_fixture_name | (could not parse 'hook' field)"
        _fail_count=$((_fail_count + 1))
        continue
    fi

    _hook_script="$_scripts_dir/$_hook_name.sh"
    if [ ! -x "$_hook_script" ]; then
        _rows="$_rows
FAIL | $_fixture_name | hook script not found/executable: $_hook_script"
        _fail_count=$((_fail_count + 1))
        continue
    fi

    _stdin_json="$(_extract_raw_field "$_fixture_text" "stdin")"
    if [ -z "$_stdin_json" ]; then
        _rows="$_rows
FAIL | $_fixture_name | (could not parse 'stdin' field)"
        _fail_count=$((_fail_count + 1))
        continue
    fi

    _expect_exit="$(_extract_raw_field "$_fixture_text" "expect_exit")"
    [ -z "$_expect_exit" ] && _expect_exit=0

    _expect_contains="$(_extract_raw_field "$_fixture_text" "expect_stdout_contains")"
    _expect_not_contains="$(_extract_raw_field "$_fixture_text" "expect_stdout_not_contains")"

    _env_json="$(_extract_raw_field "$_fixture_text" "env")"
    _mock_context=""
    _mock_branch=""
    _policy_file_override=""
    if [ -n "$_env_json" ]; then
        _mock_context="$(_extract_raw_field "$_env_json" "HOOK_TEST_MOCK_CONTEXT")"
        _policy_file_override="$(_extract_raw_field "$_env_json" "POLICY_FILE")"
        _mock_branch="$(_extract_raw_field "$_env_json" "HOOK_TEST_MOCK_BRANCH")"
    fi

    # protect-paths fixtures use the corpus-local policy copy by default
    # unless a fixture explicitly overrides POLICY_FILE.
    if [ "$_hook_name" = "protect-paths" ] && [ -z "$_policy_file_override" ]; then
        _policy_file_override="$_fixtures_dir/protected-paths.txt"
    fi

    _actual_stdout="$(printf '%s' "$_stdin_json" | HOOK_TEST_MOCK_CONTEXT="$_mock_context" POLICY_FILE="$_policy_file_override" HOOK_TEST_MOCK_BRANCH="$_mock_branch" sh "$_hook_script" 2>/tmp/run-corpus.stderr.$$)"
    _actual_exit=$?
    rm -f /tmp/run-corpus.stderr.$$ 2>/dev/null

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
