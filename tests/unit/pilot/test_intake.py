"""Intake → action contract: fail-closed, no invention."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from saena_pilot.errors import (
    ContractIncompleteError,
    SecretShapedValueError,
    ValidationFailedError,
)
from saena_pilot.intake import (
    AUTO_DETECT_PENDING,
    CONTRACT_SCHEMA_VERSION,
    build_contract,
    load_intake_file,
    require_complete,
)

_BASE = {"customer_repo": "/tmp/x", "domain": "https://customer.example"}

_FULL_INTAKE = {
    "customer_id": "tenant-1",
    "allowed_write_scope": ["src/**"],
    "protected_paths": ["deploy/**"],
    "build_commands": ["make build"],
    "test_commands": ["make test"],
    "deployment_responsibility": "human",
    "data_classification": "internal",
    "observation_authorization": {"authorized": True, "owner": "Owner Kim"},
}


def _build(intake: dict | None, customer_id: str | None = None):  # type: ignore[no-untyped-def]
    return build_contract(
        customer_repo=_BASE["customer_repo"],
        domain=_BASE["domain"],
        customer_id=customer_id,
        intake_data=intake,
    )


class TestCompleteness:
    def test_no_inputs_yields_all_eight_numbered_questions(self) -> None:
        contract, questions = _build(None)
        assert len(questions) == 8
        assert [q.split(".")[0] for q in questions] == [str(i) for i in range(1, 9)]
        with pytest.raises(ContractIncompleteError) as excinfo:
            require_complete(contract, questions)
        assert excinfo.value.questions == questions

    def test_full_intake_is_complete(self) -> None:
        contract, questions = _build(dict(_FULL_INTAKE))
        assert questions == []
        require_complete(contract, questions)  # no raise
        assert contract.to_dict()["schema_version"] == CONTRACT_SCHEMA_VERSION

    @pytest.mark.parametrize("missing_key", sorted(_FULL_INTAKE))
    def test_each_missing_critical_input_is_a_question(self, missing_key: str) -> None:
        intake = {k: v for k, v in _FULL_INTAKE.items() if k != missing_key}
        contract, questions = _build(intake)
        assert len(questions) == 1
        with pytest.raises(ContractIncompleteError):
            require_complete(contract, questions)

    def test_cli_customer_id_takes_precedence(self) -> None:
        contract, _ = _build(dict(_FULL_INTAKE), customer_id="cli-tenant")
        assert contract.customer_id == "cli-tenant"

    def test_no_invention_absent_fields_stay_null(self) -> None:
        contract, _ = _build(None)
        data = contract.to_dict()
        for key in _FULL_INTAKE:
            assert data[key] is None, f"{key} must never be invented"

    def test_contract_hash_is_stable_and_canonical(self) -> None:
        a, _ = _build(dict(_FULL_INTAKE))
        b, _ = _build(dict(_FULL_INTAKE))
        assert a.contract_sha256 == b.contract_sha256


class TestConstraints:
    def test_deployment_responsibility_must_be_human(self) -> None:
        intake = {**_FULL_INTAKE, "deployment_responsibility": "agent"}
        with pytest.raises(ValidationFailedError, match="human"):
            _build(intake)

    def test_auto_detect_pending_literal_accepted(self) -> None:
        intake = {**_FULL_INTAKE, "build_commands": AUTO_DETECT_PENDING}
        contract, questions = _build(intake)
        assert questions == []
        assert contract.build_commands == AUTO_DETECT_PENDING

    def test_empty_write_scope_rejected(self) -> None:
        intake = {**_FULL_INTAKE, "allowed_write_scope": []}
        with pytest.raises(ValidationFailedError, match="allowed_write_scope"):
            _build(intake)

    def test_observation_authorization_shape_enforced(self) -> None:
        intake = {**_FULL_INTAKE, "observation_authorization": {"authorized": True}}
        with pytest.raises(ValidationFailedError, match="observation_authorization"):
            _build(intake)

    def test_observation_owner_must_be_nonempty(self) -> None:
        intake = {
            **_FULL_INTAKE,
            "observation_authorization": {"authorized": True, "owner": "  "},
        }
        with pytest.raises(ValidationFailedError):
            _build(intake)

    def test_secret_shaped_value_refused_and_not_echoed(self) -> None:
        secret = "sk-live-" + "a1B2" * 5
        intake = {**_FULL_INTAKE, "data_classification": secret}
        with pytest.raises(SecretShapedValueError) as excinfo:
            _build(intake)
        assert secret not in str(excinfo.value)


class TestIntakeFile:
    def test_unknown_keys_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "intake.json"
        path.write_text(json.dumps({**_FULL_INTAKE, "kpi_target": "x"}), encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="unknown keys.*kpi_target"):
            load_intake_file(str(path))

    def test_non_object_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "intake.json"
        path.write_text("[1,2]", encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="JSON object"):
            load_intake_file(str(path))

    def test_invalid_json_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "intake.json"
        path.write_text("{nope", encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="not valid JSON"):
            load_intake_file(str(path))

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationFailedError, match="could not read"):
            load_intake_file(str(tmp_path / "absent.json"))
