"""Decision aggregation tests use synthetic markets and never fabricate risk outputs."""

import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.decision_routes import router
from app.core.config import get_settings
from app.platform import decision
from app.platform.auth import require_user
from app.platform.business import get_workspace

OPERATOR = {"id": "USR-OPERATOR", "role": "operator", "project_ids": ["PRJ-001"]}
REVIEWER = {"id": "USR-REVIEWER", "role": "reviewer", "project_ids": ["PRJ-001"]}
CUSTOMER = {"id": "USR-CUSTOMER", "role": "customer", "project_ids": ["PRJ-001"]}


def market_snapshot(root, tickers=("c2609", "c2611", "c2701")):
    root.mkdir(exist_ok=True)
    market, contracts, all_dates = [], [], set()
    for ticker in tickers:
        dates = (
            ["2026-09-10", "2026-09-11", "2026-09-14"]
            if ticker == "c2609"
            else ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-22", "2026-10-23"]
        )
        contracts.append({"ticker": ticker, "listDate": dates[0], "lastTradeDate": dates[-1]})
        for index, day in enumerate(dates):
            settle = 2200 + [0, 10, 5, 20, 15][index]
            market.append(
                {
                    "ticker": ticker,
                    "tradeDate": day,
                    "settlePrice": settle,
                    "closePrice": settle - 7,
                    "openPrice": settle - 12,
                    "highestPrice": settle + 9,
                    "lowestPrice": settle - 17,
                    "preSettlePrice": 9999,
                    "turnoverVol": None if index == 0 else 1000 + index,
                    "openInt": None if index == 0 else 2000 + index,
                }
            )
        all_dates.update(dates)
    files = {}
    for name, rows in (
        ("market.parquet", market),
        ("contracts.parquet", contracts),
        ("calendar.parquet", [{"calendarDate": day, "isOpen": 1} for day in sorted(all_dates)]),
    ):
        pq.write_table(pa.Table.from_pylist(rows), root / name)
        files[name] = {
            "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
            "rows": len(rows),
        }
    manifest = {
        "schema_version": "market-cache-v1",
        "source": "uqer",
        "tickers": list(tickers),
        "requested_start": min(all_dates),
        "requested_end": max(all_dates),
        "files": files,
        "created_at": "2026-10-24T00:00:00Z",
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    market = tmp_path / "market"
    manifest = market_snapshot(market)
    monkeypatch.setenv("MARKET_CACHE_DIR", str(market))
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: OPERATOR
    with TestClient(app) as http:
        yield http, app, market, manifest
    get_settings.cache_clear()


def test_dashboard_uses_real_field_contract_and_current_casde_forecast_column(client):
    http, _, _, manifest = client
    before = get_workspace("PRJ-001", OPERATOR)
    response = http.get("/api/v2/decision/dashboard")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["context_only"] and value["not_claim_trigger"]
    assert value["project"]["id"] == "PRJ-001"
    assert value["product"]["contract"] == "c2701"
    assert value["market"]["cards"][0]["ticker"] == "c2701"
    assert len(value["market"]["cards"]) == 3
    context = value["source_context"]
    assert context["market_version"] == manifest["files"]["market.parquet"]["sha256"]
    assert context["casde_version"] == "CASDE-No.124-20261009"
    assert context["data_as_of"] == "2026-10-23"
    supply = value["supply_demand"]
    assert supply["source_revision"] == "202610-forecast"
    assert supply["statistic_status"] == "10月预测"
    assert supply["is_forecast"]
    metrics = {row["id"]: row for row in supply["metrics"]}
    assert metrics["production"]["value"] == 30600 * 10000
    assert metrics["exports_my"]["value"] == 10000
    assert metrics["export_share"]["value"] == pytest.approx(1 / (30685 + 1))
    assert metrics["ending_stocks"]["value"] is None
    assert metrics["stocks_to_use"]["value"] is None
    assert get_workspace("PRJ-001", OPERATOR)["revision"] == before["revision"]


@pytest.mark.parametrize(
    ("weather_regions", "risk_regions"),
    [
        (["231200"], ["230200"]),
        (["230200"], ["231200"]),
        (["231200", "230200"], ["230200"]),
        (["231200"], []),
        ([], ["231200"]),
    ],
)
def test_dashboard_handles_unmatched_regional_risk_without_using_another_region(
    client, monkeypatch, weather_regions, risk_regions
):
    http, _, _, _ = client
    observations = [
        {"region_code": code, "observation_date": "2026-10-29"} for code in weather_regions
    ]
    assessments = [
        {
            "region_code": code,
            "as_of": "2026-10-29T08:00:00+00:00",
            "probability": 0.3,
            "risk_level": "medium",
            "model_id": "regional-v1",
            "model_version": "1.0",
        }
        for code in risk_regions
    ]
    monkeypatch.setattr(
        "app.platform.catalog_store.regional_context",
        lambda project_id: (observations, assessments, []),
    )
    response = http.get("/api/v2/decision/dashboard")
    assert response.status_code == 200, response.text
    dashboard = response.json()
    assert dashboard["market"]["status"] == "available"
    assert dashboard["agri_risk"]["status"] == "not_ready"
    assert dashboard["agri_risk"]["probability"] is None
    assert dashboard["agri_risk"]["risk_level"] is None
    assert dashboard["agri_risk"]["model_id"] is None


def test_futures_default_is_product_contract_with_separate_ohlc_and_settlement(client):
    http, _, _, manifest = client
    response = http.get("/api/v2/decision/futures")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "c2701"
    assert data["default_ticker"] == "c2701"
    assert data["contract_choices"][0]["ticker"] == "c2701"
    assert data["latest"]["settle_price"] == 2215
    assert data["latest"]["close_price"] == 2208
    assert data["latest"]["open_price"] == 2203
    assert data["latest"]["high_price"] == 2224
    assert data["latest"]["low_price"] == 2198
    assert data["latest"]["settle_change"] == -5
    assert data["latest"]["settle_change_ratio"] == pytest.approx(-5 / 2220)
    assert data["history"][1]["settle_change"] == 10
    assert data["history"][0]["settle_change"] is None
    assert data["history"][0]["volume"] is None
    assert data["history"][0]["open_interest"] is None
    assert data["source_version"] == manifest["files"]["market.parquet"]["sha256"]
    assert data["not_live"] and data["context_only"] and data["not_claim_trigger"]
    assert all(row["source_published_at"] is None for row in data["history"])


def test_expired_contract_is_only_returned_when_explicitly_selected(client):
    http, _, _, _ = client
    data = http.get("/api/v2/decision/futures?ticker=c2609").json()
    assert data["ticker"] == "c2609"
    assert data["as_of"] == "2026-09-14"
    assert data["default_ticker"] == "c2701"
    assert http.get("/api/v2/decision/futures?ticker=c9999").status_code == 404
    assert http.get("/api/v2/decision/futures?ticker=../market").status_code == 422


def test_missing_product_contract_never_silently_uses_old_contract(client):
    http, _, root, _ = client
    market_snapshot(root, tickers=("c2609", "c2611"))
    data = http.get("/api/v2/decision/dashboard").json()
    assert data["market"]["default_ticker"] == "c2701"
    assert data["market"]["status"] == "partial"
    assert not any(row["is_product_contract"] for row in data["market"]["cards"])
    assert http.get("/api/v2/decision/futures").status_code == 404


def test_corrupt_market_fails_closed_without_fake_prices(client):
    http, _, root, _ = client
    (root / "market.parquet").write_bytes(b"corrupt")
    data = http.get("/api/v2/decision/dashboard").json()
    assert data["market"]["status"] == "unavailable"
    assert data["market"]["cards"] == []
    assert data["source_context"]["market_version"] is None
    assert data["source_context"]["data_as_of"] is None
    assert data["supply_demand"]["status"] == "available"
    assert http.get("/api/v2/decision/futures").status_code == 503
    capability = http.get("/api/v2/decision/capabilities").json()
    assert capability["items"][0]["status"] == "partial"


def test_missing_casde_does_not_masquerade_as_forecast(client, monkeypatch):
    def broken():
        raise ValueError("source checksum mismatch")

    monkeypatch.setattr(decision, "read_casde", broken)
    data = client[0].get("/api/v2/decision/dashboard").json()
    assert data["supply_demand"]["status"] == "unavailable"
    assert data["supply_demand"]["metrics"] == []
    assert data["source_context"]["casde_version"] is None
    assert data["market"]["status"] == "available"


def risk_payload(**overrides):
    return {
        "project_id": "PRJ-001",
        "region_code": "230000",
        "region_name": "黑龙江省",
        "crop": "maize",
        "as_of": "2026-10-25T08:00:00+08:00",
        "hazard_types": ["lodging", "waterlogging"],
        "horizon_days": 7,
        **overrides,
    }


def test_risk_request_never_fabricates_model_probability_or_claim(client):
    http, _, _, _ = client
    before = get_workspace("PRJ-001", OPERATOR)
    response = http.post("/api/v2/decision/risk-assessments", json=risk_payload())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["risk_level"] is None and data["probability"] is None
    assert data["model_id"] is None and data["model_version"] is None
    assert len(data["missing_requirements"]) == 4
    assert "饱和度" in data["soil_definition_notice"]
    assert data["context_only"] and data["not_claim_trigger"]
    after = get_workspace("PRJ-001", OPERATOR)
    assert after["claims"] == before["claims"]
    assert after["policies"] == before["policies"]
    assert after["revision"] == before["revision"]


@pytest.mark.parametrize(
    "bad",
    [
        {"region_code": "XX"},
        {"crop": "soybean"},
        {"as_of": "2026-10-25T08:00:00"},
        {"hazard_types": ["lodging", "lodging"]},
        {"hazard_types": ["unsupported"]},
        {"hazard_types": []},
        {"horizon_days": 0},
        {"horizon_days": 31},
        {"horizon_days": "7"},
        {"risk_level": "low"},
    ],
)
def test_risk_contract_rejects_invalid_or_invented_inputs(client, bad):
    assert (
        client[0].post("/api/v2/decision/risk-assessments", json=risk_payload(**bad)).status_code
        == 422
    )


def test_policy_events_and_agri_coverage_explicitly_unconnected(client):
    http, _, _, _ = client
    policy = http.get("/api/v2/decision/policy-events").json()
    assert policy["items"] == []
    assert policy["status"] == "not_connected"
    assert all(source["status"] == "reference_only" for source in policy["sources"])
    assert all(source["source_uri"].startswith("https://") for source in policy["sources"])
    dashboard = http.get("/api/v2/decision/dashboard").json()
    assert dashboard["agri_risk"]["risk_level"] is None
    assert dashboard["agri_risk"]["status"] == "not_ready"
    assert dashboard["policy"]["items"] == []


@pytest.mark.parametrize("path", ["dashboard", "futures", "capabilities", "policy-events"])
def test_internal_endpoints_enforce_project_scope_and_role(client, path):
    http, app, _, _ = client
    app.dependency_overrides[require_user] = lambda: REVIEWER
    assert http.get(f"/api/v2/decision/{path}").status_code == 200
    assert http.get(f"/api/v2/decision/{path}?project_id=OTHER").status_code == 403
    app.dependency_overrides[require_user] = lambda: CUSTOMER
    assert http.get(f"/api/v2/decision/{path}").status_code == 403
    assert http.post("/api/v2/decision/risk-assessments", json=risk_payload()).status_code == 403
    app.dependency_overrides.clear()
    assert http.get(f"/api/v2/decision/{path}").status_code == 401
