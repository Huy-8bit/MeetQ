"""Credentialed CORS: the API answers only configured frontend origins, never "*"."""
import importlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _app(origins):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    return app


def test_allowed_origins_come_from_env(monkeypatch):
    main = importlib.import_module("server.service.gateway.main")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://meetq.example.com/, https://dev.meetq.example.com,*")
    assert main.cors_allowed_origins() == ["https://meetq.example.com", "https://dev.meetq.example.com"]
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
    assert main.cors_allowed_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_credentialed_preflight_echoes_only_allowed_origin():
    client = TestClient(_app(["https://meetq.example.com"]))
    headers = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "content-type"}
    ok = client.options("/api/ping", headers={"Origin": "https://meetq.example.com", **headers})
    assert ok.headers["access-control-allow-origin"] == "https://meetq.example.com"
    assert ok.headers["access-control-allow-credentials"] == "true"
    denied = client.options("/api/ping", headers={"Origin": "https://evil.com", **headers})
    assert "access-control-allow-origin" not in denied.headers
    response = client.get("/api/ping", headers={"Origin": "https://meetq.example.com"})
    assert response.headers["access-control-allow-origin"] == "https://meetq.example.com"
