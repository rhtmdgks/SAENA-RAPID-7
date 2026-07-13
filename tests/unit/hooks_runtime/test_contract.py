from __future__ import annotations

import dataclasses

from hooks_runtime_factories import make_contract
from saena_hooks_runtime.contract import compute_contract_hash, validate_contract
from saena_hooks_runtime.models import ReasonCode


def test_valid_contract_passes() -> None:
    contract = make_contract()
    assert validate_contract(contract) is None


def test_missing_contract_denied() -> None:
    assert validate_contract(None) == ReasonCode.CONTRACT_MISSING


def test_hash_mismatch_denied() -> None:
    contract = make_contract(bad_hash=True)
    assert validate_contract(contract) == ReasonCode.CONTRACT_HASH_MISMATCH


def test_engine_scope_violation_denied() -> None:
    contract = make_contract(engine_scope=("google-ai-overviews",))
    assert validate_contract(contract) == ReasonCode.ENGINE_SCOPE_VIOLATION


def test_hash_is_deterministic_regardless_of_call_order() -> None:
    contract = make_contract()
    assert compute_contract_hash(contract) == compute_contract_hash(contract)


def test_hash_changes_when_content_changes() -> None:
    contract = make_contract()
    mutated = dataclasses.replace(contract, repo_commit="b" * 40)
    assert compute_contract_hash(contract) != compute_contract_hash(mutated)


def test_hash_ignores_contract_hash_field_itself() -> None:
    contract = make_contract()
    mutated = dataclasses.replace(contract, contract_hash="deadbeef")
    assert compute_contract_hash(contract) == compute_contract_hash(mutated)
