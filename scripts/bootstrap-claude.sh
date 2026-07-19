#!/bin/sh
# scripts/bootstrap-claude.sh — SAENA RAPID-7 workstation bootstrap (w6-10).
#
# POSIX sh. Runs under sh/bash/zsh, from any cwd, and is safe to *source*:
# it never calls `exit` when sourced (it finishes via `return`), never `cd`s
# the calling shell (all cd happens in subshells), sets no shell options,
# and installs no traps. A missing optional dependency NEVER terminates the
# caller. All state is namespaced `_bc_*` / `_BC_*` (variables remain
# defined in the caller after sourcing; functions are unset on the way out).
#
# Modes:
#   --check    (default) read-only verification; mutates nothing
#   --install  idempotent install/update of the uv-managed toolchain
#   --json     machine-readable report on stdout (combinable with both)
#   --help     usage
#
# Exit codes: 0 = no FAIL (WARN / N/A allowed); 1 = at least one FAIL;
#             2 = usage error.
#
# Install policy (ADR-0019 deny-unpinned-install.sh): this script only ever
# executes hook-allowlisted forms — `uv sync --locked` and version-pinned
# `uv tool install <pkg>==<ver>`. Pins come from .tool-versions (SSOT).
# gitleaks/kubectl/helm/k3d/oasdiff have no pinned uv install path and are
# REPORT-ONLY here: this script never installs them and never claims any
# scan/deploy check ran locally — CI covers them.
#
# Platforms: macOS and Linux (Linux verification runs in CI on ubuntu).
# Windows: UNTESTED — expected to work under WSL (`sh` inside a WSL
# distribution); native cmd.exe / PowerShell is NOT supported.

_BC_SHELLCHECK_PY_PIN="0.10.0.1" # optional lint tool; pinned uv wheel (baseline 2026-07-19)
_BC_EXPECTED_AGENTS=14           # .claude/agents/README.md documents the 14 agent roles

_bc_usage() {
    cat <<'EOF'
Usage: sh scripts/bootstrap-claude.sh [--check|--install] [--json] [--help]

SAENA RAPID-7 developer-machine bootstrap.

Modes:
  --check      (default) Read-only verification of the toolchain, Claude
               Code wiring (settings/hooks/agents/skills), and repo layout.
               Mutates nothing.
  --install    Idempotent install/update via hook-allowlisted commands only:
                 uv sync --locked
                 uv tool install rust-just==<pin from .tool-versions>
                 uv tool install shellcheck-py==<pin>          (optional)
               Plus, when plugin packaging exists in the checkout:
                 claude plugin marketplace add <repo-root>
                 claude plugin install saena-skill-pack@saena-rapid-7
  --json       Machine-readable report on stdout
               (schema saena.bootstrap-report/v1); combinable with both
               modes. Progress/diagnostics go to stderr.
  --help       This text.

Exit codes:
  0  no FAIL (WARN and N/A are acceptable)
  1  at least one FAIL check
  2  usage error

Environment:
  SAENA_BOOTSTRAP_ROOT   optional explicit repo root (else: git toplevel of
                         the script location, else marker walk-up; works
                         from any cwd, including paths with spaces/Unicode)
  CLAUDE_CONFIG_DIR      honored implicitly - claude plugin commands read it
                         themselves (used by tests for isolation)

Notes:
  - Sourcing this script (`. scripts/bootstrap-claude.sh --check`) is safe:
    it returns instead of exiting and never kills the parent shell.
  - gitleaks/kubectl/helm/k3d/oasdiff are report-only (no hook-allowlisted
    pinned install path); CI runs them. This script never claims otherwise.
  - Platforms: macOS + Linux (CI: ubuntu). Windows is untested; expected to
    work under WSL sh, NOT under native cmd.exe/PowerShell.
EOF
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_bc_jesc() {
    # JSON-escape a single-line string (strips control chars).
    printf '%s' "$1" | tr -d '\n\r\t' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

_bc_nl='
'

_bc_record() {
    # _bc_record <id> <status> <detail> <remedy>
    _bc_r_id="$1"
    _bc_r_status="$2"
    _bc_r_detail="$3"
    _bc_r_remedy="$4"
    _bc_r_row=$(printf '%-18s %-6s %s' "$_bc_r_id" "$_bc_r_status" "$_bc_r_detail")
    _bc_human="${_bc_human}${_bc_r_row}${_bc_nl}"
    if [ "$_bc_r_status" != "PASS" ] && [ -n "$_bc_r_remedy" ]; then
        _bc_r_row=$(printf '%18s -> remedy: %s' '' "$_bc_r_remedy")
        _bc_human="${_bc_human}${_bc_r_row}${_bc_nl}"
    fi
    _bc_json_checks="${_bc_json_checks}${_bc_json_checks:+,}{\"id\":\"$(_bc_jesc "$_bc_r_id")\",\"status\":\"$(_bc_jesc "$_bc_r_status")\",\"detail\":\"$(_bc_jesc "$_bc_r_detail")\",\"remedy\":\"$(_bc_jesc "$_bc_r_remedy")\"}"
    case "$_bc_r_status" in
        FAIL) _bc_fail=$((_bc_fail + 1)) ;;
        WARN) _bc_warn=$((_bc_warn + 1)) ;;
        N/A) _bc_na=$((_bc_na + 1)) ;;
    esac
    :
}

