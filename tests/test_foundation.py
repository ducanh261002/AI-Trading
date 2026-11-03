import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def test_workflow_and_persistence(tmp_path):
    settings = Settings(database_path=tmp_path / "state.sqlite3", market_enabled=False, _env_file=None)
    for run in range(2):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/health").json()["status"] == "ok"
            assert len(client.get("/api/agents").json()) == 16
            assert client.get("/").status_code == 200
            assert client.get("/dashboard.js").status_code == 200
            assert client.get("/style.css").status_code == 200
            assert client.post("/api/orders", json={"symbol": "BTCUSDT"}).status_code == 403
            assert client.post("/api/kill-switch").json()["halted"] is True
            if run == 0:
                task = client.post("/api/diagnostics")
                assert task.status_code == 201
                task_id = task.json()["task_id"]
            tasks = client.get("/api/tasks").json()
            assert tasks[0]["id"] == task_id
            assert tasks[0]["status"] == "Completed"
            assert tasks[0]["result"]["database"] is True
            assert tasks[0]["finished_at"]
            assert any(row["task_id"] == task_id for row in client.get("/api/events").json())
            assert client.get("/api/status").json()["execution_available"] is False


def test_security_and_config(tmp_path):
    settings = Settings(database_path=tmp_path / "state.sqlite3", market_enabled=False, _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/diagnostics", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert "BINANCE_API_SECRET" not in client.get("/api/status").text
    for override in ({"mode": "live"}, {"risk_per_trade": 0.1}, {"max_leverage": 20}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **override)
    with TestClient(create_app(settings), client=("192.0.2.1", 1000)) as client:
        assert client.get("/api/health").status_code == 403
