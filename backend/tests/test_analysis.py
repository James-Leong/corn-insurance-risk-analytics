"""Runtime replay must equal frozen validation outputs and refuse invalid artifacts."""

import hashlib
import json
import shutil

import numpy as np
import pandas as pd
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.analysis_routes import get_service, router
from app.domain.analysis import AnalysisRequest
from app.repositories.comparison_repository import ComparisonError, ComparisonRepository
from app.services.analysis_service import AnalysisService


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    """Build deterministic test-only artifacts; no mounted var files or network required."""
    from research.run import run

    root = tmp_path_factory.mktemp("analysis-artifacts")
    cache = root / "cache"
    cache.mkdir()
    dates = pd.bdate_range("2025-12-31", "2026-10-23").strftime("%Y-%m-%d")
    frames = {
        "market.parquet": pd.DataFrame(
            {
                "ticker": "c2701",
                "tradeDate": dates,
                "settlePrice": 2200 + 100 * np.sin(np.arange(len(dates)) / 10),
            }
        ),
        "calendar.parquet": pd.DataFrame({"calendarDate": dates, "isOpen": 1}),
        "contracts.parquet": pd.DataFrame(
            {
                "ticker": ["c2701"],
                "listDate": ["2025-12-31"],
                "lastTradeDate": ["2027-01-15"],
            }
        ),
    }
    files = {}
    for name, frame in frames.items():
        frame.to_parquet(cache / name, index=False)
        files[name] = {
            "sha256": hashlib.sha256((cache / name).read_bytes()).hexdigest(),
            "rows": len(frame),
        }
    manifest = {
        "schema_version": "market-cache-v1",
        "source": "uqer",
        "requested_start": "2025-12-31",
        "requested_end": "2026-10-23",
        "tickers": ["c2701"],
        "files": files,
        "test_fixture": "synthetic sine series; never production market evidence",
    }
    (cache / "manifest.json").write_text(json.dumps(manifest))
    run(cache, root / "comparison", "corn-2026-v1")
    return AnalysisService(cache, root / "models", root / "comparison")


def test_saved_model_replay_matches_published_validation(service):
    bundle = ComparisonRepository(service.comparison_root).get("corn-2026-v1")
    cases = bundle.partitions["validation"].cases
    for case in [cases[i] for i in (0, len(cases) // 2, len(cases) - 1)]:
        rows, _ = __import__(
            "app.repositories.market_cache", fromlist=["read_market_snapshot"]
        ).read_market_snapshot(
            service.market_root, case.contract_id, bundle.data_start, bundle.data_end
        )
        settlement = next(
            r["settlePrice"] for r in rows if str(r["tradeDate"])[:10] == case.valuation_date
        )
        ratio = min(
            (0.95, 1.0, 1.05), key=lambda r: abs(round(settlement * r, 2) - case.guarantee_price)
        )
        request = AnalysisRequest(
            ticker=case.contract_id, valuation_date=case.valuation_date, strike_ratio=ratio
        )
        report = service.estimate(request)
        for actual in report["methods"]:
            recorded = next(o for o in case.outputs if o.method_id == actual["method_id"])
            assert actual["expected_payout"] == pytest.approx(
                recorded.expected_payout, rel=1e-9, abs=1e-8
            )
            assert actual["claim_probability"] == pytest.approx(
                recorded.claim_probability, rel=1e-9
            )
        assert service.estimate(request) == report


def test_stress_terms_do_not_change_mean_model_outputs(service):
    request = AnalysisRequest(**service.options()["defaults"])
    original = service.estimate(request)
    changed = service.estimate(
        request.model_copy(update={"deductible": 20.0, "payout_cap": 1000.0})
    )
    assert changed["methods"] == original["methods"]
    assert changed["stress"][0]["net_payout"] == 1000
    assert changed["stress"][0]["budget_gap"] == 0
    zero = service.estimate(request.model_copy(update={"payout_cap": 0.0}))
    assert all(s["net_payout"] == 0 for s in zero["stress"])
    doubled = service.estimate(request.model_copy(update={"quantity": 200.0}))
    for a, b in zip(original["methods"], doubled["methods"]):
        assert b["expected_payout"] == pytest.approx(2 * a["expected_payout"])
        assert b["claim_probability"] == a["claim_probability"]


def test_tampered_model_rejected_before_deserialization(service, tmp_path):
    shutil.copytree(service.model_root, tmp_path / "models")
    path = tmp_path / "models/corn-2026-v1/glm_hurdle.joblib"
    path.write_bytes(path.read_bytes() + b"tampered")
    changed = AnalysisService(service.market_root, tmp_path / "models", service.comparison_root)
    with pytest.raises(ComparisonError, match="模型"):
        changed.options()


def test_api_bounds_and_training_date_refusal(service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    defaults = client.get("/api/v1/analysis/options").json()["defaults"]
    assert client.post("/api/v1/analysis/estimate", json=defaults).status_code == 200
    for change in (
        {"strike_ratio": 0.99},
        {"quantity": -1},
        {"shocks": [-60]},
        {"model_path": "/tmp/model"},
        {"valuation_date": "2026-02-01"},
    ):
        assert client.post("/api/v1/analysis/estimate", json=defaults | change).status_code == 422


def test_runtime_sources_do_not_import_training_or_sdk():
    root = Path(__file__).parents[1] / "app"
    for name in (
        "services/analysis_service.py",
        "repositories/model_repository.py",
        "api/analysis_routes.py",
    ):
        text = (root / name).read_text()
        assert "from research" not in text
        assert "import uqer" not in text
        assert ".fit(" not in text


def test_saved_xgboost_uses_single_worker(service):
    _, models, _, _ = service.context()
    classifier, regressor, _ = models["xgboost_hurdle"]
    assert classifier.get_params()["n_jobs"] == 1
    assert regressor.get_params()["n_jobs"] == 1


def test_tampered_market_rejected(service, tmp_path):
    shutil.copytree(service.market_root, tmp_path / "cache")
    path = tmp_path / "cache/market.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    changed = AnalysisService(tmp_path / "cache", service.model_root, service.comparison_root)
    request = AnalysisRequest(**service.options()["defaults"])
    with pytest.raises(ComparisonError, match="行情"):
        changed.estimate(request)


def test_future_prices_never_enter_runtime_model_features(service, monkeypatch):
    import app.services.analysis_service as module

    request = AnalysisRequest(**service.options()["defaults"])
    original = service.estimate(request)
    real_reader = module.read_market_snapshot

    def changed_future(*args, **kwargs):
        rows, manifest = real_reader(*args, **kwargs)
        for row in rows:
            if str(row["tradeDate"])[:10] > request.valuation_date:
                row["settlePrice"] *= 0.8
        return rows, manifest

    monkeypatch.setattr(module, "read_market_snapshot", changed_future)
    changed = service.estimate(request)
    assert changed["methods"] == original["methods"]
    assert changed["price_references"] == original["price_references"]
    assert changed["observed"] != original["observed"]
