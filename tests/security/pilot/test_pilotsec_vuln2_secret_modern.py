"""VULN-2 reproduction: `saena_pilot.secretguard` misses modern default-format
secrets, so they would be written verbatim into a contract/report/evidence
record.

Most impactful: OpenAI PROJECT keys `sk-proj-…` (the current default issuance
format). The module explicitly targets OpenAI `sk-` keys and even added the
`sk-live-` hyphen-infix variant, yet `sk-proj-<...>` does not match
`sk-[A-Za-z0-9]{20,}` — the `-proj-` hyphen breaks the required 20-char run, and
the literal `sk-` appears only once, so `.search` finds no match. GitHub
fine-grained PATs (`github_pat_…`) and GitLab PATs (`glpat-…`) are likewise
uncovered.

FIXED at w6-13 integration: `_SECRET_SHAPED_PATTERNS` extended with
`sk-(proj|svcacct|admin)-…`, `github_pat_…`, and `glpat-…`. This test asserts
the hardened behavior (was a strict xfail reproduction; flipped to a positive
regression guard once patched).
"""

from __future__ import annotations

import pytest
from saena_pilot.secretguard import is_secret_shaped


@pytest.mark.parametrize(
    "secret",
    [
        "sk-" + "proj-" + "T3BlbkFJ" + "abcdefghij" * 2 + "1234567890ABCD",  # OpenAI project key
        "github_"
        + "pat_"
        + "11ABCDE0000"
        + "abcdefghij"
        + "_kLmNoPqRsTuVwXyZ"
        + "0123456789ab",  # GH fine-grained PAT
        "glpat" + "-" + "abcdefghij" + "1234567890",  # GitLab PAT
    ],
)
def test_modern_secret_shapes_should_be_caught(secret: str) -> None:
    assert is_secret_shaped(secret)


def test_legacy_shapes_still_caught_regression_anchor() -> None:
    # Proves the guard DOES catch the shapes it targets — VULN-2 is strictly the
    # modern-format gap above, not a regression of existing coverage.
    for secret in (
        "sk-abcdefghijklmnopqrstuvwx",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "sk-live-abcdefghijklmnopqrstuvwx",
    ):
        assert is_secret_shaped(secret)
