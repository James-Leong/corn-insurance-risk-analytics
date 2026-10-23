import numpy as np
import pandas as pd
import pytest
from research.baselines import historical_prediction
from research.labels import build_samples, payout
from research.splits import split_samples


def market_fixture():
    dates = pd.bdate_range("2025-12-31", "2026-10-23").strftime("%Y-%m-%d")
    calendar = pd.DataFrame({"calendarDate": dates, "isOpen": 1})
    market = pd.DataFrame(
        {
            "ticker": "c2701",
            "tradeDate": dates,
            "settlePrice": 2200 + 100 * np.sin(np.arange(len(dates)) / 10),
        }
    )
    return market, calendar


def test_future_label_does_not_leak_into_features():
    market, calendar = market_fixture()
    original = build_samples(market, calendar)
    first = original.iloc[0]
    market.loc[market.tradeDate > first.as_of, "settlePrice"] *= 0.8
    changed = build_samples(market, calendar).iloc[0]
    for key in (
        "return_5",
        "return_19",
        "volatility_19",
        "ma_ratio",
        "strike_ratio",
        "strike",
        "history_returns",
    ):
        assert first[key] == changed[key]
    assert first.actual_payout != changed.actual_payout


def test_purge_uses_label_date_and_keeps_same_day_together():
    market, calendar = market_fixture()
    parts, manifest = split_samples(build_samples(market, calendar))
    assert parts["train"].label_available_at.max() < parts["calibration"].as_of.min()
    assert parts["calibration"].label_available_at.max() < parts["validation"].as_of.min()
    assert manifest["test_opened"] is False
    assert manifest["purged_count"] > 0


def test_missing_calendar_day_not_bridged_and_no_prior_history():
    market, calendar = market_fixture()
    baseline = build_samples(market, calendar)
    missing = market.drop(index=55)
    samples = build_samples(missing, calendar)
    assert len(samples) < len(baseline)
    market.loc[0, "tradeDate"] = "2025-12-30"
    with pytest.raises(ValueError, match="outside"):
        build_samples(market, calendar)


def test_domain_label_and_reproducible_scenarios():
    assert payout(2200, 2100) == 10000
    assert payout(2200, 2300) == 0
    market, calendar = market_fixture()
    row = next(build_samples(market, calendar).itertuples())
    assert historical_prediction(row) == historical_prediction(row)
    assert historical_prediction(row)["p90_payout"] is None


def test_runner_publishes_valid_bundle_and_refuses_overwrite(tmp_path):
    import hashlib
    import json
    from app.domain.comparison import Bundle
    from research.run import run

    market, calendar = market_fixture()
    cache = tmp_path / "cache"
    cache.mkdir()
    frames = {
        "market.parquet": market,
        "calendar.parquet": calendar,
        "contracts.parquet": pd.DataFrame({"ticker": ["c2701"]}),
    }
    files = {}
    for name, frame in frames.items():
        frame.to_parquet(cache / name, index=False)
        files[name] = {"sha256": hashlib.sha256((cache / name).read_bytes()).hexdigest()}
    (cache / "manifest.json").write_text(
        json.dumps({"requested_start": "2025-12-31", "requested_end": "2026-10-23", "files": files})
    )
    result = run(cache, tmp_path / "reports", "test-run")
    bundle = Bundle.model_validate_json(result.read_text())
    assert bundle.released_partitions == ["validation"]
    assert not bundle.selection.frozen
    assert len(bundle.partitions["validation"].models) == 5
    assert all(model.coverage == 1 for model in bundle.partitions["validation"].models)
    with pytest.raises(ValueError, match="immutable"):
        run(cache, tmp_path / "reports", "test-run")


def test_calibration_insufficiency_is_not_silently_fitted():
    from research.train import fit_hurdle

    market, calendar = market_fixture()
    parts, _ = split_samples(build_samples(market, calendar))
    calibration = parts["calibration"].copy()
    calibration["triggered"] = 1
    with pytest.raises(ValueError, match="calibration"):
        fit_hurdle("glm_hurdle", parts["train"], calibration)
