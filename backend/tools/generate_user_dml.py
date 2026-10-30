"""Generate private account INSERT DML; never connect to or modify a database."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Python 3.12 is required.")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

ROLES = ("operator", "reviewer", "customer")


def build_user_dml(
    username: str, name: str, role: str, password: str, *, user_id: str | None = None
) -> str:
    from app.platform.auth import password_hash

    if role not in ROLES:
        raise ValueError("Unsupported role.")
    if len(password) < 12 or len(password) > 200:
        raise ValueError("Use 12 to 200 characters for the password.")
    identity = user_id if user_id is not None else f"USR-{uuid4().hex}"
    for value, limit in ((username, 80), (name, 200), (identity, 80)):
        if not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid user ID, username or display name.")
    salt = secrets.token_hex(16)
    fields = (identity, username, name, role, salt, password_hash(password, salt))
    values = ",".join("'" + value.replace("'", "''") + "'" for value in fields)
    return (
        "-- Private account data: do not commit or publish this file.\n"
        "-- INSERT only: duplicate IDs/usernames fail; existing users are not updated.\n"
        "SET NAMES utf8mb4;\n"
        "SET @grain_account_sql_mode=@@SESSION.sql_mode;\n"
        "SET SESSION sql_mode=CONCAT_WS(',',@@SESSION.sql_mode,'NO_BACKSLASH_ESCAPES');\n"
        "START TRANSACTION;\n"
        "INSERT INTO platform_users (id,username,name,role,salt,password_hash) VALUES\n"
        f"({values});\n"
        "COMMIT;\n"
        "SET SESSION sql_mode=@grain_account_sql_mode;\n"
    )


def write_private_dml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument(
        "--user-id", help="Use an agreed business user ID when linking existing records"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    if not secrets.compare_digest(password, getpass.getpass("Repeat password: ")):
        raise SystemExit("Passwords differ; no file written.")
    try:
        content = build_user_dml(
            args.username, args.name, args.role, password, user_id=args.user_id
        )
        write_private_dml(args.output, content)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Private DML file generated. No database connection or account creation was performed.")


if __name__ == "__main__":
    main()
