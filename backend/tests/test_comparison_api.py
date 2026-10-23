import copy
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.comparison_routes import get_service
from app.repositories.comparison_repository import ComparisonRepository
from app.services.comparison_service import ComparisonService


def example():
    part = {
        "sample_count": 12,
        "date_count": 4,
        "models": [
            {
                "method_id": "historical_blocks",
                "release_state": "research_only",
                "coverage": 1,
                "failure_count": 0,
                "metrics": [
                    {
                        "metric_id": "expected_payout_rmse",
                        "value": 12.5,
                        "unit": "CNY",
                        "direction": "lower_is_better",
                    }
                ],
            }
        ],
        "evidence": {"calibration": [{"observed": 0.5}]},
        "cases": [
            {
                "case_id": "case1",
                "observed_payout": 100,
                "outputs": [
                    {
                        "method_id": "historical_blocks",
                        "expected_payout": 80,
                        "claim_probability": 0.4,
                        "p90_payout": None,
                        "p90_status": "not_validated",
                    }
                ],
            }
        ],
    }
    test = copy.deepcopy(part)
    test["models"][0]["metrics"][0]["value"] = 987654321
    return {
        "schema_version": "comparison-v1",
        "run_id": "run1",
        "comparison_group_id": "group1",
        "title": "研究",
        "created_at": "2026-10-24",
        "source_kind": "measured",
        "label_kind": "rule_generated",
        "run_status": "completed",
        "data_start": "2025-12-31",
        "data_end": "2026-10-23",
        "warnings": ["研究用途"],
        "protocol": {"task": "payout_risk", "secret_test_score": 987654321},
        "selection": {"frozen": False},
        "test_review": {"approved": False},
        "released_partitions": ["validation"],
        "partitions": {"validation": part, "test": test},
    }


def publish(root, bundle):
    directory = root / "runs" / "run1"
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(bundle).encode()
    (directory / "bundle.json").write_bytes(raw)
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "schema_version": "comparison-v1",
                "runs": [
                    {
                        "run_id": "run1",
                        "comparison_group_id": "group1",
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ],
            }
        )
    )


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_service] = lambda: ComparisonService(
        ComparisonRepository(tmp_path)
    )
    with TestClient(app) as client:
        yield client, tmp_path
    app.dependency_overrides.clear()


PREFIX = "/api/v1/comparisons"


def test_empty_and_unknown(client):
    http, _ = client
    response = http.get(PREFIX + "/groups")
    assert response.status_code == 200
    assert response.json()["empty_reason"] == "no_published_results"
    assert http.get(PREFIX + "/runs/missing").status_code == 404
    assert http.get(PREFIX + "/runs/bad.id").status_code == 422


def test_all_public_endpoints_and_sealed_test(client):
    http, root = client
    publish(root, example())
    paths = [
        "/groups",
        "/groups/group1/runs",
        "/runs/run1",
        "/runs/run1/metrics",
        "/runs/run1/evidence",
        "/runs/run1/cases",
        "/runs/run1/export",
    ]
    for path in paths:
        response = http.get(PREFIX + path)
        assert response.status_code == 200, response.text
        assert "987654321" not in response.text
    for suffix in ["", "/metrics", "/evidence", "/cases", "/export"]:
        response = http.get(PREFIX + "/runs/run1" + suffix, params={"partition": "test"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "partition_not_released"
    assert http.get(PREFIX + "/runs/run1/cases?case_id=unknown").status_code == 404
    assert http.get(PREFIX + "/runs/run1/evidence?view=secret").status_code == 422
    csv = http.get(PREFIX + "/runs/run1/export?format=csv")
    assert "CNY" in csv.text and "2026-10-23" in csv.text
    assert "987654321" not in csv.text


def test_test_release_requires_both_gates(client):
    http, root = client
    bundle = example()
    bundle["released_partitions"].append("test")
    publish(root, bundle)
    assert http.get(PREFIX + "/groups").status_code == 503
    bundle["selection"]["frozen"] = True
    bundle["test_review"]["approved"] = True
    publish(root, bundle)
    response = http.get(PREFIX + "/runs/run1/metrics?partition=test")
    assert response.status_code == 200
    assert "987654321" in response.text


@pytest.mark.parametrize(
    "mutation", ["hash", "nan", "probability", "p90", "identity", "date", "symlink"]
)
def test_corrupt_published_data_never_falls_back(client, mutation):
    http, root = client
    bundle = example()
    output = bundle["partitions"]["validation"]["cases"][0]["outputs"][0]
    if mutation == "nan":
        bundle["protocol"]["extra"] = float("nan")
    elif mutation == "probability":
        output["claim_probability"] = 1.2
    elif mutation == "p90":
        output["p90_payout"] = 80
    elif mutation == "identity":
        bundle["run_id"] = "other"
    elif mutation == "date":
        bundle["data_start"] = "2017-01-01"
    publish(root, bundle)
    path = root / "runs/run1/bundle.json"
    if mutation == "hash":
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "symlink":
        target = root / "copy.json"
        path.rename(target)
        path.symlink_to(target)
    response = http.get(PREFIX + "/groups")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "comparison_bundle_invalid"


def test_fixture_isolation_and_no_fake_scores(client):
    http, root = client
    bundle = example()
    bundle["source_kind"] = "schema_fixture"
    bundle["partitions"] = {"validation": {"sample_count": 0, "date_count": 0, "models": []}}
    publish(root, bundle)
    assert http.get(PREFIX + "/groups").json()["items"] == []
    app.dependency_overrides[get_service] = lambda: ComparisonService(
        ComparisonRepository(root, "schema_fixture")
    )
    assert len(http.get(PREFIX + "/groups").json()["items"]) == 1
    bundle["partitions"]["validation"] = example()["partitions"]["validation"]
    publish(root, bundle)
    assert http.get(PREFIX + "/groups").status_code == 503
