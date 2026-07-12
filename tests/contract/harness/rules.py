"""Compatibility verdict judgment (ADR-0012 dual policy + ruling R6 vocabulary).

`judge()` is the sole place compat_class-specific breaking/non-breaking
logic lives (ADR-0012 "harness 이원 구현 금지" -- single implementation).
No contract names are hardcoded anywhere in this module: all judgment
consumes `registry.json`-sourced data (`entry.compat_class`, `entry.major`
etc.) plus the caller-supplied schema bytes / structural findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    # `tests/` has no __init__.py (not a package, tests/contract/README.md
    # layout) -- conftest.py inserts tests/contract/ onto sys.path so
    # `harness` resolves as a top-level module both at runtime and here.
    from harness.registry import RegistryEntry

Verdict = Literal["pass", "breaking", "fail"]

# Structural findings (harness.diff violation-string prefixes, see
# diff.py docstring) that constitute a breaking change for `open`
# compat_class contracts (ADR-0012 event-payload rules + ruling R5).
# "optional-added" is deliberately absent -- it is non-breaking (minor)
# and open contracts never see a violation string for it because
# structural_diff() does not flag plain optional-property additions.
OPEN_BREAKING_FINDING_PREFIXES: tuple[str, ...] = (
    "required-add",
    "required-remove",
    "type-narrow",
    "enum-change",
    "const-change",
    "pattern-changed",
    "external-ref-changed",
)


def _canonical_bytes(raw: bytes) -> bytes:
    """Canonical-JSON serialize (sort_keys, no whitespace) for closed/frozen
    byte-identity comparison (plan §2 rules.py spec).
    """
    parsed = json.loads(raw)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class JudgeResult:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)


def judge(
    entry: RegistryEntry,
    old_schema_bytes: bytes,
    new_schema_bytes: bytes,
    structural_findings: list[str],
    old_major: int,
    new_major: int,
) -> JudgeResult:
    """Return the compat verdict for one contract's N-1 comparison.

    - compat_class == "closed" or "frozen": canonical-JSON byte compare.
      ANY difference at all (including a plain optional-property
      addition) is treated as breaking:
        - closed:  pass only if new_major > old_major (a proper major
                   bump legitimizes the breaking change).
        - frozen:  fail regardless of major bump -- envelope/frozen
                   contracts require a new ADR to change at all
                   (ADR-0012 envelope-frozen policy), so even a major
                   bump does not self-legitimize the change inside this
                   harness; a human-authored ADR is the only path.
    - compat_class == "open": structural findings drive the verdict.
      Any finding whose violation string starts with one of
      OPEN_BREAKING_FINDING_PREFIXES is breaking -- pass requires
      new_major > old_major. Non-breaking findings (i.e. no breaking
      findings present -- optional-property additions produce no
      structural_diff() violation string at all) are minor-OK (pass)
      regardless of major bump.
    """
    if entry.compat_class in ("closed", "frozen"):
        old_canonical = _canonical_bytes(old_schema_bytes)
        new_canonical = _canonical_bytes(new_schema_bytes)
        if old_canonical == new_canonical:
            return JudgeResult(verdict="pass", reasons=[])

        if entry.compat_class == "frozen":
            return JudgeResult(
                verdict="fail",
                reasons=["envelope/frozen change requires a new ADR"],
            )

        # closed
        if new_major > old_major:
            return JudgeResult(
                verdict="pass",
                reasons=[f"closed contract changed with major bump {old_major}->{new_major}"],
            )
        return JudgeResult(
            verdict="breaking",
            reasons=[
                "closed contract changed (canonical bytes differ) without a major version bump"
            ],
        )

    if entry.compat_class == "open":
        breaking_findings = [
            finding for finding in structural_findings if _is_breaking_finding(finding)
        ]
        if not breaking_findings:
            return JudgeResult(verdict="pass", reasons=["no breaking structural findings"])
        if new_major > old_major:
            return JudgeResult(
                verdict="pass",
                reasons=[
                    f"open contract breaking findings accompanied by major bump "
                    f"{old_major}->{new_major}: {breaking_findings}"
                ],
            )
        return JudgeResult(
            verdict="breaking",
            reasons=[
                "open contract has breaking structural findings without a major version bump: "
                f"{breaking_findings}"
            ],
        )

    msg = f"unknown compat_class {entry.compat_class!r} for entry {entry.name!r}"
    raise ValueError(msg)


def _is_breaking_finding(finding: str) -> bool:
    """True if `finding` (a harness.diff violation string, e.g.
    "$.properties.foo: required-add 'foo'") reports one of the
    OPEN_BREAKING_FINDING_PREFIXES tokens.

    Violation strings are formatted as "<path>: <token> ...", so the
    token is matched as the text immediately following ": " rather than
    as a whole-string prefix.
    """
    marker = ": "
    idx = finding.find(marker)
    token_region = finding[idx + len(marker) :] if idx != -1 else finding
    return any(token_region.startswith(prefix) for prefix in OPEN_BREAKING_FINDING_PREFIXES)
