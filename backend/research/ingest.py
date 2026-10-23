"""Explicit offline UQER acquisition; cached calls never initialize the SDK.

Run from backend: python -m research.ingest --output ../var/market
Credentials are read from UQER_TOKEN (or the ignored project .env) only on a cache miss.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import time

import pandas as pd
import numpy as np

START = "2025-12-31"
END = "2026-10-23"
TICKERS = ("c2609", "c2611", "c2701")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_suffix(".tmp.parquet")
    frame.to_parquet(temp, index=False, engine="pyarrow")
    os.replace(temp, path)


class CachedUqer:
    def __init__(self, root: Path, *, offline: bool = False, interval: float = 5):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.interval = max(3.0, interval)
        self.api = None
        self.last_call = 0.0
        self.calls = 0

    def fetch(self, api_name: str, params: dict) -> pd.DataFrame:
        identity = {"api": api_name, "parameters": params, "format": "uqer-cache-v1"}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        target = self.root / f"{key}.parquet"
        meta_path = self.root / f"{key}.json"
        if target.exists() != meta_path.exists():
            raise ValueError("Incomplete cached response; no automatic refetch")
        if target.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("sha256") != digest(target) or meta.get("request") != identity:
                raise ValueError("Cached response integrity mismatch; no automatic refetch")
            return pd.read_parquet(target)
        if self.offline:
            raise ValueError("Offline response missing; explicit authorized ingestion is required")
        if self.calls >= 7:
            raise ValueError("Seven data-call batch limit reached")
        # Capture SDK output: authentication failures may print sensitive account context.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if self.api is None:
                from dotenv import dotenv_values

                token = os.environ.get("UQER_TOKEN") or dotenv_values(
                    Path(__file__).resolve().parents[2] / ".env"
                ).get("UQER_TOKEN")
                if not token:
                    raise ValueError("UQER_TOKEN is required only to acquire missing cache entries")
                import uqer
                from uqer import DataAPI

                client = uqer.Client(token=token)
                if not getattr(client, "_isvalid", False):
                    raise ValueError("SDK authentication failed")
                self.api = DataAPI
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_call)))
            self.calls += 1
            self.last_call = time.monotonic()
            frame = getattr(self.api, api_name)(**params)
        if not isinstance(frame, pd.DataFrame) or frame.empty or len(frame) > 2000:
            raise ValueError("Unexpected or empty API response; batch stopped")
        if any(str(column).lower() in {"token", "password", "authorization"} for column in frame):
            raise ValueError("Unexpected sensitive response field")
        write_parquet(target, frame)
        write_json(
            meta_path,
            {
                "request": identity,
                "sha256": digest(target),
                "rows": len(frame),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return frame


def acquire(output: Path, *, offline: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    client = CachedUqer(output / "responses", offline=offline)
    contracts = pd.concat(
        [
            client.fetch(
                "FutuGet",
                {"ticker": ticker, "exchangeCD": "XDCE", "contractObject": "c", "pandas": "1"},
            )
            for ticker in TICKERS
        ],
        ignore_index=True,
    )
    if set(contracts.ticker) != set(TICKERS):
        raise ValueError("Contract metadata does not match requested tickers")
    calendar = client.fetch(
        "TradeCalGet",
        {"exchangeCD": "XDCE", "beginDate": "20251231", "endDate": "20261023", "pandas": "1"},
    )
    market = pd.concat(
        [
            client.fetch(
                "MktFutdGet",
                {
                    "ticker": ticker,
                    "exchangeCD": "XDCE",
                    "beginDate": "20251231",
                    "endDate": "20261023",
                    "pandas": "1",
                },
            )
            for ticker in TICKERS
        ],
        ignore_index=True,
    )
    for frame, key in [(market, "tradeDate"), (calendar, "calendarDate")]:
        frame[key] = pd.to_datetime(frame[key]).dt.strftime("%Y-%m-%d")
        if not frame[key].between(START, END).all():
            raise ValueError("API response outside user-authorized date scope")
    if market.duplicated(["ticker", "tradeDate"]).any():
        raise ValueError("Duplicate contract-date observations")
    required = {"ticker", "tradeDate", "settlePrice", "turnoverVol", "openInt"}
    if not required.issubset(market.columns) or set(market.ticker) != set(TICKERS):
        raise ValueError("Missing market fields or unexpected contracts")
    if not np.isfinite(market.settlePrice).all() or (market.settlePrice <= 0).any():
        raise ValueError("Missing or non-positive settlement price")
    market = market.sort_values(["ticker", "tradeDate"]).reset_index(drop=True)
    calendar = calendar.sort_values("calendarDate").reset_index(drop=True)
    if calendar.calendarDate.duplicated().any():
        raise ValueError("Duplicate calendar dates")
    open_days = set(calendar.loc[calendar.isOpen == 1, "calendarDate"])
    if not set(market.tradeDate).issubset(open_days):
        raise ValueError("Market observations not on exchange trading calendar")
    quality = {}
    for ticker, frame in market.groupby("ticker"):
        row = contracts.loc[contracts.ticker == ticker].iloc[0]
        first = max(START, str(row.listDate)[:10])
        last = min(END, str(row.lastTradeDate)[:10])
        expected = {day for day in open_days if first <= day <= last}
        if not set(frame.tradeDate).issubset(expected):
            raise ValueError("Contract observations outside listing/expiry boundary")
        quality[ticker] = {
            "rows": len(frame),
            "first_date": frame.tradeDate.min(),
            "last_date": frame.tradeDate.max(),
            "missing_open_dates": sorted(expected - set(frame.tradeDate)),
        }
    # Publication is a completed snapshot. HTTP readers validate hashes and fail closed
    # during replacement rather than silently using partially replaced files.
    files = {}
    for name, frame in [
        ("contracts.parquet", contracts),
        ("calendar.parquet", calendar),
        ("market.parquet", market),
    ]:
        write_parquet(output / name, frame)
        files[name] = {"sha256": digest(output / name), "rows": len(frame)}
    manifest = {
        "schema_version": "market-cache-v1",
        "source": "uqer",
        "requested_start": START,
        "requested_end": END,
        "tickers": list(TICKERS),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "price_field": "settlePrice",
        "price_unit": "CNY/tonne",
        "quality": quality,
        "availability_assumption": "Estimate after the daily settlement is available; historical publication timestamps unverified",
    }
    write_json(output / "manifest.json", manifest)
    return {
        "data_calls": client.calls,
        "rows": len(market),
        "quality": quality,
        "manifest": str(output / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("../var/market"))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(acquire(args.output, offline=args.offline), ensure_ascii=False, indent=2))
    except Exception as exc:
        # SDK exception messages may include credentials: expose class only.
        raise SystemExit(f"Ingestion stopped ({type(exc).__name__}); no automatic retry") from None


if __name__ == "__main__":
    main()
