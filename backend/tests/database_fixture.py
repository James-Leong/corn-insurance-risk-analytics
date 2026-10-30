"""Test-only SQL double. Never imported or packaged by the application."""

import re
import sqlite3

from app.platform.schema import projection_tables


class TestConnection:
    dialect = "mysql"

    def __init__(self, path):
        self.raw = sqlite3.connect(path, timeout=20, isolation_level=None)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute("PRAGMA foreign_keys = ON")
        self.raw.execute("PRAGMA busy_timeout = 20000")

    def execute(self, sql, parameters=()):
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
        if " ON DUPLICATE KEY UPDATE " in sql:
            sql = sql.replace(" ON DUPLICATE KEY UPDATE ", " ON CONFLICT(id) DO UPDATE SET ")
            sql = re.sub(r"VALUES\((`?\w+`?)\)", r"excluded.\1", sql)
        return self.raw.execute(sql, parameters)

    def begin(self, lock):
        self.raw.execute("BEGIN IMMEDIATE")

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def create_test_schema(path):
    connection = TestConnection(path)
    connection.raw.execute("PRAGMA journal_mode=WAL")
    for sql in (
        "CREATE TABLE platform_workspaces (id TEXT PRIMARY KEY, revision INTEGER, document TEXT)",
        "CREATE TABLE platform_requests (actor_id TEXT, request_id TEXT, fingerprint TEXT, response TEXT, PRIMARY KEY(actor_id,request_id))",
        "CREATE TABLE platform_users (id TEXT PRIMARY KEY, username TEXT UNIQUE, name TEXT, role TEXT, salt TEXT, password_hash TEXT)",
        "CREATE TABLE platform_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES platform_users(id), expires_at TEXT)",
        "CREATE TABLE research_objects (id TEXT UNIQUE, kind TEXT, payload TEXT, sequence_no INTEGER PRIMARY KEY AUTOINCREMENT)",
        "CREATE TABLE research_test_exposures (signature TEXT PRIMARY KEY, run_id TEXT, exposed_at TEXT)",
    ):
        connection.execute(sql)
    for table, fields in projection_tables().items():
        columns = ["`id` TEXT PRIMARY KEY"] + [f"`{key}` {kind}" for key, kind in fields.items()]
        columns += ["origin_type TEXT NOT NULL", "seed_batch TEXT", "payload TEXT NOT NULL"]
        connection.execute(f"CREATE TABLE `{table}` (" + ", ".join(columns) + ")")
    connection.close()
