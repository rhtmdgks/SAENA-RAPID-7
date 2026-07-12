"""`saena_engine_gateway.errors` — exception hierarchy and error_code taxonomy."""

from __future__ import annotations

import re

from saena_engine_gateway.errors import (
    AdapterDisabledError,
    AdapterNotFoundError,
    EngineGatewayError,
    EngineNotPermittedError,
    PayloadEngineMismatchError,
)

# ADR-0015 problem-detail.schema.json error_code pattern.
_ERROR_CODE_PATTERN = re.compile(r"^saena\.[a-z_]+\.[a-z_]+$")


class TestEngineNotPermittedError:
    def test_carries_engine_id_and_context(self) -> None:
        exc = EngineNotPermittedError("gemini")
        assert exc.engine_id == "gemini"
        assert exc.context == {"engine_id": "gemini"}

    def test_error_code_matches_adr0015_pattern(self) -> None:
        assert _ERROR_CODE_PATTERN.match(EngineNotPermittedError("gemini").error_code)

    def test_http_status_is_403(self) -> None:
        assert EngineNotPermittedError("gemini").http_status == 403

    def test_not_retryable(self) -> None:
        assert EngineNotPermittedError("gemini").retryable is False

    def test_message_mentions_v1_and_chatgpt_search(self) -> None:
        message = str(EngineNotPermittedError("gemini"))
        assert "not permitted in v1" in message
        assert "chatgpt-search" in message

    def test_to_dict_is_log_safe_structured(self) -> None:
        exc = EngineNotPermittedError("gemini")
        as_dict = exc.to_dict()
        assert as_dict["error_code"] == "saena.policy_denied.engine_not_permitted"
        assert as_dict["engine_id"] == "gemini"


class TestAdapterNotFoundError:
    def test_carries_engine_id(self) -> None:
        exc = AdapterNotFoundError("chatgpt-search")
        assert exc.engine_id == "chatgpt-search"

    def test_http_status_is_404(self) -> None:
        assert AdapterNotFoundError("chatgpt-search").http_status == 404

    def test_error_code_matches_adr0015_pattern(self) -> None:
        assert _ERROR_CODE_PATTERN.match(AdapterNotFoundError("chatgpt-search").error_code)


class TestAdapterDisabledError:
    def test_carries_engine_id(self) -> None:
        exc = AdapterDisabledError("chatgpt-search")
        assert exc.engine_id == "chatgpt-search"

    def test_http_status_is_403(self) -> None:
        assert AdapterDisabledError("chatgpt-search").http_status == 403

    def test_error_code_is_policy_denied_category(self) -> None:
        assert AdapterDisabledError("chatgpt-search").error_code.startswith("saena.policy_denied.")


class TestPayloadEngineMismatchError:
    def test_carries_both_engine_ids(self) -> None:
        exc = PayloadEngineMismatchError("chatgpt-search", "gemini")
        assert exc.path_engine_id == "chatgpt-search"
        assert exc.payload_engine_id == "gemini"
        assert exc.context == {
            "path_engine_id": "chatgpt-search",
            "payload_engine_id": "gemini",
        }

    def test_http_status_is_400(self) -> None:
        assert PayloadEngineMismatchError("chatgpt-search", "gemini").http_status == 400

    def test_error_code_is_validation_category(self) -> None:
        error_code = PayloadEngineMismatchError("chatgpt-search", "gemini").error_code
        assert error_code.startswith("saena.validation.")


class TestEngineGatewayErrorBaseDefaults:
    def test_base_class_defaults_to_internal_non_retryable_500(self) -> None:
        exc = EngineGatewayError("boom")
        assert exc.http_status == 500
        assert exc.retryable is False
        assert exc.context == {}

    def test_context_defensive_copy(self) -> None:
        original_context = {"k": "v"}
        exc = EngineGatewayError("boom", context=original_context)
        original_context["k"] = "mutated"
        assert exc.context == {"k": "v"}
