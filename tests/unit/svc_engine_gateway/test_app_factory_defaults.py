"""`create_app()` — default registry/flags factories (v1-standard setup)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from saena_engine_gateway.app import create_app


class TestCreateAppDefaults:
    def test_no_args_registers_and_enables_chatgpt_search(self) -> None:
        app = create_app()
        response = TestClient(app).get("/v1/engines")
        assert response.status_code == 200
        assert response.json() == {"engines": ["chatgpt-search"]}

    def test_no_args_preflight_passes(self) -> None:
        app = create_app()
        response = TestClient(app).get("/v1/preflight")
        assert response.status_code == 200
        assert response.json()["status"] == "PASS"
