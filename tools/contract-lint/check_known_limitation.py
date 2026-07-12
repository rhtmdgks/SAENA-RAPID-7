"""Pinned-limitation gate: the ONLY acceptable asyncapi-cli failure is the
known 2020-12 schemaFormat gap (see README). Anything else = real doc error."""

import json
import sys

raw = sys.stdin.read()
start = raw.find("[")
diags = json.loads(raw[start:], strict=False) if start >= 0 else []
errors = [d for d in diags if d.get("severity") == 0]
known = [e for e in errors if "Unknown schema format" in e.get("message", "")]
other = [e for e in errors if e not in known]
if other:
    print("contract-lint-smoke: UNEXPECTED asyncapi errors:", file=sys.stderr)
    for e in other:
        print(f"  [{e['code']}] {e['message'][:160]}", file=sys.stderr)
    sys.exit(1)
if known:
    state = "known 2020-12 limitation only"
else:
    state = "clean parse (limitation lifted? re-evaluate README)"
print(f"contract-lint-smoke ok — {state} ({len(diags)} diagnostics)")
