"""Synthetic fixtures verify research controls; live data never enters these tests."""

import copy
import hashlib
import json
from datetime import date, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.platform_research_routes import router
from app.core.config import get_settings
from app.platform import data, research
from app.platform.auth import require_user

OPERATOR = {"id": "user-a", "role": "operator", "project_ids": ["PRJ-001"]}
REVIEWER = {"id": "user-b", "role": "reviewer", "project_ids": ["PRJ-001"]}
CUSTOMER = {"id": "user-c", "role": "customer", "project_ids": ["PRJ-001"]}


def write_market(root, count=80, missing_close=False):
    root.mkdir(exist_ok=True)
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(count)]
    rows = [
        {
            "ticker": "c2701",
            "tradeDate": day,
            "settlePrice": 2200 + i * 2 + i % 3,
            "closePrice": 2190 + i * 2,
            "turnoverVol": 1000 + i,
            "openInt": 2000,
        }
        for i, day in enumerate(days)
    ]
    if missing_close:
        for row in rows:
            del row["closePrice"]
    files = {}
    for name, values in (
        ("market.parquet", rows),
        (
            "contracts.parquet",
            [{"ticker": "c2701", "listDate": days[0], "lastTradeDate": days[-1]}],
        ),
        ("calendar.parquet", [{"calendarDate": day, "isOpen": 1} for day in days]),
    ):
        pq.write_table(pa.Table.from_pylist(values), root / name)
        files[name] = {
            "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
            "rows": len(values),
        }
    manifest = {
        "schema_version": "market-cache-v1",
        "source": "uqer",
        "requested_start": days[0],
        "requested_end": days[-1],
        "tickers": ["c2701"],
        "files": files,
        "created_at": "2026-10-23T10:00:00Z",
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return days


@pytest.fixture
def environment(tmp_path, monkeypatch):
    market = tmp_path / "market"
    days = write_market(market)
    monkeypatch.setenv("MARKET_CACHE_DIR", str(market))
    get_settings.cache_clear()
    yield {"market": market, "days": days}
    get_settings.cache_clear()


def dataset_payload(**overrides):
    return {
        "name": "合成验收行情",
        "series_id": "market.c2701.settlePrice",
        "as_of": "2026-10-24",
        "availability_mode": "source_published",
        "project_id": "PRJ-001",
        **overrides,
    }


def create_run(environment, **overrides):
    dataset = research.save_dataset(dataset_payload(), OPERATOR)
    return research.run_experiment(
        {
            "name": "合成验收实验",
            "dataset_id": dataset["id"],
            "model_id": "moving_average",
            **overrides,
        },
        OPERATOR,
    )


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('true')",
        "value.__class__",
        "value[0]",
        "[x for x in value]",
        "lag(value,-1)",
        "lag(value,0)",
        "lag(value,True)",
        "lag(value,window=2)",
        "value**2",
    ],
)
def test_factor_interpreter_rejects_uncontrolled_or_future_code(expression):
    with pytest.raises(ValueError):
        research.evaluate_expression(expression, {"value": [1.0, 2.0, 3.0]})


def test_factor_zero_denominator_missing_and_causal_prefix():
    assert research.evaluate_expression(
        "ratio(value,lag(value,1))", {"value": [0.0, 1.0, 2.0]}
    ) == [None, None, 2.0]
    prefix = research.evaluate_expression("rolling_mean(value,2)", {"value": [1.0, 2.0, 3.0]})
    extended = research.evaluate_expression(
        "rolling_mean(value,2)", {"value": [1.0, 2.0, 3.0, 9999.0]}
    )
    assert prefix == extended[:3]
    assert data.safe_ratio(1, 0)[0] is None