_bc_is_root() {
    [ -n "$1" ] && [ -f "$1/.tool-versions" ] && [ -e "$1/.claude" ]
}

_bc_walk_up() {
    _bc_w="$1"
    while [ -n "$_bc_w" ] && [ "$_bc_w" != "/" ]; do
        if _bc_is_root "$_bc_w"; then
            printf '%s\n' "$_bc_w"
            return 0
        fi
        _bc_w=$(dirname -- "$_bc_w")
    done
    return 1
}

_bc_detect_self_dir() {
    # Best-effort path of this file (works executed OR sourced in bash/zsh;
    # POSIX sh sourced has no introspection - callers fall back to $PWD).
    _bc_self=""
    if [ -n "${BASH_VERSION:-}" ]; then
        # shellcheck disable=SC3028 # bash-only introspection, guarded by BASH_VERSION
        _bc_self="${BASH_SOURCE:-$0}"
    elif [ -n "${ZSH_VERSION:-}" ]; then
        # %x prompt escape = file currently being sourced/executed (zsh only,
        # hidden from other shells inside the single-quoted eval).
        eval '_bc_self="${(%):-%x}"' 2>/dev/null
        [ -n "$_bc_self" ] || _bc_self="$0"
    else
        _bc_self="$0"
    fi
    _bc_self_dir=""
    if [ -n "$_bc_self" ] && [ -e "$_bc_self" ]; then
        _bc_self_dir=$(CDPATH='' cd -- "$(dirname -- "$_bc_self")" 2>/dev/null && pwd) || _bc_self_dir=""
    fi
}

_bc_find_root() {
    if _bc_is_root "${SAENA_BOOTSTRAP_ROOT:-}"; then
        printf '%s\n' "$SAENA_BOOTSTRAP_ROOT"
        return 0
    fi
    _bc_detect_self_dir
    for _bc_base in "$_bc_self_dir" "$PWD"; do
        [ -n "$_bc_base" ] || continue
        _bc_g=$(git -C "$_bc_base" rev-parse --show-toplevel 2>/dev/null) || _bc_g=""
        if _bc_is_root "$_bc_g"; then
            printf '%s\n' "$_bc_g"
            return 0
        fi
        if _bc_w2=$(_bc_walk_up "$_bc_base"); then
            printf '%s\n' "$_bc_w2"
            return 0
        fi
    done
    return 1
}

