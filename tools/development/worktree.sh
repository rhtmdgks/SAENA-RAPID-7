#!/bin/sh
# worktree.sh — patch-unit worktree lifecycle per ADR-0023.
# 1 write agent = 1 worktree = 1 patch unit (worktree-ownership.md CONFIRMED).
# Registry: .saena/worktrees/registry.json (gitignored). Seq issuance is
# Lead-only by convention; this tool enforces exclusive-path non-overlap.
# POSIX sh + python3 stdlib only (macOS bash 3.2 compatible, no jq).
# python3 is invoked via `uv run --no-project` (works pre-workspace-scaffold
# and satisfies the modern-python environment guard against bare python3).

set -eu

REPO_ROOT=$(git rev-parse --show-toplevel)
COMMON_DIR=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
MAIN_ROOT=$(dirname "$COMMON_DIR")
REGISTRY="$MAIN_ROOT/.saena/worktrees/registry.json"
WT_BASE="$(dirname "$MAIN_ROOT")/$(basename "$MAIN_ROOT").worktrees"

usage() {
  cat <<'EOF'
Usage:
  worktree.sh create <unit-id> --paths '<glob>' [--paths '<glob>' ...] [--owner <agent>]
  worktree.sh destroy <unit-id>
  worktree.sh list
  worktree.sh audit

unit-id format: w<wave>-<seq2>-<slug>  (e.g. w0-06-workspace)
Branch created: unit/<unit-id>   Path: <repo>.worktrees/<unit-id>/
Exclusive path globs are recorded in .saena/worktrees/registry.json;
creation is refused when globs overlap an existing unit (Integrator only may override by editing the registry).
EOF
  exit 2
}

ensure_registry() {
  mkdir -p "$(dirname "$REGISTRY")"
  [ -f "$REGISTRY" ] || printf '{"units": {}}\n' > "$REGISTRY"
}

py() { uv run --no-project --quiet python3 - "$@"; }

case "${1:-}" in
  create)
    shift
    UNIT="${1:-}"; [ -n "$UNIT" ] || usage; shift
    printf '%s' "$UNIT" | grep -Eq '^w[0-9]+-[0-9]{2}-[a-z0-9][a-z0-9-]*$' || {
      echo "ERROR: unit-id '$UNIT' violates w<wave>-<seq2>-<slug> (ADR-0023)" >&2; exit 2; }
    OWNER="unspecified"; PATHS=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --paths) shift; PATHS="$PATHS${PATHS:+|}$1" ;;
        --owner) shift; OWNER="$1" ;;
        *) usage ;;
      esac
      shift
    done
    [ -n "$PATHS" ] || { echo "ERROR: at least one --paths glob required (ownership declaration)" >&2; exit 2; }
    ensure_registry
    REG="$REGISTRY" UNIT="$UNIT" OWNER="$OWNER" PATHS="$PATHS" py <<'PYEOF'
import json, os, sys, fnmatch
reg_path = os.environ["REG"]
unit = os.environ["UNIT"]
owner = os.environ["OWNER"]
globs = os.environ["PATHS"].split("|")
reg = json.load(open(reg_path))
units = reg.setdefault("units", {})
if unit in units:
    print(f"ERROR: unit '{unit}' already registered", file=sys.stderr); sys.exit(2)

def overlap(a: str, b: str) -> bool:
    # Conservative: equal globs, prefix containment, or fnmatch either way.
    if a == b: return True
    ab, bb = a.rstrip("*"), b.rstrip("*")
    if ab.startswith(bb) or bb.startswith(ab): return True
    return fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)

for other, meta in units.items():
    for g in globs:
        for og in meta["paths"]:
            if overlap(g, og):
                print(f"ERROR: glob '{g}' overlaps '{og}' owned by unit '{other}' — Integrator assignment required", file=sys.stderr)
                sys.exit(2)
units[unit] = {"owner": owner, "paths": globs, "branch": f"unit/{unit}"}
json.dump(reg, open(reg_path, "w"), indent=2, ensure_ascii=False)
print(f"registered {unit} owner={owner} paths={globs}")
PYEOF
    mkdir -p "$WT_BASE"
    git -C "$MAIN_ROOT" worktree add "$WT_BASE/$UNIT" -b "unit/$UNIT"
    echo "worktree ready: $WT_BASE/$UNIT (branch unit/$UNIT)"
    ;;
  destroy)
    UNIT="${2:-}"; [ -n "$UNIT" ] || usage
    ensure_registry
    git -C "$MAIN_ROOT" worktree remove --force "$WT_BASE/$UNIT" 2>/dev/null || true
    REG="$REGISTRY" UNIT="$UNIT" py <<'PYEOF'
import json, os, sys
reg_path = os.environ["REG"]; unit = os.environ["UNIT"]
reg = json.load(open(reg_path))
if reg.get("units", {}).pop(unit, None) is None:
    print(f"WARN: unit '{unit}' was not in registry", file=sys.stderr)
json.dump(reg, open(reg_path, "w"), indent=2, ensure_ascii=False)
print(f"deregistered {unit}")
PYEOF
    echo "destroyed: $UNIT (branch unit/$UNIT kept for history; delete manually after merge)"
    ;;
  list)
    ensure_registry
    REG="$REGISTRY" py <<'PYEOF'
import json, os
reg = json.load(open(os.environ["REG"]))
for u, m in sorted(reg.get("units", {}).items()):
    print(f"{u}\towner={m['owner']}\tbranch={m['branch']}\tpaths={','.join(m['paths'])}")
PYEOF
    ;;
  audit)
    ensure_registry
    # Registered units without a live worktree, and live unit-worktrees not registered.
    LIVE=$(git -C "$MAIN_ROOT" worktree list --porcelain | sed -n 's/^worktree //p' | grep -F "$WT_BASE/" | sed "s|$WT_BASE/||" || true)
    LIVE="$LIVE" REG="$REGISTRY" py <<'PYEOF'
import json, os, sys
reg = json.load(open(os.environ["REG"]))
live = set(filter(None, os.environ["LIVE"].splitlines()))
registered = set(reg.get("units", {}))
stale_reg = registered - live
orphan_wt = live - registered
for u in sorted(stale_reg): print(f"STALE-REGISTRY: {u} (registered, no worktree)")
for u in sorted(orphan_wt): print(f"ORPHAN-WORKTREE: {u} (worktree exists, not registered)")
sys.exit(1 if (stale_reg or orphan_wt) else 0)
PYEOF
    ;;
  *) usage ;;
esac
