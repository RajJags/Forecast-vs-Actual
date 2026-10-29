from fastapi.testclient import TestClient

from app.main import app


def test_meta():
    c = TestClient(app)
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/api/meta").json()["cutoff_local"] == "09:20"
