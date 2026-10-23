"""Offline guarantees exercised with small synthetic Parquet files, never provider calls."""

import builtins
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.main import app
from app.repositories.market_cache import MarketCacheError, read_market_snapshot
from research.ingest import CachedUqer, END, START, TICKERS, acquire


def frames():
    dates = ["2026-01-05", "2026-01-06"]
    market = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "tradeDate": day,
                "settlePrice": 2200 + i,
                "turnoverVol": 100,
                "openInt": 200,
            }
            for ticker in TICKERS
            for i, day in enumerate(dates)
        ]
    )
    contracts = pd.DataFrame(
        [{"ticker": ticker, "listDate": START, "lastTradeDate": END} for ticker in TICKERS]
    )
    calendar = pd.DataFrame([{"calendarDate": day, "isOpen": 1} for day in dates])
    return market, contracts, calendar


def snapshot(root: Path):
    root.mkdir(exist_ok=True)
    market, contracts, calendar = frames()
    files = {}
    for name, frame in zip(
        ("market.parquet", "contracts.parquet", "calendar.parquet"), (market, contracts, calendar)
    ):
        frame.to_parquet(root / name, index=False)
        files[name] = {
            "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
            "rows": len(frame),
        }
    manifest = {
        "schema_version": "market-cache-v1",
        "source": "uqer",
        "requested_start": START,
        "requested_end": END,
        "tickers": list(TICKERS),
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.fixture
def prohibit_sdk(monkeypatch):
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name == "uqer" or name.startswith("uqer."):
            pytest.fail("Runtime or cached ingestion imported the SDK")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    monkeypatch.delenv("UQER_TOKEN", raising=False)


def test_http_uses_only_mounted_parquet_without_token(tmp_path, monkeypatch, prohibit_sdk):
    snapshot(tmp_path)
    monkeypatch.setenv("MARKET_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_PROVIDER", "parquet")
    monkeypatch.setenv("MARKET_TICKER", "c2701")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/market/corn")
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["provider"] == "parquet"
            assert [p["price"] for p in result["series"]] == [2200, 2201]
            assert result["data_as_of"] == "2026-01-06"
            assert client.get("/api/v1/dashboard").status_code == 200
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "damage", ["bytes", "scope", "row_count", "outside_dates", "duplicate", "nan", "calendar"]
)
def test_reader_rejects_corruption_and_wrong_scope(tmp_path, damage):
    manifest = snapshot(tmp_path)
    market = pd.read_parquet(tmp_path / "market.parquet")
    if damage == "bytes":
        (tmp_path / "market.parquet").write_bytes(b"bad file")
    elif damage == "scope":
        manifest["requested_start"] = "2017-01-01"
    elif damage == "row_count":
        manifest["files"]["market.parquet"]["rows"] += 1
    else:
        if damage == "outside_dates":
            market.loc[4, "tradeDate"] = "2025-12-30"
        elif damage == "duplicate":
            market.loc[5, "tradeDate"] = market.loc[4, "tradeDate"]
        elif damage == "nan":
            market.loc[4, "settlePrice"] = float("nan")
        elif damage == "calendar":
            market.loc[4, "tradeDate"] = "2026-01-07"
        market.to_parquet(tmp_path / "market.parquet", index=False)
        manifest["files"]["market.parquet"]["sha256"] = hashlib.sha256(
            (tmp_path / "market.parquet").read_bytes()
        ).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(MarketCacheError):
        read_market_snapshot(tmp_path, "c2701", START, END)


def test_corrupt_cache_is_503_not_mock_or_sdk(tmp_path, monkeypatch, prohibit_sdk):
    snapshot(tmp_path)
    (tmp_path / "market.parquet").write_bytes(b"broken")
    monkeypatch.setenv("MARKET_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_PROVIDER", "auto")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            for endpoint in ("/api/v1/market/corn", "/api/v1/dashboard"):
                response = client.get(endpoint)
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "market_cache_invalid"
    finally:
        get_settings.cache_clear()


def test_ingestion_reuses_all_seven_responses_without_sdk(tmp_path, monkeypatch, prohibit_sdk):
    market, contracts, calendar = frames()

    class FakeAPI:
        @staticmethod
        def FutuGet(**params):
            return contracts[contracts.ticker == params["ticker"]].copy()

        @staticmethod
        def TradeCalGet(**params):
            return calendar.copy()

        @staticmethod
        def MktFutdGet(**params):
            assert "contractObject" not in params
            assert params["beginDate"] == "20251231" and params["endDate"] == "20261023"
            return market[market.ticker == params["ticker"]].copy()

    original = CachedUqer.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not self.offline:
            self.api = FakeAPI

    monkeypatch.setattr(CachedUqer, "__init__", init)
    monkeypatch.setattr("research.ingest.time.sleep", lambda _: None)
    first = acquire(tmp_path)
    assert first["data_calls"] == 7
    second = acquire(tmp_path, offline=True)
    assert second["data_calls"] == 0
    rows, _ = read_market_snapshot(tmp_path, "c2701", START, END)
    assert len(rows) == 2


def test_response_cache_hash_failure_does_not_refetch(tmp_path, prohibit_sdk):
    client = CachedUqer(tmp_path, offline=True)
    identity = {"api": "MktFutdGet", "parameters": {"ticker": "c2701"}, "format": "uqer-cache-v1"}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    pd.DataFrame({"settlePrice": [1]}).to_parquet(tmp_path / f"{key}.parquet")
    (tmp_path / f"{key}.json").write_text(json.dumps({"request": identity, "sha256": "bad"}))
    with pytest.raises(ValueError, match="integrity"):
        client.fetch("MktFutdGet", {"ticker": "c2701"})
    assert client.calls == 0


def test_partial_runtime_cache_fails_closed(tmp_path, monkeypatch, prohibit_sdk):
    snapshot(tmp_path)
    (tmp_path / "manifest.json").unlink()
    monkeypatch.setenv("MARKET_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_PROVIDER", "auto")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/market/corn").status_code == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("missing", ["metadata", "parquet"])
def test_partial_response_cache_is_not_a_network_miss(tmp_path, prohibit_sdk, missing):
    identity = {"api": "MktFutdGet", "parameters": {"ticker": "c2701"}, "format": "uqer-cache-v1"}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if missing == "metadata":
        pd.DataFrame({"settlePrice": [1]}).to_parquet(tmp_path / f"{key}.parquet")
    else:
        (tmp_path / f"{key}.json").write_text("{}")
    client = CachedUqer(tmp_path, offline=False)
    with pytest.raises(ValueError):
        client.fetch("MktFutdGet", {"ticker": "c2701"})
    assert client.calls == 0


@pytest.mark.parametrize("invalid", ["[]", "null", "false"])
def test_manifest_json_wrong_shape_is_cache_error(tmp_path, invalid):
    snapshot(tmp_path)
    (tmp_path / "manifest.json").write_text(invalid)
    with pytest.raises(MarketCacheError):
        read_market_snapshot(tmp_path, "c2701", START, END)
