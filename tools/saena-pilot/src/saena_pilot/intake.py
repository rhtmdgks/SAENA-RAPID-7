"""Pilot intake → machine-readable ACTION CONTRACT.

The contract (`schema_version` "saena.pilot-contract/v1") is assembled ONLY
from explicit human-provided inputs: CLI flags plus an optional `--intake`
JSON file. Missing critical inputs become numbered questions; the pilot NEVER
invents business claims, credentials, consent, KPIs, or legal approval, and
never auto-fills a tenant id, write scope, or authorization.

Unknown intake keys are rejected outright (fail-closed, mirroring the Wave-5
unknown-key regression posture). Secret-shaped values are refused before the
contract is ever serialized.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saena_pilot.errors import ContractIncompleteError, ValidationFailedError
from saena_pilot.models import canonical_json, sha256_text
from saena_pilot.secretguard import guard_tree

CONTRACT_SCHEMA_VERSION = "saena.pilot-contract/v1"
AUTO_DETECT_PENDING = "auto-detect-pending"

#: Intake-file keys accepted, and nothing else.
_INTAKE_KEYS = frozenset(
    {
        "customer_id",
        "allowed_write_scope",
        "protected_paths",
        "build_commands",
        "test_commands",
        "deployment_responsibility",
        "data_classification",
        "observation_authorization",
    }
)


@dataclass(frozen=True, slots=True)
class ActionContract:
    """The machine-readable action contract. `None` fields are open
    questions; `complete` is True only when every critical input is present
    and constraint-valid."""

    customer_repo: str
    domain: str
    customer_id: str | None
    allowed_write_scope: tuple[str, ...] | None
    protected_paths: tuple[str, ...] | None
    build_commands: tuple[str, ...] | str | None
    test_commands: tuple[str, ...] | str | None
    deployment_responsibility: str | None
    data_classification: str | None
    observation_authorization: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        def _seq(value: tuple[str, ...] | str | None) -> Any:
            return list(value) if isinstance(value, tuple) else value

        return {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "customer_repo": self.customer_repo,
            "domain": self.domain,
            "customer_id": self.customer_id,
            "allowed_write_scope": _seq(self.allowed_write_scope),
            "protected_paths": _seq(self.protected_paths),
            "build_commands": _seq(self.build_commands),
            "test_commands": _seq(self.test_commands),
            "deployment_responsibility": self.deployment_responsibility,
            "data_classification": self.data_classification,
            "observation_authorization": (
                dict(self.observation_authorization)
                if self.observation_authorization is not None
                else None
            ),
        }

    @property
    def contract_sha256(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


def _string_tuple(value: Any, *, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationFailedError(
            f"intake key {key!r} must be a list of strings",
            context={"key": key},
        )
    return tuple(value)


def load_intake_file(path: str) -> dict[str, Any]:
    """Load and shape-check the human-supplied intake JSON file."""
    intake_path = Path(path)
    try:
        raw = intake_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationFailedError(
            f"could not read intake file {path!r}: {exc}",
            context={"path": path},
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailedError(
            f"intake file {path!r} is not valid JSON: {exc}",
            context={"path": path},
        ) from exc
    if not isinstance(data, dict):
        raise ValidationFailedError(
            f"intake file {path!r} must contain a JSON object",
            context={"path": path},
        )
    unknown = sorted(set(data) - _INTAKE_KEYS)
    if unknown:
        raise ValidationFailedError(
            f"intake file {path!r} has unknown keys (rejected fail-closed): {unknown}",
            context={"path": path, "unknown_keys": unknown},
        )
    return data


def _commands_field(data: Mapping[str, Any], key: str) -> tuple[str, ...] | str | None:
    if key not in data:
        return None
    value = data[key]
    if value == AUTO_DETECT_PENDING:
        return AUTO_DETECT_PENDING
    return _string_tuple(value, key=key)


def build_contract(
    *,
    customer_repo: str,
    domain: str,
    customer_id: str | None,
    intake_data: Mapping[str, Any] | None,
) -> tuple[ActionContract, list[str]]:
    """Assemble the contract and the numbered open-question list.

    Constraint violations on PRESENT values raise `ValidationFailedError`
    immediately (e.g. `deployment_responsibility` other than "human");
    ABSENT critical values become questions.
    """
    data: Mapping[str, Any] = intake_data or {}

    resolved_customer_id = customer_id if customer_id is not None else data.get("customer_id")
    if resolved_customer_id is not None and (
        not isinstance(resolved_customer_id, str) or not resolved_customer_id.strip()
    ):
        raise ValidationFailedError(
            "customer id must be a non-empty string",
            context={"key": "customer_id"},
        )

    allowed_write_scope = (
        _string_tuple(data["allowed_write_scope"], key="allowed_write_scope")
        if "allowed_write_scope" in data
        else None
    )
    if allowed_write_scope is not None and not allowed_write_scope:
        raise ValidationFailedError(
            "allowed_write_scope must not be an empty list — an empty write scope "
            "is expressed by not requesting implement mode",
            context={"key": "allowed_write_scope"},
        )

    protected_paths = (
        _string_tuple(data["protected_paths"], key="protected_paths")
        if "protected_paths" in data
        else None
    )

    deployment = data.get("deployment_responsibility")
    if deployment is not None and deployment != "human":
        raise ValidationFailedError(
            f"deployment_responsibility must be the literal 'human', got {deployment!r} — "
            "the pilot never assumes deployment authority",
            context={"key": "deployment_responsibility"},
        )

    classification = data.get("data_classification")
    if classification is not None and (
        not isinstance(classification, str) or not classification.strip()
    ):
        raise ValidationFailedError(
            "data_classification must be a non-empty string",
            context={"key": "data_classification"},
        )

    observation = data.get("observation_authorization")
    if observation is not None:
        valid = (
            isinstance(observation, dict)
            and set(observation) == {"authorized", "owner"}
            and isinstance(observation.get("authorized"), bool)
            and isinstance(observation.get("owner"), str)
            and bool(observation["owner"].strip())
        )
        if not valid:
            raise ValidationFailedError(
                "observation_authorization must be exactly "
                '{"authorized": <bool>, "owner": "<non-empty name>"}',
                context={"key": "observation_authorization"},
            )

    contract = ActionContract(
        customer_repo=customer_repo,
        domain=domain,
        customer_id=resolved_customer_id,
        allowed_write_scope=allowed_write_scope,
        protected_paths=protected_paths,
        build_commands=_commands_field(data, "build_commands"),
        test_commands=_commands_field(data, "test_commands"),
        deployment_responsibility=deployment,
        data_classification=classification,
        observation_authorization=observation,
    )
    guard_tree(contract.to_dict(), path="contract")
    return contract, open_questions(contract)


def open_questions(contract: ActionContract) -> list[str]:
    """Every missing critical input, as a numbered human question."""
    missing: list[str] = []
    if contract.customer_id is None:
        missing.append("What is the customer/tenant id for this pilot (--customer-id)?")
    if contract.allowed_write_scope is None:
        missing.append(
            "Which customer paths is the pilot allowed to modify "
            "(allowed_write_scope globs in the intake file)?"
        )
    if contract.protected_paths is None:
        missing.append(
            "Which customer paths are protected and must never be modified (protected_paths)?"
        )
    if contract.build_commands is None:
        missing.append(
            "What are the customer build commands (build_commands), or the explicit "
            f"literal {AUTO_DETECT_PENDING!r}?"
        )
    if contract.test_commands is None:
        missing.append(
            "What are the customer test commands (test_commands), or the explicit "
            f"literal {AUTO_DETECT_PENDING!r}?"
        )
    if contract.deployment_responsibility is None:
        missing.append(
            "Confirm deployment responsibility remains with a human "
            '(deployment_responsibility: "human").'
        )
    if contract.data_classification is None:
        missing.append("What is the data classification of this customer engagement?")
    if contract.observation_authorization is None:
        missing.append(
            "Is external observation authorized, and by whom "
            '(observation_authorization: {"authorized": true/false, "owner": "<name>"})?'
        )
    return [f"{index}. {question}" for index, question in enumerate(missing, start=1)]


def require_complete(contract: ActionContract, questions: list[str]) -> None:
    """Raise `ContractIncompleteError` (listing every open question) for the
    modes that demand a complete contract."""
    if questions:
        raise ContractIncompleteError(questions)
