import base64
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def protected_settings(**overrides):
    values = {
        "auth_required": True,
        "app_username": "referrals",
        "app_password": "correct horse battery staple",
        "frontend_dist": None,
    }
    values.update(overrides)
    return replace(Settings(), **values)


def test_hosted_auth_protects_app_but_not_health(monkeypatch):
    monkeypatch.setattr("app.main.settings", protected_settings())
    app = create_app()

    with TestClient(app) as client:
        health = client.get("/health")
        unauthorized = client.get("/openapi.json")
        wrong = client.get("/openapi.json", auth=("referrals", "wrong"))
        authorized = client.get(
            "/openapi.json", auth=("referrals", "correct horse battery staple")
        )

    assert health.status_code == 200
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"].startswith("Basic ")
    assert wrong.status_code == 401
    assert authorized.status_code == 200


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer token", 401),
        ("Basic not-base64", 401),
        (f"Basic {base64.b64encode(b'no-colon').decode()}", 401),
    ],
)
def test_hosted_auth_rejects_malformed_credentials(monkeypatch, header, expected):
    monkeypatch.setattr("app.main.settings", protected_settings())
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json", headers={"Authorization": header})
    assert response.status_code == expected


@pytest.mark.parametrize("missing", ["app_username", "app_password"])
def test_hosted_auth_fails_closed_when_a_credential_is_missing(monkeypatch, missing):
    monkeypatch.setattr("app.main.settings", protected_settings(**{missing: None}))
    with pytest.raises(RuntimeError, match="APP_USERNAME and APP_PASSWORD"):
        create_app()
