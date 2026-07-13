"""ExecutionError base — structured error_code/context/to_dict() shape every
saena_domain.execution exception carries."""

from __future__ import annotations

from saena_domain.execution.errors import (
    EngineDisallowedError,
    EngineNotPermittedError,
    ExecutionError,
    InvalidJobTransitionError,
)


def test_execution_error_to_dict_carries_error_code_message_and_context() -> None:
    err = ExecutionError("something went wrong", context={"foo": "bar"})
    assert err.to_dict() == {
        "error_code": "saena.execution.error",
        "message": "something went wrong",
        "foo": "bar",
    }


def test_execution_error_context_defaults_to_empty_dict() -> None:
    err = ExecutionError("plain message")
    assert err.context == {}
    assert err.to_dict() == {"error_code": "saena.execution.error", "message": "plain message"}


def test_invalid_job_transition_error_context_carries_current_and_target() -> None:
    err = InvalidJobTransitionError("pending", "succeeded")
    assert err.context == {"current": "pending", "target": "succeeded"}
    assert err.error_code == "saena.execution.invalid_transition"


def test_engine_disallowed_error_is_an_execution_error() -> None:
    err = EngineDisallowedError("gemini", "Gemini")
    assert isinstance(err, ExecutionError)
    assert isinstance(err, EngineNotPermittedError)
    assert err.to_dict()["error_code"] == "saena.execution.engine_disallowed"
    assert err.to_dict()["engine_id"] == "gemini"
    assert err.to_dict()["disallowed_name"] == "Gemini"
