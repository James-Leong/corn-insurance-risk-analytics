from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_demo_endpoints_are_wired():
    assert client.get("/api/v1/health").json()["status"] == "ok"
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["data_provider"] in {"mock", "mock_fallback", "uqer", "parquet"}
    assert client.get("/api/v1/market/corn").status_code == 200


def test_scenario_validation_and_calculation():
    response = client.post(
        "/api/v1/insurance/scenario",
        json={
            "insured_tons": 1000,
            "guarantee_price": 2600,
            "settlement_price": 2500,
            "deductible_per_ton": 10,
            "payout_cap": 50000,
        },
    )
    assert response.status_code == 200
    assert response.json()["gross_payout"] == 50000
    assert (
        client.post(
            "/api/v1/insurance/scenario",
            json={"insured_tons": -1, "guarantee_price": 1, "settlement_price": 0},
        ).status_code
        == 422
    )