def test_casde_keeps_source_revision_and_never_calls_stock_change_inventory(environment):
    stock = data.query_data({"series_id": "casde.CHN.ending_stocks"})
    assert all(row["value"] is None for row in stock["observations"])
    assert all(row["quality_flag"] == "not_provided" for row in stock["observations"])
    ratio = data.query_data({"series_id": "casde.CHN.export_share"})
    assert ratio["observations"][-1]["value"] == pytest.approx(1 / (30685 + 1))
    assert ratio["observations"][-1]["formula"] == "X/(C+X)"
    assert len({row["source_revision"] for row in ratio["observations"]}) == 4
    assert ratio["observations"][-1]["source_published_at"] == "2026-10-09"
    assert "scs.moa.gov.cn" in ratio["observations"][-1]["source_uri"]
    assert not data.query_data({"series_id": "casde.CHN.production", "as_of": "2026-10-08"})[
        "observations"
    ]


def test_unconnected_source_is_empty_and_close_is_not_settlement(environment):
    assert data.query_data({"series_id": "trade.CHN.imports"})["observations"] == []
    settle = data.query_data({"series_id": "market.c2701.settlePrice"})
    close = data.query_data({"series_id": "market.c2701.closePrice"})
    assert settle["observations"]
    assert settle["observations"][0]["value"] != close["observations"][0]["value"]
    assert settle["observations"][0]["source_published_at"] is None
    assert settle["observations"][0]["ticker"] == "c2701"


def test_catalog_missing_close_field_is_unavailable(environment):
    write_market(environment["market"], missing_close=True)
    close = next(
        item for item in data.catalog()["series"] if item["id"] == "market.c2701.closePrice"
    )
    assert close["status"] == "unavailable"
    assert close["non_null_count"] == 0


