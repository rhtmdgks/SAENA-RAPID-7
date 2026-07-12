"""`build_problem_detail` — RFC 9457 shaping (ADR-0015)."""

from __future__ import annotations

import re

from saena_engine_gateway.errors import EngineNotPermittedError
from saena_engine_gateway.problem_detail import build_problem_detail

# ADR-0015/problem-detail.schema.json trace_id: 32-hex W3C format.
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class TestBuildProblemDetail:
    def test_contains_all_required_rfc9457_fields(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/v1/engines/gemini/requests")
        for field in ("type", "title", "status", "error_code", "retryable", "trace_id"):
            assert field in body

    def test_status_matches_exception_http_status(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert body["status"] == 403

    def test_error_code_matches_exception(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert body["error_code"] == "saena.policy_denied.engine_not_permitted"

    def test_detail_is_the_exception_message(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert body["detail"] == str(exc)

    def test_instance_is_passed_through(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/v1/engines/gemini/requests")
        assert body["instance"] == "/v1/engines/gemini/requests"

    def test_trace_id_matches_contract_pattern(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert _TRACE_ID_PATTERN.match(body["trace_id"])

    def test_type_uri_embeds_error_code(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert body["error_code"] in body["type"]
        assert body["type"].startswith("https://schemas.the-saena.ai/errors/")

    def test_tenant_id_omitted_when_not_provided(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x")
        assert "tenant_id" not in body
        assert "run_id" not in body

    def test_tenant_id_and_run_id_included_when_provided(self) -> None:
        exc = EngineNotPermittedError("gemini")
        body = build_problem_detail(exc, instance="/x", tenant_id="acme-corp", run_id="run-0001")
        assert body["tenant_id"] == "acme-corp"
        assert body["run_id"] == "run-0001"
