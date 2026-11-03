from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app.security import password_hash


def test_hosted_login_csrf_logout_and_host(tmp_path):
    settings = Settings(database_path=tmp_path / "web.db", market_enabled=False, hosted=True,
                        public_origin="https://trading.example.com", admin_password_hash=password_hash("test-password-12345"), _env_file=None)
    with TestClient(create_app(settings), base_url="https://trading.example.com") as client:
        assert client.get("/api/portfolio").status_code == 401
        assert client.post("/auth/login", json={"password": "test-password-12345"}).status_code == 403
        headers = {"Origin": "https://trading.example.com"}
        assert client.post("/auth/login", json={"password": "wrong"}, headers=headers).status_code == 401
        login = client.post("/auth/login", json={"password": "test-password-12345"}, headers=headers)
        assert login.status_code == 200
        assert "HttpOnly" in login.headers.get_list("set-cookie")[0]
        assert "Secure" in login.headers.get_list("set-cookie")[0]
        assert client.get("/api/portfolio").status_code == 200
        assert client.post("/api/kill-switch", headers=headers).status_code == 403
        headers["X-CSRF-Token"] = client.cookies["atc_csrf"]
        assert client.post("/api/kill-switch", headers=headers).status_code == 200
        assert client.post("/api/orders", headers=headers).status_code == 403
        assert client.get("/api/portfolio", headers={"Host": "attacker.example"}).status_code == 400
        assert client.post("/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/portfolio").status_code == 401


def test_hosted_fails_closed_and_login_rate_limit(tmp_path):
    with pytest.raises(ValueError):
        Settings(hosted=True, _env_file=None)
    settings = Settings(database_path=tmp_path / "web.db", hosted=True, market_enabled=False,
                        public_origin="https://trading.example.com", admin_password_hash=password_hash("test-password-12345"), _env_file=None)
    with TestClient(create_app(settings), base_url="https://trading.example.com") as client:
        for _ in range(10):
            assert client.post("/auth/login", json={"password": "wrong"}, headers={"Origin": "https://trading.example.com"}).status_code == 401
        assert client.post("/auth/login", json={"password": "wrong"}, headers={"Origin": "https://trading.example.com"}).status_code == 429