def test_platform_availability_does_not_fall_back_to_unverified_publication(environment):
    manifest_path = environment["market"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["created_at"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="首次入库"):
        data.query_data(
            {
                "series_id": "market.c2701.settlePrice",
                "as_of": "2026-02-01",
                "availability_mode": "platform_available",
            }
        )


def test_snapshot_excludes_future_and_remains_immutable_after_source_replacement(environment):
    dataset = research.save_dataset(dataset_payload(as_of="2026-02-01"), OPERATOR)
    assert dataset["observations"][-1]["date"] < "2026-02-01"
    original = copy.deepcopy(dataset)
    write_market(environment["market"], count=90)
    assert research.get_object("dataset", dataset["id"], OPERATOR) == original
    platform = data.query_data(
        {
            "series_id": "market.c2701.settlePrice",
            "as_of": "2026-02-01",
            "availability_mode": "platform_available",
        }
    )
    assert platform["observations"] == []


def test_insufficient_samples_have_no_fake_metrics(environment):
    write_market(environment["market"], count=10)
    run = create_run(environment)
    assert run["status"] == "insufficient_data"
    assert run["metrics"] == {}
    assert run["predictions"] == []


def test_runs_use_previous_data_and_label_reused_test_across_new_snapshots(environment):
    first = create_run(environment)
    assert first["status"] == "succeeded"
    assert first["validation"]["independent_test"]
    assert all(row["feature_cutoff"] < row["date"] for row in first["predictions"])
    assert first["metrics"]["model"]["sample_count"] >= 3
    next_dataset = research.save_dataset(dataset_payload(as_of="2026-10-25"), OPERATOR)
    second = research.run_experiment(
        {"name": "重复测试", "dataset_id": next_dataset["id"], "model_id": "naive_last"}, OPERATOR
    )
    assert second["validation"]["test_reused"]
    assert not second["validation"]["independent_test"]
    assert second["validation"]["previous_run_id"] == first["id"]


def test_registered_factor_model_fit_scope_and_payout_definition(environment):
    factor = research.save_factor(
        {"name": "三日均价", "operator": "rolling_mean", "window": 3}, OPERATOR
    )
    run = create_run(
        environment,
        model_id="factor_ridge",
        factor_ids=[factor["id"]],
        target="payout",
        policy_terms={"strike": 2300, "quantity": 100},
    )
    assert run["status"] == "succeeded"
    assert run["fitted_transform"]["fit_scope"] == "train_only"
    assert run["unit"] == "元"
    assert "非正式" in run["target_definition"]
    assert all(row["actual"] >= 0 for row in run["predictions"])


def test_partly_overlapping_test_window_is_never_called_independent(environment):
    first = create_run(environment)
    dataset = research.save_dataset(dataset_payload(), OPERATOR)
    repeated = research.run_experiment(
        {
            "name": "改变终点仍属于已见测试",
            "dataset_id": dataset["id"],
            "model_id": "naive_last",
            "test_end": environment["days"][-3],
        },
        OPERATOR,
    )
    assert repeated["status"] == "succeeded"
    assert repeated["validation"]["test_reused"]
    assert repeated["validation"]["previously_exposed_count"] > 0
    assert repeated["validation"]["previous_run_id"] == first["id"]


def test_test_values_cannot_change_training_transform_or_first_test_prediction(environment):
    factor = research.save_factor(
        {"name": "三日均价", "operator": "rolling_mean", "window": 3}, OPERATOR
    )
    first = create_run(environment, model_id="factor_ridge", factor_ids=[factor["id"]])
    # Replace only a later test target; the training fit and first test prediction stay fixed.
    market_path = environment["market"] / "market.parquet"
    rows = pq.read_table(market_path).to_pylist()
    rows[-1]["settlePrice"] = 9999
    pq.write_table(pa.Table.from_pylist(rows), market_path)
    manifest_path = environment["market"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["market.parquet"]["sha256"] = hashlib.sha256(
        market_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    second = create_run(environment, model_id="factor_ridge", factor_ids=[factor["id"]])
    assert second["fitted_transform"] == first["fitted_transform"]
    old_first = next(row for row in first["predictions"] if row["split"] == "test")
    new_first = next(row for row in second["predictions"] if row["split"] == "test")
    assert old_first["predicted"] == new_first["predicted"]


def test_reports_are_immutable_and_shared_only_with_authorized_project(environment):
    run = create_run(environment)
    private = research.save_report(
        {
            "name": "私有报告",
            "run_id": run["id"],
            "conclusion": "需人工复核",
            "share_scope": "private",
        },
        OPERATOR,
    )
    with pytest.raises(HTTPException) as exc:
        research.get_report(private["id"], REVIEWER)
    assert exc.value.status_code == 403
    shared = research.save_report(
        {
            "name": "共享报告",
            "run_id": run["id"],
            "conclusion": "需人工复核",
            "share_scope": "team",
        },
        OPERATOR,
    )
    assert research.get_report(shared["id"], REVIEWER)["run_snapshot"] == run
    with pytest.raises(HTTPException):
        research.get_report(shared["id"], {**REVIEWER, "project_ids": ["OTHER"]})
    create_run(environment, model_id="naive_last")
    assert research.get_report(shared["id"], OPERATOR)["run_snapshot"] == run


def trade_payload(**overrides):
    return {
        "mode": "preview",
        "source_id": "synthetic",
        "name": "仅供测试的合成贸易文件",
        "source_uri": "https://example.test/data",
        "source_published_at": "2026-10-10",
        "source_revision": "fixture-v1",
        "kind": "trade",
        "period_type": "calendar_month",
        "unit": "吨",
        "rows": [
            {
                "reporter": "CHN",
                "partner": "USA",
                "flow": "import",
                "hs_code": "1005",
                "hs_revision": "HS2022",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "value": 10,
            }
        ],
        **overrides,
    }


def test_standard_import_preview_confirm_is_immutable_and_catalog_queryable(environment):
    payload = trade_payload()
    assert research.import_data(payload, OPERATOR)["status"] == "preview"
    assert research.imported_data() == []
    confirmed = research.import_data({**payload, "mode": "confirm"}, OPERATOR)
    assert confirmed["immutable"]
    assert research.import_data({**payload, "mode": "confirm"}, OPERATOR)["id"] == confirmed["id"]
    series = confirmed["data"]["series"][0]
    assert series["verification_status"] == "unverified"
    assert any(item["id"] == series["id"] for item in data.catalog()["series"])
    result = data.query_data({"series_id": series["id"]})
    assert result["observations"][0]["value"] == 10
    assert result["observations"][0]["quality_flag"] == "manual_unverified"
    mutated = copy.deepcopy(payload)
    mutated["rows"][0]["value"] = 11
    with pytest.raises(ValueError, match="不得覆盖"):
        research.import_data({**mutated, "mode": "confirm"}, OPERATOR)
    assert research.imported_data()[0]["observations"][0]["value"] == 10


@pytest.mark.parametrize(
    "variant", ["hs_parent_child", "world_partners", "duplicate", "negative", "missing", "year"]
)
def test_trade_import_rejects_ambiguous_or_duplicate_aggregation(environment, variant):
    payload = trade_payload()
    extra = copy.deepcopy(payload["rows"][0])
    if variant == "hs_parent_child":
        extra["hs_code"] = "100590"
        payload["rows"].append(extra)
    elif variant == "world_partners":
        extra["partner"] = "WLD"
        payload["rows"].append(extra)
    elif variant == "duplicate":
        payload["rows"].append(extra)
    elif variant == "negative":
        payload["rows"][0]["value"] = -1
    elif variant == "missing":
        del payload["rows"][0]["hs_revision"]
    else:
        payload["period_type"] = "MY"
    with pytest.raises(ValueError):
        research.import_data(payload, OPERATOR)


def test_csv_supply_import_derives_matching_year_ratios_and_does_not_invent_stocks(environment):
    payload = trade_payload(
        kind="supply_demand",
        period_type="MY",
        rows=[],
        mode="confirm",
        csv_content=(
            "entity_code,metric,marketing_year,period_start,period_end,value\n"
            "USA,domestic_consumption,2025/26,2025-09-01,2026-08-31,80\n"
            "USA,exports_my,2025/26,2025-09-01,2026-08-31,20\n"
        ),
    )
    result = research.import_data(payload, OPERATOR)
    shares = [row for row in result["data"]["observations"] if row.get("formula")]
    assert [row["value"] for row in shares] == [0.8, 0.2, None]
    assert shares[-1]["quality_flag"] == "not_provided"


def test_fixture_import_is_visibly_separate_from_unverified_real_file(environment):
    payload = trade_payload(mode="confirm", is_fixture=True)
    result = research.import_data(payload, OPERATOR)
    assert result["data"]["source"]["status"] == "fixture"
    assert result["data"]["series"][0]["is_fixture"]
    queried = data.query_data({"series_id": result["data"]["series"][0]["id"]})
    assert queried["observations"][0]["quality_flag"] == "fixture"
    assert any("合成验收" in warning for warning in queried["warnings"])


def test_research_routes_enforce_role_and_strict_payload(environment):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: CUSTOMER
    with TestClient(app) as client:
        assert client.get("/api/v2/data/catalog").status_code == 403
        assert client.get("/api/v2/research/datasets").status_code == 403
        app.dependency_overrides[require_user] = lambda: OPERATOR
        response = client.post("/api/v2/research/datasets", json=dataset_payload())
        assert response.status_code == 201, response.text
        assert (
            client.get("/api/v2/research/datasets").json()["items"][0]["id"]
            == response.json()["id"]
        )
        bad = client.post(
            "/api/v2/research/factors", json={"name": "bad", "expression": "value.__class__"}
        )
        assert bad.status_code == 422
        assert (
            client.post(
                "/api/v2/data/query", json={"series_id": "market.c2701.settlePrice", "unknown": 1}
            ).status_code
            == 422
        )
