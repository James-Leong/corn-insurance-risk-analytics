"""MySQL-only application storage; schema installation belongs to its owner."""

import os
from contextlib import contextmanager
from urllib.parse import urlsplit

from app.core.config import get_settings


def database_url():
    configured = os.environ.get("PLATFORM_DATABASE_URL", get_settings().platform_database_url)
    if not configured:
        raise RuntimeError("必须配置PLATFORM_DATABASE_URL；业务平台仅使用MySQL数据库。")
    parsed = urlsplit(configured)
    if parsed.scheme != "mysql" or not parsed.hostname or not parsed.path.strip("/"):
        raise RuntimeError("PLATFORM_DATABASE_URL必须指定有效的MySQL地址和数据库名。")
    return configured


def connect():
    from app.platform.mysql_store import MySQLConnection

    return MySQLConnection(database_url())


@contextmanager
def transaction():
    connection = connect()
    try:
        connection.begin("business")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_schema(connection) -> None:
    # MySQLConnection validates the installed schema version before returning a connection.
    if getattr(connection, "dialect", None) != "mysql":
        raise RuntimeError("应用仅支持MySQL；请先由数据库所有者安装DDL。")