_bc_pin() {
    # _bc_pin <tool> -> pinned version from .tool-versions (SSOT), or empty.
    awk -v t="$1" '$1 == t { print $2; exit }' "$_bc_root/.tool-versions" 2>/dev/null
}

_bc_have() {
    command -v "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# --install actions (all idempotent; hook-allowlisted forms ONLY)
# ---------------------------------------------------------------------------

_bc_do_install() {
    _bc_sync_rc=""
    _bc_just_rc=""
    _bc_sc_rc=""
    _bc_plugin_rc=""
    if ! _bc_have uv; then
        printf 'bootstrap-claude: [install] uv not found - skipping uv-managed installs\n' >&2
    else
        printf 'bootstrap-claude: [install] uv sync --locked\n' >&2
        _bc_out=$( (cd "$_bc_root" && uv sync --locked) 2>&1 )
        _bc_sync_rc=$?
        [ "$_bc_sync_rc" -eq 0 ] || printf '%s\n' "$_bc_out" >&2

        _bc_just_pin=$(_bc_pin just)
        if [ -n "$_bc_just_pin" ]; then
            printf 'bootstrap-claude: [install] uv tool install rust-just==%s\n' "$_bc_just_pin" >&2
            _bc_out=$(uv tool install "rust-just==$_bc_just_pin" 2>&1)
            _bc_just_rc=$?
            [ "$_bc_just_rc" -eq 0 ] || printf '%s\n' "$_bc_out" >&2
        fi

        printf 'bootstrap-claude: [install] uv tool install shellcheck-py==%s (optional)\n' "$_BC_SHELLCHECK_PY_PIN" >&2
        _bc_out=$(uv tool install "shellcheck-py==$_BC_SHELLCHECK_PY_PIN" 2>&1)
        _bc_sc_rc=$?
        [ "$_bc_sc_rc" -eq 0 ] || printf '%s\n' "$_bc_out" >&2
    fi

    if [ -f "$_bc_root/.claude-plugin/marketplace.json" ] && [ -d "$_bc_root/plugins" ] && _bc_have claude; then
        printf 'bootstrap-claude: [install] claude plugin marketplace add %s\n' "$_bc_root" >&2
        _bc_out=$(claude plugin marketplace add "$_bc_root" 2>&1) || printf '%s\n' "$_bc_out" >&2
        printf 'bootstrap-claude: [install] claude plugin install saena-skill-pack@saena-rapid-7\n' >&2
        _bc_out=$(claude plugin install "saena-skill-pack@saena-rapid-7" 2>&1)
        _bc_plugin_rc=$?
        [ "$_bc_plugin_rc" -eq 0 ] || printf '%s\n' "$_bc_out" >&2
    fi
    :
}

# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

_bc_check_uv_sync() {
    if [ "$_bc_mode" = "install" ]; then
        if [ -z "$_bc_sync_rc" ]; then
            _bc_record uv-sync N/A "skipped: uv is not available" "install uv, then rerun --install"
        elif [ "$_bc_sync_rc" -eq 0 ]; then
            _bc_record uv-sync PASS "uv sync --locked completed (no-op when already synced)" ""
        else
            _bc_record uv-sync FAIL "uv sync --locked failed (rc=$_bc_sync_rc)" "run 'uv sync --locked' in the repo root and inspect its output"
        fi
        return 0
    fi
    if ! _bc_have uv; then
        _bc_record uv-sync N/A "requires uv (not found)" "install uv first, then rerun"
    elif [ ! -f "$_bc_root/uv.lock" ]; then
        _bc_record uv-sync FAIL "uv.lock missing from repo root" "restore uv.lock from git (do not re-resolve)"
    elif [ -d "$_bc_root/.venv" ]; then
        _bc_record uv-sync PASS "uv.lock present; .venv present (read-only check)" ""
    else
        _bc_record uv-sync WARN ".venv not created yet (dependencies not synced)" "run: sh scripts/bootstrap-claude.sh --install"
    fi
}

_bc_resolve_tool() {
    # _bc_resolve_tool <name> -> sets _bc_tool_bin ('' if absent) and
    # _bc_tool_where (PATH | uv-tool-bin | '').
    _bc_tool_bin=""
    _bc_tool_where=""
    if _bc_have "$1"; then
        _bc_tool_bin=$(command -v "$1")
        _bc_tool_where="PATH"
        return 0
    fi
    if _bc_have uv; then
        _bc_uv_bin_dir=$(uv tool dir --bin 2>/dev/null) || _bc_uv_bin_dir=""
        if [ -n "$_bc_uv_bin_dir" ] && [ -x "$_bc_uv_bin_dir/$1" ]; then
            _bc_tool_bin="$_bc_uv_bin_dir/$1"
            _bc_tool_where="uv-tool-bin"
        fi
    fi
}

_bc_check_just() {
    _bc_just_pin=$(_bc_pin just)
    _bc_resolve_tool just
    if [ -n "$_bc_tool_bin" ]; then
        _bc_just_ver=$("$_bc_tool_bin" --version 2>/dev/null | awk '{print $2; exit}')
        if [ "$_bc_tool_where" = "uv-tool-bin" ]; then
            # shellcheck disable=SC2016 # remedy is a literal command for the user; $HOME must NOT expand here
            _bc_record just WARN "just $_bc_just_ver installed in the uv tool bin dir but not on the active PATH" 'add the uv tool bin dir to PATH: export PATH="$HOME/.local/bin:$PATH"'
        elif [ -n "$_bc_just_pin" ] && [ "$_bc_just_ver" != "$_bc_just_pin" ]; then
            _bc_record just WARN "just $_bc_just_ver on PATH; .tool-versions pins $_bc_just_pin" "run --install (uv tool install rust-just==$_bc_just_pin)"
        else
            _bc_record just PASS "just $_bc_just_ver (pin $_bc_just_pin)" ""
        fi
    elif [ "$_bc_mode" = "install" ] && [ -n "$_bc_just_rc" ]; then
        _bc_record just FAIL "uv tool install rust-just==$_bc_just_pin did not yield a usable binary (rc=$_bc_just_rc)" "run 'uv tool install rust-just==$_bc_just_pin' manually and inspect its output"
    else
        _bc_record just WARN "just not installed" "run: sh scripts/bootstrap-claude.sh --install"
    fi
}

_bc_check_shellcheck() {
    _bc_resolve_tool shellcheck
    if [ -n "$_bc_tool_bin" ]; then
        _bc_sc_ver=$("$_bc_tool_bin" --version 2>/dev/null | awk '/^version:/{print $2; exit}')
        if [ "$_bc_tool_where" = "uv-tool-bin" ]; then
            # shellcheck disable=SC2016 # remedy is a literal command for the user; $HOME must NOT expand here
            _bc_record shellcheck WARN "shellcheck $_bc_sc_ver installed in the uv tool bin dir but not on the active PATH" 'add the uv tool bin dir to PATH: export PATH="$HOME/.local/bin:$PATH"'
        else
            _bc_record shellcheck PASS "shellcheck $_bc_sc_ver (optional lint tool)" ""
        fi
    elif [ "$_bc_mode" = "install" ]; then
        _bc_record shellcheck WARN "optional shellcheck-py==$_BC_SHELLCHECK_PY_PIN not usable after install attempt" "run 'uv tool install shellcheck-py==$_BC_SHELLCHECK_PY_PIN' manually, or use: uvx --from shellcheck-py==$_BC_SHELLCHECK_PY_PIN shellcheck"
    else
        _bc_record shellcheck N/A "optional; not installed" "run --install, or one-off: uvx --from shellcheck-py==$_BC_SHELLCHECK_PY_PIN shellcheck <file>"
    fi
}

_bc_check_plugin_bundle() {
    if [ ! -f "$_bc_root/.claude-plugin/marketplace.json" ] || [ ! -d "$_bc_root/plugins" ]; then
        _bc_record plugin-bundle N/A "plugin packaging not present in this checkout (w6-09 deliverable)" "none - expected until the Wave 6 plugin unit integrates"
        return 0
    fi
    if ! _bc_have claude; then
        _bc_record plugin-bundle N/A "packaging present but claude CLI is absent - cannot manage the plugin" "install the claude CLI first, then rerun"
        return 0
    fi
    if [ "$_bc_mode" = "install" ]; then
        if [ -n "$_bc_plugin_rc" ] && [ "$_bc_plugin_rc" -eq 0 ]; then
            _bc_record plugin-bundle PASS "saena-skill-pack@saena-rapid-7 installed/updated (user scope; CLAUDE_CONFIG_DIR honored by the claude CLI)" ""
        else
            _bc_record plugin-bundle FAIL "claude plugin install failed (rc=${_bc_plugin_rc:-unknown})" "run manually: claude plugin marketplace add <repo-root> && claude plugin install saena-skill-pack@saena-rapid-7"
        fi
        return 0
    fi
    if claude plugin marketplace list 2>/dev/null | grep -q "saena-rapid-7"; then
        _bc_record plugin-bundle PASS "marketplace 'saena-rapid-7' registered (user scope)" ""
    else
        _bc_record plugin-bundle WARN "packaging present but the 'saena-rapid-7' marketplace is not registered" "run --install (claude plugin marketplace add <repo-root>; claude plugin install saena-skill-pack@saena-rapid-7)"
    fi
}

_bc_do_checks() {
    # -- git ----------------------------------------------------------------
    if _bc_have git; then
        _bc_record git PASS "$(git --version 2>/dev/null | awk 'NR==1')" ""
    else
        _bc_record git FAIL "git not found on PATH" "install git (Xcode CLT on macOS / distro package on Linux) - installer needs human approval under the install policy"
    fi

    # -- uv (+ pin comparison) ----------------------------------------------
    _bc_uv_pin=$(_bc_pin uv)
    if _bc_have uv; then
        _bc_uv_ver=$(uv --version 2>/dev/null | awk '{print $2; exit}')
        if [ -n "$_bc_uv_pin" ] && [ "$_bc_uv_ver" != "$_bc_uv_pin" ]; then
            _bc_record uv WARN "uv $_bc_uv_ver on PATH; .tool-versions pins $_bc_uv_pin" "align to the pin: uv self update $_bc_uv_pin (or mise/asdf per ADR-0022)"
        else
            _bc_record uv PASS "uv $_bc_uv_ver (pin $_bc_uv_pin)" ""
        fi
    else
        _bc_record uv FAIL "uv not found on PATH" "install uv (https://docs.astral.sh/uv/) - installer needs human approval under the install policy"
    fi

    # -- python via uv -------------------------------------------------------
    _bc_py_pin=$(_bc_pin python)
    _bc_py_mm=$(printf '%s' "$_bc_py_pin" | awk -F. 'NF >= 2 {print $1 "." $2}')
    [ -n "$_bc_py_mm" ] || _bc_py_mm="3.12"
    if ! _bc_have uv; then
        _bc_record python N/A "requires uv (not found)" "install uv first, then rerun"
    elif uv python find "$_bc_py_mm" >/dev/null 2>&1; then
        _bc_record python PASS "python $_bc_py_mm interpreter available via uv (pin $_bc_py_pin)" ""
    else
        _bc_record python FAIL "no python $_bc_py_mm interpreter available via uv" "run --install (uv sync --locked provisions the pinned interpreter)"
    fi

    # -- claude CLI ----------------------------------------------------------
    if _bc_have claude; then
        _bc_claude_ver=$(claude --version 2>/dev/null | awk 'NR==1')
        [ -n "$_bc_claude_ver" ] || _bc_claude_ver="version unknown"
        _bc_record claude-cli PASS "claude CLI $_bc_claude_ver" ""
    else
        _bc_record claude-cli FAIL "claude CLI not found on PATH" "install Claude Code (https://claude.com/claude-code) - npm/brew installers need human approval under the install policy"
    fi

    # -- managed installs ----------------------------------------------------
    _bc_check_uv_sync
    _bc_check_just
    _bc_check_shellcheck

    # -- report-only optional tools (never installed by this script) --------
    for _bc_t in gitleaks kubectl helm k3d oasdiff; do
        _bc_t_pin=$(_bc_pin "$_bc_t")
        case "$_bc_t" in
            gitleaks) _bc_ci="CI security.yml runs gitleaks $_bc_t_pin over full history" ;;
            oasdiff) _bc_ci="CI contract lanes cover it" ;;
            *) _bc_ci="k3s/deploy CI lanes cover it; local deploys are hook-denied anyway" ;;
        esac
        if _bc_have "$_bc_t"; then
            _bc_record "$_bc_t" PASS "present on PATH (pin $_bc_t_pin; optional locally)" ""
        else
            _bc_record "$_bc_t" N/A "not installed locally; no hook-allowlisted pinned install path; $_bc_ci" "optional: install $_bc_t $_bc_t_pin manually (needs human approval under the install policy)"
        fi
    done

    # -- SAENA plugin bundle -------------------------------------------------
    _bc_check_plugin_bundle

    # -- Claude Code wiring --------------------------------------------------
    if [ -f "$_bc_root/.claude/settings.json" ]; then
        _bc_record claude-settings PASS ".claude/settings.json present (W0 hook wiring)" ""
    else
        _bc_record claude-settings FAIL ".claude/settings.json missing" "restore it from git; never hand-edit (protected surface)"
    fi

    _bc_missing=""
    for _bc_h in deny-deploy-push deny-unpinned-install protect-paths audit-log secret-scan; do
        [ -f "$_bc_root/.claude/hooks/scripts/$_bc_h.sh" ] || _bc_missing="$_bc_missing $_bc_h"
    done
    if [ -z "$_bc_missing" ]; then
        _bc_record hook-scripts PASS "all 5 W0 safety hook scripts present" ""
    else
        _bc_record hook-scripts FAIL "missing hook script(s):$_bc_missing" "restore .claude/hooks/scripts/ from git - hooks are the dev-repo safety layer"
    fi

    if [ -e "$_bc_root/.claude/hooks/DISABLED" ]; then
        _bc_record hook-kill-switch WARN "DISABLED kill-switch file is PRESENT - the W0 safety hooks are bypassed" "remove .claude/hooks/DISABLED to re-arm the safety hooks"
    else
        _bc_record hook-kill-switch PASS "kill-switch absent (safety hooks armed)" ""
    fi

    if [ -d "$_bc_root/.claude/agents" ]; then
        _bc_agents_n=$(find "$_bc_root/.claude/agents" -type f -name '*.md' ! -name 'README.md' 2>/dev/null | wc -l | tr -d '[:space:]')
        if [ "$_bc_agents_n" = "$_BC_EXPECTED_AGENTS" ]; then
            _bc_record agents PASS "$_BC_EXPECTED_AGENTS agent definitions present" ""
        else
            _bc_record agents WARN "expected $_BC_EXPECTED_AGENTS agent .md files, found $_bc_agents_n" "compare .claude/agents/ against git (README documents the $_BC_EXPECTED_AGENTS roles)"
        fi
    else
        _bc_record agents FAIL ".claude/agents directory missing" "restore .claude/agents/ from git"
    fi

    if [ -f "$_bc_root/.claude/skills/manifest.json" ]; then
        _bc_record skills-manifest PASS "skill manifest present (.claude/skills/manifest.json)" ""
    else
        _bc_record skills-manifest N/A "skill manifest not yet landed in this checkout (w6-01 deliverable)" "none - expected until the Wave 6 skill units integrate"
    fi

    if [ -f "$_bc_root/tools/development/worktree.sh" ]; then
        _bc_record worktree-tool PASS "tools/development/worktree.sh present (ADR-0023 worktree tool)" ""
    else
        _bc_record worktree-tool FAIL "tools/development/worktree.sh missing" "restore tools/development/worktree.sh from git"
    fi
}

