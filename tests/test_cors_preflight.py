from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_sse_cors_preflight_allows_last_event_id():
    client = TestClient(app)
    response = client.options(
        "/api/v1/research/test-research-id/events",
        headers={
            "Origin": settings.FRONTEND_URL,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "last-event-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == settings.FRONTEND_URL
    assert response.headers["access-control-allow-credentials"] == "true"

    allowed_headers = {
        header.strip().lower()
        for header in response.headers["access-control-allow-headers"].split(",")
    }
    assert "last-event-id" in allowed_headers
    assert "content-type" in allowed_headers
    assert "x-csrf-token" in allowed_headers
