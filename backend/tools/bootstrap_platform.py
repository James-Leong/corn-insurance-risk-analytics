"""Export/apply the additive MySQL schema and idempotent seeded data. Python 3.12."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from uuid import UUID

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Python 3.12 is required.")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


@patch("app.platform.catalog_store.records", new=lambda *args, **kwargs: [])
def seed_rows():
    from app.platform.bootstrap import AS_OF, business_state, data_records
    from app.platform.schema import SEED_BATCH, workspace_rows
    from app.platform import business

    counter = iter(range(1, 100000))

    def stable_uuid():
        return UUID(hashlib.md5(f"{SEED_BATCH}:{next(counter)}".encode()).hexdigest())

    with (
        patch.object(business.uuid, "uuid4", stable_uuid),
        patch.object(business, "now", lambda: AS_OF),
    ):
        state = business_state()
    rows = []
    rows.append(
        (
            "platform_workspaces",
            dict(
                id=state["id"],
                revision=state["revision"],
                document=json.dumps(state, ensure_ascii=False, allow_nan=False),
            ),
        )
    )
    rows.extend(workspace_rows(state))
    rows.extend(data_records())
    # Preserve the previously executed research results without opening a temporary database.
    snapshot = json.loads((ROOT / "backend/data/platform/research_seed.json").read_text())
    if snapshot["seed_batch"] != SEED_BATCH:
        raise ValueError("Research seed batch does not match the business seed.")
    for record in snapshot["records"]:
        if record["table"] not in {"research_objects", "research_test_exposures"}:
            raise ValueError("Unsupported research seed record.")
        rows.append((record["table"], record["row"]))
    return rows


def sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def export(directory):
    from app.platform.bootstrap import AS_OF
    from app.platform.schema import SEED_BATCH, mysql_ddl

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "001_schema_mysql.sql").write_text(mysql_ddl())
    grouped = defaultdict(list)
    for table, row in seed_rows():
        if table in {"platform_users", "platform_sessions", "platform_requests"}:
            raise ValueError("Identity and session data must not be exported in public seeds.")
        grouped[table].append(row)
    statements = [
        "-- Synthetic business/reference fixtures and verified historical market snapshots.\n-- Provenance is stored per row. Re-running preserves every existing row and workspace.",
        "SET NAMES utf8mb4;",
        "SET @grain_previous_sql_mode=@@SESSION.sql_mode;",
        "SET SESSION sql_mode=CONCAT_WS(',',@@SESSION.sql_mode,'NO_BACKSLASH_ESCAPES');",
        "START TRANSACTION;",
    ]
    for table, rows in grouped.items():
        for offset in range(0, len(rows), 250):
            batch = rows[offset : offset + 250]
            columns = list(batch[0])
            key = columns[0]
            assert all(list(row) == columns for row in batch)
            values = ",\n".join(
                "(" + ",".join(sql_value(row[col]) for col in columns) + ")" for row in batch
            )
            statements.append(
                f"INSERT INTO `{table}` ("
                + ",".join(f"`{col}`" for col in columns)
                + ") VALUES\n"
                + values
                + f"\nON DUPLICATE KEY UPDATE `{key}`=`{key}`;"
            )
    statements += ["COMMIT;", "SET SESSION sql_mode=@grain_previous_sql_mode;"]
    path = directory / "002_seed_mysql.sql"
    path.write_text("\n\n".join(statements) + "\n")
    counts = {table: len(rows) for table, rows in grouped.items()}
    (directory / "seed-manifest.json").write_text(
        json.dumps(
            {
                "seed_batch": SEED_BATCH,
                "as_of": AS_OF,
                "counts": counts,
                "row_count": sum(counts.values()),
                "dml_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {"tables_with_data": len(counts), "rows": sum(counts.values()), "dml": str(path)},
            ensure_ascii=False,
        )
    )


def apply(path):
    from app.platform.store import database_url

    url = urlsplit(database_url() or "")
    if url.scheme != "mysql":
        raise SystemExit("Set PLATFORM_DATABASE_URL to the authorized MySQL database URL.")
    with tempfile.NamedTemporaryFile(mode="w", prefix="grain-db-", suffix=".cnf") as config:
        config.write(
            "[client]\nhost="
            + str(url.hostname)
            + "\nport="
            + str(url.port or 3306)
            + "\nuser="
            + unquote(url.username or "")
            + '\npassword="'
            + unquote(url.password or "").replace("\\", "\\\\").replace('"', '\\"')
            + '"\ndatabase='
            + url.path.lstrip("/")
            + "\n"
        )
        config.flush()
        with path.open() as sql:
            result = subprocess.run(
                [
                    "mysql",
                    "--defaults-extra-file=" + config.name,
                    "--default-character-set=utf8mb4",
                    "--show-warnings",
                ],
                stdin=sql,
                text=True,
                capture_output=True,
            )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise SystemExit(result.returncode)
        print("MySQL seed transaction committed. Existing rows were preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--directory", type=Path, default=ROOT / "docs/database")
    args = parser.parse_args()
    if args.export:
        export(args.directory)
    if args.apply:
        apply(args.directory / "002_seed_mysql.sql")
    if not args.export and not args.apply:
        parser.print_help()
