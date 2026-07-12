"""`ChatGPTSearchAdapter` — the single v1 `EngineAdapter` stub."""

from __future__ import annotations

from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.registry import EngineAdapter


class TestEngineId:
    def test_engine_id_is_chatgpt_search(self) -> None:
        adapter = ChatGPTSearchAdapter()
        assert adapter.engine_id == "chatgpt-search"


class TestCapabilities:
    def test_capabilities_are_a_nonempty_frozenset(self) -> None:
        adapter = ChatGPTSearchAdapter()
        assert isinstance(adapter.capabilities, frozenset)
        assert adapter.capabilities

    def test_capabilities_are_stable_across_instances(self) -> None:
        assert ChatGPTSearchAdapter().capabilities == ChatGPTSearchAdapter().capabilities


class TestSubmitObservationRequestIsDeterministicStub:
    def test_echoes_request_and_reports_stub_status(self) -> None:
        adapter = ChatGPTSearchAdapter()
        result = adapter.submit_observation_request({"query": "site:example.com"})
        assert result["engine_id"] == "chatgpt-search"
        assert result["status"] == "accepted_stub"
        assert result["request"] == {"query": "site:example.com"}

    def test_empty_request_is_accepted(self) -> None:
        adapter = ChatGPTSearchAdapter()
        result = adapter.submit_observation_request({})
        assert result["request"] == {}

    def test_result_is_independent_of_input_mutation(self) -> None:
        adapter = ChatGPTSearchAdapter()
        original = {"query": "x"}
        result = adapter.submit_observation_request(original)
        original["query"] = "mutated"
        assert result["request"] == {"query": "x"}


class TestStructuralProtocolConformance:
    def test_adapter_satisfies_engine_adapter_protocol(self) -> None:
        adapter = ChatGPTSearchAdapter()
        assert isinstance(adapter, EngineAdapter)
