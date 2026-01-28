"""
Phase 1 Tests: Health check endpoint
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint_returns_200():
    """Test that /health returns HTTP 200"""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_ok_status():
    """Test that /health returns status: ok"""
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"


def test_home_endpoint_returns_200():
    """Test that / returns HTTP 200"""
    response = client.get("/")
    assert response.status_code == 200
