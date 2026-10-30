"""Server-owned identities, hashed passwords and expiring sessions."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Header, HTTPException

from app.platform.store import ensure_schema, transaction


def now() -> str:
    return datetime.now(UTC).isoformat()


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 180_000).hex()


def public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["name"],
        "display_name": row["name"],
        "role": row["role"],
        "project_ids": ["PRJ-001"],
    }


def login(username: str, password: str) -> dict:
    with transaction() as connection:
        ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM platform_users WHERE username = ?", (username,)
        ).fetchone()
        # Use the same expensive derivation on unknown users to reduce timing differences.
        actual = password_hash(password, row["salt"] if row else "00" * 16)
        if not row or not hmac.compare_digest(actual, row["password_hash"]):
            raise HTTPException(
                401, detail={"code": "invalid_credentials", "message": "账号或密码不正确"}
            )
        token = secrets.token_urlsafe(40)
        expires_at = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
        connection.execute(
            "INSERT INTO platform_sessions VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), row["id"], expires_at),
        )
        return {
            "token": token,
            "user": public_user(row),
            "expires_at": expires_at,
            "execution_mode": "simulation",
        }


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, detail={"code": "session_required", "message": "请先登录"})
    token = authorization.removeprefix("Bearer ").strip()
    with transaction() as connection:
        ensure_schema(connection)
        row = connection.execute(
            "SELECT u.*, s.expires_at FROM platform_sessions s "
            "JOIN platform_users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            raise HTTPException(
                401, detail={"code": "session_expired", "message": "会话已过期，请重新登录"}
            )
        return public_user(row)


def revoke_session(authorization: str) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    with transaction() as connection:
        connection.execute(
            "DELETE FROM platform_sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
