"""Read-only, token-free Parquet snapshot reader. Never imports the UQER SDK."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


class MarketCacheError(ValueError):
    pass


def read_market_snapshot(root: Path, ticker: str, start: str, end: str) -> tuple[list[dict], dict]:
    try:
        if (root / "manifest.json").is_symlink():
            raise ValueError("Invalid manifest path")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be an object")
        if (
            manifest.get("schema_version") != "market-cache-v1"
            or manifest.get("source") != "uqer"
            or manifest.get("requested_start") != start
            or manifest.get("requested_end") != end
            or ticker not in manifest.get("tickers", [])
        ):
            raise ValueError("Snapshot scope mismatch")
        frames = {}
        for name in ("market.parquet", "contracts.parquet", "calendar.parquet"):
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Invalid cache path")
            raw = path.read_bytes()
            expected = manifest["files"][name]
            if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise ValueError("Snapshot checksum mismatch")
            # Read the same bytes that were hashed, avoiding replacement races.
            import pyarrow as pa

            table = pq.read_table(pa.BufferReader(raw))
            if len(table) != expected["rows"]:
                raise ValueError("Snapshot row count mismatch")
            frames[name] = table.to_pylist()
        market = frames["market.parquet"]
        contracts = {row["ticker"]: row for row in frames["contracts.parquet"]}
        if len(contracts) != len(frames["contracts.parquet"]):
            raise ValueError("Duplicate contract metadata")
        if set(contracts) != set(manifest["tickers"]) or set(
            row["ticker"] for row in market
        ) != set(contracts):
            raise ValueError("Contract identity mismatch")
        if any(
            not str(contracts[row["ticker"]]["listDate"])[:10]
            <= str(row["tradeDate"])[:10]
            <= str(contracts[row["ticker"]]["lastTradeDate"])[:10]
            for row in market
        ):
            raise ValueError("Observation outside contract listing dates")
        calendar = frames["calendar.parquet"]
        if any(not start <= str(row["calendarDate"])[:10] <= end for row in calendar):
            raise ValueError("Calendar outside allowed dates")
        if len({str(row["calendarDate"])[:10] for row in calendar}) != len(calendar):
            raise ValueError("Duplicate calendar dates")
        if any(not start <= str(row["tradeDate"])[:10] <= end for row in market):
            raise ValueError("Snapshot outside allowed dates")
        if len({(row["ticker"], row["tradeDate"]) for row in market}) != len(market):
            raise ValueError("Duplicate contract-date observations")
        rows = [row for row in market if row["ticker"] == ticker]
        rows.sort(key=lambda row: str(row["tradeDate"]))
        if len(rows) < 2 or len({row["tradeDate"] for row in rows}) != len(rows):
            raise ValueError("Insufficient or duplicate observations")
        import math

        if any(
            not math.isfinite(float(row["settlePrice"])) or float(row["settlePrice"]) <= 0
            for row in market
        ):
            raise ValueError("Invalid settlement price")
        open_dates = {
            str(row["calendarDate"])[:10]
            for row in frames["calendar.parquet"]
            if row["isOpen"] == 1
        }
        if any(str(row["tradeDate"])[:10] not in open_dates for row in market):
            raise ValueError("Observation is not on exchange calendar")
        return rows, manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MarketCacheError(
            "行情缓存缺失、损坏或不符合指定日期范围；请离线生成并挂载完整快照"
        ) from exc
