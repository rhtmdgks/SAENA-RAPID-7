#!/bin/sh
# ADR-0017 global coverage ratchet: total may never fall below the committed
# baseline. Raising the baseline is a manual, in-PR edit (no bot commits —
# CLAUDE.md #10 no-push policy).
set -eu
baseline=$(cat tools/validation/coverage-baseline.txt)
total=$(uv run coverage report --format=total)
awk -v t="$total" -v b="$baseline" 'BEGIN { exit (t+0 < b+0) ? 1 : 0 }' || {
    echo "coverage ratchet: total ${total}% < baseline ${baseline}%" >&2; exit 1; }
echo "coverage ratchet ok: total ${total}% >= baseline ${baseline}%"