# ---------------------------------------------------------------------------
# report emission
# ---------------------------------------------------------------------------

_bc_emit() {
    if [ "$_bc_json" = "1" ]; then
        printf '{"schema_version":"saena.bootstrap-report/v1","mode":"%s","checks":[%s],"exit_code":%s}\n' \
            "$_bc_mode" "$_bc_json_checks" "$_bc_exit"
    else
        printf 'SAENA RAPID-7 bootstrap-claude - mode: %s\n' "$_bc_mode"
        [ -n "$_bc_root" ] && printf 'repo root: %s\n' "$_bc_root"
        printf '\n'
        printf '%-18s %-6s %s\n' 'CHECK' 'STATUS' 'DETAIL'
        printf '%-18s %-6s %s\n' '-----' '------' '------'
        printf '%s' "$_bc_human"
        printf '\nResult: fail=%s warn=%s n/a=%s (exit %s)\n' "$_bc_fail" "$_bc_warn" "$_bc_na" "$_bc_exit"
    fi
    :
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

_bc_main() {
    _bc_mode="check"
    _bc_json=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --check) _bc_mode="check" ;;
            --install) _bc_mode="install" ;;
            --json) _bc_json=1 ;;
            -h | --help)
                _bc_usage
                return 0
                ;;
            *)
                printf 'bootstrap-claude: unknown option: %s (try --help)\n' "$1" >&2
                return 2
                ;;
        esac
        shift
    done

    _bc_fail=0
    _bc_warn=0
    _bc_na=0
    _bc_human=""
    _bc_json_checks=""
    _bc_sync_rc=""
    _bc_just_rc=""
    _bc_sc_rc=""
    _bc_plugin_rc=""

    _bc_root=$(_bc_find_root) || _bc_root=""
    if [ -z "$_bc_root" ]; then
        _bc_record repo-root FAIL "could not locate the SAENA-RAPID-7 repo root (.tool-versions + .claude markers)" "run from within the repo, or set SAENA_BOOTSTRAP_ROOT=/path/to/repo"
        _bc_exit=1
        _bc_emit
        return 1
    fi
    _bc_record repo-root PASS "$_bc_root" ""

    if [ "$_bc_mode" = "install" ]; then
        _bc_do_install
    fi
    _bc_do_checks

    if [ "$_bc_fail" -gt 0 ]; then
        _bc_exit=1
    else
        _bc_exit=0
    fi
    _bc_emit
    return "$_bc_exit"
}

_bc_main "$@"
_bc_rc=$?

# Best-effort namespace cleanup for the sourced case (functions only;
# _bc_* variables stay defined in the caller - documented in the header).
unset -f _bc_usage _bc_jesc _bc_record _bc_is_root _bc_walk_up _bc_detect_self_dir \
    _bc_find_root _bc_pin _bc_have _bc_do_install _bc_check_uv_sync _bc_resolve_tool \
    _bc_check_just _bc_check_shellcheck _bc_check_plugin_bundle _bc_do_checks \
    _bc_emit _bc_main 2>/dev/null

# Sourced => `return` succeeds and hands control back to the caller (the
# caller's shell must never be killed). Executed => `return` fails at top
# level (message silenced) and we `exit` instead.
# shellcheck disable=SC2317
return "$_bc_rc" 2>/dev/null || exit "$_bc_rc"
