"""Bypass corpus runner (task instructions):

"Bypass corpus: JSON/py fixture corpus mirroring tools/validation/hook-tests
style — at least 40 cases spanning every wrapper category above, both deny
AND allow (false-positive guard: benign `git commit -m "push to prod
later"` must ALLOW). Corpus runner = pytest parametrized test."

`tests/unit/hooks_runtime/corpus/manifest.json` holds 55 fixtures (32 DENY
/ 23 ALLOW) across every wrapper category named in the task instructions'
"Command normalization layer" requirement, plus a `deploy_push_bare` /
`dns_cms` sanity set and a `false_positive_allow` set. This module loads
that manifest once at collection time and parametrizes one test per
fixture, so a single failing fixture reports as one named test failure,
not a silent aggregate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hooks_runtime_factories import TENANT_ID, TRACE_ID, TS, make_budget, make_contract
from saena_hooks_runtime.hooks.pre_tool_use import PreToolUseInput, pre_tool_use
from saena_hooks_runtime.models import Decision, ReasonCode

# Computed directly (not `from conftest import corpus_dir`) — see
# `hooks_runtime_factories.py`'s module docstring for why this test
# directory avoids `from conftest import ...` entirely.
_CORPUS_MANIFEST = Path(__file__).resolve().parent / "corpus" / "manifest.json"


def _load_manifest() -> list[dict]:
    with _CORPUS_MANIFEST.open(encoding="utf-8") as f:
        return json.load(f)


_FIXTURES = _load_manifest()

# The corpus's approved_scope needs to cover every "ALLOW"-expected write
# target used across fixtures.
_APPROVED_SCOPE = ("src/**", "docs/blog/**")


def _run_fixture(fixture: dict) -> None:
    contract = make_contract(approved_scope=_APPROVED_SCOPE)
    input_ = PreToolUseInput(
        ts=TS,
        run_id=fixture["id"],
        tenant_id=TENANT_ID,
        trace_id=TRACE_ID,
        contract=contract,
        tool_name=fixture["tool_name"],
        budget=make_budget("pre_tool_use"),
        file_path=fixture.get("file_path"),
        resolved_path=fixture.get("resolved_path"),
        command=fixture.get("command"),
    )
    result = pre_tool_use(input_)

    expected_decision = Decision(fixture["expect_decision"])
    assert result.decision == expected_decision, (
        f"{fixture['id']}: expected decision {expected_decision}, got "
        f"{result.decision} (reason={result.reason_code}, detail={result.detail!r})"
    )

    expected_reason = fixture.get("expect_reason_code")
    if expected_reason is not None:
        assert result.reason_code == ReasonCode(expected_reason), (
            f"{fixture['id']}: expected reason_code {expected_reason}, got {result.reason_code}"
        )


@pytest.mark.parametrize("fixture", _FIXTURES, ids=[fx["id"] for fx in _FIXTURES])
def test_corpus_fixture(fixture: dict) -> None:
    _run_fixture(fixture)


def test_corpus_has_at_least_40_cases() -> None:
    assert len(_FIXTURES) >= 40


def test_corpus_has_both_allow_and_deny() -> None:
    decisions = {fx["expect_decision"] for fx in _FIXTURES}
    assert "ALLOW" in decisions
    assert "DENY" in decisions


def test_corpus_covers_every_named_wrapper_category() -> None:
    required_categories = {
        "sh_c_wrap",
        "env_prefix",
        "git_dash_c",
        "git_dash_cap_c",
        "symlink_target",
        "path_normalization",
        "encoded_quoted",
        "pipeline",
        "subshell_dollar",
        "subshell_paren",
        "multiline",
        "indirect_write",
    }
    present = {fx["category"] for fx in _FIXTURES}
    missing = required_categories - present
    assert not missing, f"corpus missing required wrapper categories: {missing}"


def test_corpus_ids_are_unique() -> None:
    ids = [fx["id"] for fx in _FIXTURES]
    assert len(ids) == len(set(ids))
