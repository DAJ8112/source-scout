from types import SimpleNamespace

from app.db import database_url


def test_database_url_uses_psycopg_for_standard_postgres_urls(monkeypatch):
    monkeypatch.setattr(
        "app.db.settings",
        SimpleNamespace(
            database_url="postgresql://user:p%40ss@host.example/referrals?sslmode=require"
        ),
    )

    assert database_url() == (
        "postgresql+psycopg://user:p%40ss@host.example/referrals?sslmode=require"
    )


def test_database_url_accepts_legacy_postgres_scheme(monkeypatch):
    monkeypatch.setattr(
        "app.db.settings",
        SimpleNamespace(database_url="postgres://user:secret@host.example/referrals"),
    )

    assert database_url().startswith("postgresql+psycopg://")
