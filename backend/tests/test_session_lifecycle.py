"""Credentials are explicit; logging out revokes only the current session."""

import secrets

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.platform import auth, store
from tools.generate_user_dml import build_user_dml, write_private_dml


def test_no_implicit_accounts_even_with_legacy_password_configuration(monkeypatch):
    for role in ("OPERATOR", "REVIEWER", "CUSTOMER"):
        monkeypatch.setenv(f"PLATFORM_{role}_PASSWORD", secrets.token_urlsafe(24))
    with pytest.raises(HTTPException) as caught:
        auth.login("operator", secrets.token_urlsafe(24))
    assert caught.value.status_code == 401
    with store.transaction() as connection:
        store.ensure_schema(connection)
        assert connection.execute("SELECT COUNT(*) FROM platform_users").fetchone()[0] == 0


def test_logout_revokes_only_current_session(platform_accounts):
    password = platform_accounts
    with TestClient(app) as client:
        payload = {"username": "fixture-operator", "password": password}
        first = client.post("/api/v2/session", json=payload)
        second = client.post("/api/v2/session", json=payload)
        first_headers = {"Authorization": "Bearer " + first.json()["token"]}
        second_headers = {"Authorization": "Bearer " + second.json()["token"]}
        assert client.delete("/api/v2/session", headers=first_headers).status_code == 204
        assert client.get("/api/v2/session", headers=first_headers).status_code == 401
        assert client.get("/api/v2/session", headers=second_headers).status_code == 200


def test_account_dml_uses_explicit_user_and_database_insertion(account_password):
    username = "underwriter'o\\regional"
    sql = build_user_dml(username, "核保经办", "operator", account_password, user_id="USR-ACTUAL")
    assert account_password not in sql
    insert = sql[sql.index("INSERT INTO") : sql.index("COMMIT;")]
    with store.transaction() as connection:
        store.ensure_schema(connection)
        assert connection.execute("SELECT COUNT(*) FROM platform_users").fetchone()[0] == 0
        connection.execute(insert)
    session = auth.login(username, account_password)
    assert session["user"]["id"] == "USR-ACTUAL"
    assert session["user"]["role"] == "operator"
    # Executing an account INSERT twice must not silently overwrite the existing user.
    with pytest.raises(Exception, match="UNIQUE constraint failed"):
        with store.transaction() as connection:
            connection.execute(insert)
    assert auth.require_user("Bearer " + session["token"])["username"] == username


def test_private_dml_file_is_restricted_and_never_overwritten(tmp_path, account_password):
    path = tmp_path / "private" / "account.sql"
    sql = build_user_dml("regional.manager", "区域经办", "operator", account_password)
    write_private_dml(path, sql)
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_private_dml(path, "overwrite")
    assert path.read_text() == sql


@pytest.mark.parametrize("value", ["", "sqlite:///local.db", "mysql://localhost"])
def test_database_configuration_never_falls_back_to_a_local_file(monkeypatch, value):
    monkeypatch.setenv("PLATFORM_DATABASE_URL", value)
    with pytest.raises(RuntimeError, match="MySQL"):
        store.database_url()
