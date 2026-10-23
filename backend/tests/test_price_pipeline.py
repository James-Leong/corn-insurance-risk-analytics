import hashlib
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from app.services.price_service import PriceError, overview
from research.price_run import features, fit, predict, run


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    """Synthetic business-day prices only; never publish these as measured market evidence."""
    root = tmp_path_factory.mktemp("synthetic-price-experiment")
    cache = root / "market"
    cache.mkdir()
    dates = pd.bdate_range("2025-12-31", "2026-10-23").strftime("%Y-%m-%d").tolist()
    expiries = {"c2609": "2026-09-14", "c2611": "2026-11-13", "c2701": "2027-01-15"}
    frames = {
        "market.parquet": pd.DataFrame(
            [
                dict(ticker=ticker, tradeDate=day, settlePrice=2200 + 20 * np.sin(i / 9) + i / 10)
                for ticker, expiry in expiries.items()
                for i, day in enumerate(dates)
                if day <= expiry
            ]
        ),
        "contracts.parquet": pd.DataFrame(
            [
                dict(ticker=ticker, listDate="2025-12-31", lastTradeDate=expiry)
                for ticker, expiry in expiries.items()
            ]
        ),
        "calendar.parquet": pd.DataFrame([dict(calendarDate=day, isOpen=1) for day in dates]),
    }
    files = {}
    for filename, frame in frames.items():
        frame.to_parquet(cache / filename, index=False)
        files[filename] = dict(
            sha256=hashlib.sha256((cache / filename).read_bytes()).hexdigest(), rows=len(frame)
        )
    (cache / "manifest.json").write_text(
        json.dumps(
            dict(
                schema_version="market-cache-v1",
                source="uqer",
                synthetic_test_fixture=True,
                requested_start="2025-12-31",
                requested_end="2026-10-23",
                tickers=list(expiries),
                files=files,
            )
        )
    )
    split = root / "split.json"
    split.write_text(
        json.dumps(
            dict(calibration_start="2026-06-11", validation_start="2026-07-31", test_opened=False)
        )
    )
    run(cache, root / "price", root / "models", split)
    return root


def test_saved_parameters_match_forecast(experiment):
    data = overview(experiment / "price", "c2701")
    params = json.loads((experiment / "models/parameters.json").read_text())
    past = [row["settlement"] for row in data["series"][-20:]]
    actual = predict(params, [features(past)], [past[-1]])[0]
    expected = next(
        m["value"] for m in data["forecast"]["methods"] if m["method_id"] == "price_ridge"
    )
    assert actual == pytest.approx(expected, abs=1e-10)
    assert params["train_last_label_date"] < params["split_manifest"]["calibration_start"]


def test_features_and_fit_have_no_future_input():
    import pandas as pd

    history = np.linspace(2000, 2200, 20)
    first = features(history)
    future = np.full(20, 9000)
    assert first == features(np.concatenate([history, future])[:20])
    train = pd.DataFrame(
        [
            dict(zip(["return_5", "return_19", "volatility_19", "ma_ratio"], features(history + i)))
            | dict(
                as_of=f"2026-01-{i + 1:02}",
                ticker="c2701",
                settlement=2200 + i,
                observation_mean=2205 + i,
            )
            for i in range(5)
        ]
    )
    params = fit(train)
    assert params["mean"] == pytest.approx(train[params["features"]].mean().to_numpy())
    assert params["alpha"] == 1.0


def test_expired_contract_has_no_forecast(experiment):
    result = overview(experiment / "price", "c2609")
    assert result["forecast"]["status"] == "unavailable"
    assert not result["forecast"]["methods"]
    assert result["forecast"]["target_dates"] is None


@pytest.fixture
def store(tmp_path, experiment):
    shutil.copytree(experiment / "price", tmp_path / "price")
    return tmp_path / "price"


def mutate(store, update):
    path = store / "c2701.json"
    data = json.loads(path.read_text())
    update(data)
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    manifest = json.loads((store / "manifest.json").read_text())
    manifest["documents"]["c2701"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (store / "manifest.json").write_text(json.dumps(manifest))


def test_hash_integrity(store):
    (store / "c2701.json").write_text("{}")
    with pytest.raises(PriceError) as caught:
        overview(store)
    assert caught.value.status == 503


@pytest.mark.parametrize(
    "patch",
    [
        lambda d: d.update(ticker="c2705"),
        lambda d: d["series"][0].update(date="2025-12-30"),
        lambda d: d.update(last_trade_date="2026-10-01"),
        lambda d: d["validation"]["backtest"][0].update(label_available_at="2026-12-31"),
    ],
)
def test_identity_date_and_expiry_validation(store, patch):
    mutate(store, patch)
    with pytest.raises(PriceError) as caught:
        overview(store)
    assert caught.value.status == 503


def test_unknown_contract(store):
    with pytest.raises(PriceError) as caught:
        overview(store, "c9999")
    assert caught.value.status == 404


def test_near_expiry_contract_has_no_forecast(experiment):
    from app.services.price_service import has_horizon_capacity

    assert not has_horizon_capacity("2026-10-23", "2026-11-13")
    result = overview(experiment / "price", "c2611")
    assert result["forecast"]["status"] == "unavailable"
    assert not result["forecast"]["methods"]


def test_future_label_changes_cannot_change_fitted_parameters(experiment, tmp_path):
    # Perturb only July-and-later observations; fitted training parameters must be identical.
    cache = tmp_path / "market"
    shutil.copytree(experiment / "market", cache)
    market = pd.read_parquet(cache / "market.parquet")
    market.loc[market.tradeDate >= "2026-07-01", "settlePrice"] *= 1.2
    market.to_parquet(cache / "market.parquet", index=False)
    manifest = json.loads((cache / "manifest.json").read_text())
    manifest["files"]["market.parquet"]["sha256"] = hashlib.sha256(
        (cache / "market.parquet").read_bytes()
    ).hexdigest()
    (cache / "manifest.json").write_text(json.dumps(manifest))
    run(cache, tmp_path / "price", tmp_path / "models", experiment / "split.json")
    original = json.loads((experiment / "models/parameters.json").read_text())
    changed = json.loads((tmp_path / "models/parameters.json").read_text())
    assert changed == original
