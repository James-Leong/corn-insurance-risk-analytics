"""Database-backed observations and atomic business query projections."""

import json

from app.platform.schema import projection_tables, workspace_rows


def insert_row(connection, table, row, *, preserve=False):
    if table not in projection_tables():
        raise ValueError("Unknown projection table")
    columns = list(row)
    quoted = ",".join(f"`{key}`" for key in columns)
    placeholders = ",".join("?" for _ in columns)
    verb = "INSERT IGNORE"
    if not preserve:
        verb = "INSERT"
    sql = f"{verb} INTO `{table}` ({quoted}) VALUES ({placeholders})"
    if not preserve:
        sql += " ON DUPLICATE KEY UPDATE " + ",".join(
            f"`{key}`=VALUES(`{key}`)" for key in columns if key != "id"
        )
    connection.execute(sql, tuple(row.values()))


def sync_workspace(connection, state):
    for table, row in workspace_rows(state):
        insert_row(connection, table, row)


def records(table, **filters):
    from app.platform.store import connect

    if table not in projection_tables() or any(
        key not in projection_tables()[table] and key != "id" for key in filters
    ):
        raise ValueError("Unknown data table or filter")
    conn = connect()
    try:
        where = " AND ".join(f"`{key}`=?" for key in filters)
        rows = conn.execute(
            f"SELECT payload FROM `{table}`" + (f" WHERE {where}" if where else ""),
            tuple(filters.values()),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]
    finally:
        conn.close()


def market_history(ticker):
    return sorted(records("market_daily_bars", ticker=ticker), key=lambda row: row["date"])


def market_snapshot(ticker):
    bars = market_history(ticker)
    if not bars:
        return None
    rows = [
        {
            "tradeDate": row["date"],
            "settlePrice": row["settle_price"],
            "closePrice": row["close_price"],
        }
        for row in bars
    ]
    manifest = {
        "storage": "database",
        "created_at": bars[0].get("first_seen_at"),
        "requested_start": bars[0]["date"],
        "requested_end": bars[-1]["date"],
        "files": {"market.parquet": {"sha256": bars[0]["source_version"]}},
    }
    return rows, manifest


def regional_context(project_id):
    observations = sorted(
        records("environment_daily", project_id=project_id), key=lambda row: row["observation_date"]
    )
    assessments = sorted(
        records("hazard_assessments", project_id=project_id),
        key=lambda row: row["as_of"],
        reverse=True,
    )
    events = sorted(
        records("policy_events", project_id=project_id),
        key=lambda row: row["published_at"],
        reverse=True,
    )
    return observations, assessments, events
