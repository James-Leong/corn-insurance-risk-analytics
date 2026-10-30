"""DML-only MySQL adapter; schema installation belongs to the database owner."""

from urllib.parse import unquote, urlsplit

import pymysql

from app.platform.schema import SCHEMA_VERSION


class MySQLConnection:
    dialect = "mysql"

    def __init__(self, url):
        self.in_transaction = False
        parsed = urlsplit(url)
        self.raw = pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=parsed.path.lstrip("/"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        try:
            with self.raw.cursor() as cursor:
                cursor.execute(
                    "SELECT version FROM schema_migrations WHERE version=%s", (SCHEMA_VERSION,)
                )
                if not cursor.fetchone():
                    raise RuntimeError("数据库结构版本不匹配，请执行001_schema_mysql.sql。")
        except Exception:
            self.raw.close()
            raise

    def execute(self, sql, parameters=()):
        sql = sql.replace("?", "%s")
        cursor = self.raw.cursor()
        cursor.execute(sql, parameters)
        return cursor

    def begin(self, lock):
        if self.in_transaction:
            return
        self.raw.begin()
        self.in_transaction = True
        row = self.execute(
            "SELECT name FROM platform_locks WHERE name=? FOR UPDATE", (lock,)
        ).fetchone()
        if row is None:
            raise RuntimeError("缺少事务锁记录，请执行数据库初始化脚本。")

    def commit(self):
        self.raw.commit()
        self.in_transaction = False

    def rollback(self):
        self.raw.rollback()
        self.in_transaction = False

    def close(self):
        self.raw.close()
