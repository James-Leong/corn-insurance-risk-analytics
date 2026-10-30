"""Managed accounts remain authoritative during login and session validation."""

from contextlib import contextmanager
import secrets

from fastapi import HTTPException
import pytest

from app.platform import auth, store


@pytest.fixture
def managed_accounts(monkeypatch):
    class ManagedConnection:
        dialect = "mysql"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, *args):
            return self.connection.execute(*args)

    @contextmanager
    def transaction():
        with store.transaction() as conn:
            store.ensure_schema(conn)
            yield ManagedConnection(conn)

    monkeypatch.setattr(auth, "transaction", transaction)
    return transaction


def test_empty_managed_database_does_not_create_default_accounts(
    managed_accounts, account_password
):
    with pytest.raises(HTTPException) as caught:
        auth.login("operator", account_password)
    assert caught.value.status_code == 401
    with managed_accounts() as conn:
        assert conn.execute("SELECT COUNT(*) AS total FROM platform_users").fetchone()["total"] == 0


def test_login_and_live_role_updates_use_managed_database(managed_accounts, account_password):
    salt = secrets.token_hex(16)
    with managed_accounts() as conn:
        conn.execute(
            "INSERT INTO platform_users VALUES (?, ?, ?, ?, ?, ?)",
            (
                "USR-MANAGED",
                "underwriter",
                "核保经办",
                "operator",
                salt,
                auth.password_hash(account_password, salt),
            ),
        )
    session = auth.login("underwriter", account_password)
    assert session["user"]["name"] == "核保经办"
    assert session["user"]["role"] == "operator"
    assert "password_hash" not in session["user"] and "salt" not in session["user"]
    with managed_accounts() as conn:
        conn.execute("UPDATE platform_users SET role=? WHERE id=?", ("reviewer", "USR-MANAGED"))
    assert auth.require_user("Bearer " + session["token"])["role"] == "reviewer"


def test_deleted_account_is_not_recreated_during_authentication(managed_accounts, account_password):
    salt = secrets.token_hex(16)
    with managed_accounts() as conn:
        conn.execute(
            "INSERT INTO platform_users VALUES (?, ?, ?, ?, ?, ?)",
            (
                "USR-OPERATOR",
                "operator",
                "业务经办",
                "operator",
                salt,
                auth.password_hash(account_password, salt),
            ),
        )
    assert auth.login("operator", account_password)["user"]["id"] == "USR-OPERATOR"
    with managed_accounts() as conn:
        conn.execute("DELETE FROM platform_sessions WHERE user_id=?", ("USR-OPERATOR",))
        conn.execute("DELETE FROM platform_users WHERE id=?", ("USR-OPERATOR",))
    with pytest.raises(HTTPException):
        auth.login("operator", account_password)
    with managed_accounts() as conn:
        assert conn.execute("SELECT COUNT(*) AS total FROM platform_users").fetchone()["total"] == 0
