"""Smoke tests: prove the app boots and /health responds."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from main import app
    return TestClient(app)


def test_app_imports_and_boots(client: TestClient) -> None:
    assert client.app is not None
    assert client.app.title


def test_health_endpoint_responds(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert body["status"] == "ok"
