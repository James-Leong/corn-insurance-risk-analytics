"""Database context stays scoped, time-aware and traceable during source replacement."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.decision_routes import router
from app.platform import data
from app.platform.auth import require_user
from app.platform.catalog_store import insert_row
from app.platform.schema import row_values
from app.platform.store import transaction

ACTOR = {"id": "USR-OPERATOR", "role": "operator", "project_ids": ["PRJ-001"]}


@pytest.fixture
def client():
    with transaction() as conn:
        fixtures = [
            ("data_sources", {"id": "weather", "name": "区域农业监测", "status": "available"}),
            (
                "data_series",
                {
                    "id": "weather.231200.soil_saturation",
                    "name": "绥化土壤饱和度",
                    "source_id": "weather",
                    "unit": "比例",
                    "status": "available",
                    "kind": "environment",
                },
            ),
            (
                "data_observations",
                {
                    "id": "soil-1",
                    "series_id": "weather.231200.soil_saturation",
                    "date": "2026-10-28",
                    "observation_date": "2026-10-28",
                    "value": 0.68,
                    "source_published_at": "2026-10-28T08:00:00+00:00",
                    "first_seen_at": "2026-10-29T08:00:00+00:00",
                },
            ),
            (
                "environment_daily",
                {
                    "id": "weather-1",
                    "project_id": "PRJ-001",
                    "region_code": "231200",
                    "region_name": "绥化市",
                    "observation_date": "2026-10-29",
                    "temperature_c": 4.2,
                    "rainfall_mm": 3.6,
                    "wind_speed_ms": 3.8,
                    "soil_water_content": 0.28,
                    "soil_saturation": 0.68,
                },
            ),
            (
                "hazard_assessments",
                {
                    "id": "risk-1",
                    "project_id": "PRJ-001",
                    "region_code": "231200",
                    "hazard_type": "lodging",
                    "risk_level": "medium",
                    "probability": 0.28,
                    "as_of": "2026-10-29T08:00:00+00:00",
                    "valid_until": "2026-11-05T08:00:00+00:00",
                    "horizon_days": 7,
                    "model_id": "agri-v1",
                    "model_version": "1.0",
                },
            ),
            (
                "policy_events",
                {
                    "id": "policy-1",
                    "project_id": "PRJ-001",
                    "country_code": "CHN",
                    "title": "秋收服务要点",
                    "published_at": "2026-10-29T08:00:00+00:00",
                    "source_name": "政策资料库",
                },
            ),
        ]
        for table, payload in fixtures:
            insert_row(
                conn,
                table,
                row_values(
                    table, {**payload, "origin_type": "synthetic", "seed_batch": "test-batch"}
                ),
            )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: ACTOR
    with TestClient(app) as http:
        yield http, app


def test_database_weather_risk_and_policy_are_returned_with_provenance(client):
    http, _ = client
    dashboard = http.get("/api/v2/decision/dashboard").json()
    assert dashboard["agri_risk"]["status"] == "available"
    assert dashboard["agri_risk"]["latest_observation"]["soil_saturation"] == 0.68
    assert dashboard["agri_risk"]["assessments"][0]["origin_type"] == "synthetic"
    assert dashboard["policy"]["items"][0]["source_name"] == "政策资料库"
    assert dashboard["not_claim_trigger"] is True


def test_risk_lookup_does_not_leak_future_expired_or_other_region_records(client):
    http, _ = client
    query = {
        "project_id": "PRJ-001",
        "region_code": "231200",
        "region_name": "绥化市",
        "crop": "maize",
        "as_of": "2026-10-29T08:00:00+00:00",
        "hazard_types": ["lodging"],
        "horizon_days": 7,
    }
    value = http.post("/api/v2/decision/risk-assessments", json=query).json()
    assert value["status"] == "available" and value["probability"] == 0.28
    assert value["origin_type"] == "synthetic"
    for changes in (
        {"as_of": "2026-10-28T08:00:00+00:00"},
        {"as_of": "2026-11-06T08:00:00+00:00"},
        {"region_code": "230200"},
        {"horizon_days": 30},
        {"hazard_types": ["lodging", "waterlogging"]},
    ):
        response = http.post("/api/v2/decision/risk-assessments", json={**query, **changes})
        assert response.status_code == 200
        assert response.json()["probability"] is None


def test_database_observation_respects_platform_availability_and_units(client):
    query = {"series_id": "weather.231200.soil_saturation", "as_of": "2026-10-28T23:59:59+00:00"}
    value = data.query_data(query)
    assert value["series"]["unit"] == "比例"
    assert value["observations"][0]["value"] == 0.68
    assert value["observations"][0]["origin_type"] == "synthetic"
    assert (
        data.query_data({**query, "availability_mode": "platform_available"})["observations"] == []
    )


def test_customer_cannot_query_team_database_context(client):
    http, app = client
    app.dependency_overrides[require_user] = lambda: {
        "id": "USR-CUSTOMER",
        "role": "customer",
        "project_ids": ["PRJ-001"],
    }
    assert http.get("/api/v2/decision/dashboard").status_code == 403


def test_contract_fixing_reads_database_bars_without_a_parquet_dependency(client):
    from app.platform.business import prepare_fixing, seed

    state = seed()
    with transaction() as conn:
        for index, day in enumerate(state["policies"][0]["fixing_dates"]):
            payload = {
                "id": f"bar-{day}",
                "ticker": "c2701",
                "trade_date": day,
                "date": day,
                "settle_price": 2200 + index,
                "close_price": 2195 + index,
                "source_version": "a" * 64,
                "first_seen_at": "2026-10-24T00:00:00+00:00",
                "origin_type": "synthetic",
            }
            insert_row(conn, "market_daily_bars", row_values("market_daily_bars", payload))
    result = prepare_fixing(state, {"policy_id": "POL-001"}, ACTOR)
    assert result["status"] == "pending_review"
    assert result["source"] == "database_market"
    assert result["source_version"] == "a" * 64
    assert result["source_snapshot"]["file"] == "market_daily_bars"
    assert len(result["observations"]) == 5
    assert result["observations"][0]["value"] == 2200
