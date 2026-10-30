"""Inject a private SQL double so unit tests never touch the configured MySQL."""

import secrets

import pytest

from app.platform.auth import password_hash
from app.platform import store
from app.platform.store import ensure_schema, transaction
from database_fixture import TestConnection, create_test_schema


@pytest.fixture(autouse=True)
def isolate_platform_database(monkeypatch, tmp_path):
    path = tmp_path / "unit-test.sqlite3"
    create_test_schema(path)
    monkeypatch.setenv("PLATFORM_DATABASE_URL", "mysql://unit-test.invalid/isolated_unit_test")
    monkeypatch.setattr(store, "connect", lambda: TestConnection(path))


@pytest.fixture
def account_password():
    return secrets.token_urlsafe(24)


@pytest.fixture
def platform_accounts(isolate_platform_database, account_password):
    """Explicit database fixtures for API tests only; never used by the application."""
    with transaction() as connection:
        ensure_schema(connection)
        for role in ("operator", "reviewer", "customer"):
            salt = secrets.token_hex(16)
            connection.execute(
                "INSERT INTO platform_users VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"USR-{role.upper()}",
                    f"fixture-{role}",
                    f"临时验证-{role}",
                    role,
                    salt,
                    password_hash(account_password, salt),
                ),
            )
    return account_password
