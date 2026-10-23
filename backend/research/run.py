"""Usage: python -m research.run --cache ../var/market --output ../var/comparison."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from research.baselines import historical_prediction
from research.evaluate import calibration_bins, error_slices, evaluate
from research.export import digest, encode
from research.features import END, START
from research.labels import build_samples, payout
from research.publish import publish
from research.splits import split_samples
from research.train import fit_hurdle, predict_hurdle

METHODS = ("historical_blocks", "glm_hurdle", "xgboost_hurdle")


def run(cache: Path, output: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run ID")
    if (output / "runs" / run_id).exists():
        raise ValueError("Existing runs are immutable; choose a new run ID")
    manifest = json.loads((cache / "manifest.json").read_text())
    if manifest.get("requested_start") != START or manifest.get("requested_end") != END:
        raise ValueError("Cache must match the frozen requested date range")
    for name in ("market.parquet", "calendar.parquet", "contracts.parquet"):
        actual = hashlib.sha256((cache / name).read_bytes()).hexdigest()
        if manifest["files"][name]["sha256"] != actual:
            raise ValueError(f"Cache checksum mismatch: {name}")
    contracts = pd.read_parquet(cache / "contracts.parquet")
    market = pd.read_parquet(cache / "market.parquet")
    if not set(market.ticker.astype(str)).issubset(set(contracts.ticker.astype(str))):
        raise ValueError("Market contract absent from metadata")
    samples = build_samples(
        pd.read_parquet(cache / "market.parquet"), pd.read_parquet(cache / "calendar.parquet")
    )
    partitions, split = split_samples(samples)
    validation = partitions["validation"]
    models, predictions, bins = [], {}, []
    fitted_models = {}
    for method in METHODS:
        reason = None
        try:
            if method == "historical_blocks":
                estimates = [historical_prediction(row) for row in validation.itertuples()]
            else:
                fitted = fit_hurdle(method, partitions["train"], partitions["calibration"])
                estimates = predict_hurdle(fitted, validation)
                fitted_models[method] = fitted
            if not estimates:
                raise ValueError("Empty validation cohort")
        except (ValueError, ImportError) as exc:
            estimates = []
            reason = f"insufficient_data_or_dependency: {exc}"
        predictions[method] = estimates
        models.append(
            {
                "method_id": method,
                "model_version": "limited-2026-v1",
                "task": "payout_risk",
                "release_state": "research_only",
                "coverage": len(estimates) / len(validation) if len(validation) else 0,
                "failure_count": len(validation) - len(estimates),
                "reason_code": reason,
                "metrics": evaluate(validation, estimates),
            }
        )
        bins.extend(calibration_bins(validation, estimates, method))
    for method in ("price_last", "price_ma20"):
        error = validation[method] - validation.observation_mean
        models.append(
            {
                "method_id": method,
                "model_version": "limited-2026-v1",
                "task": "price_reference",
                "release_state": "research_only",
                "coverage": 1.0,
                "failure_count": 0,
                "metrics": [
                    {
                        "metric_id": "observation_price_rmse",
                        "value": float(np.sqrt(np.average(error**2, weights=validation.weight))),
                        "unit": "CNY/ton",
                        "direction": "lower_is_better",
                        "missing_reason": None,
                    }
                ],
            }
        )
    cases = []
    for i, row in enumerate(validation.itertuples()):
        outputs = []
        for method in METHODS:
            pred = predictions[method][i] if predictions[method] else {}
            outputs.append(
                {
                    "method_id": method,
                    "claim_probability": pred.get("trigger_probability"),
                    "expected_payout": pred.get("expected_payout"),
                    "conditional_mean_payout": pred.get("conditional_mean_payout"),
                    "p90_payout": None,
                    "p90_status": "not_validated"
                    if method == "historical_blocks"
                    else "unsupported",
                    "reason_code": None if pred else "insufficient_data",
                    "scenario_payout": None,
                }
            )
        for method in ("price_last", "price_ma20"):
            outputs.append(
                {
                    "method_id": method,
                    "claim_probability": None,
                    "expected_payout": None,
                    "p90_payout": None,
                    "p90_status": "unsupported",
                    "scenario_payout": payout(row.strike, getattr(row, method)),
                    "reference_price": float(getattr(row, method)),
                }
            )
        cases.append(
            {
                "case_id": f"case-{i:04d}",
                "valuation_date": row.as_of,
                "contract_id": row.ticker,
                "guarantee_price": row.strike,
                "quantity_tons": row.quantity,
                "observed_payout": row.actual_payout,
                "observation_mean": row.observation_mean,
                "label_available_at": row.label_available_at,
                "observation_dates": row.observation_dates,
                "price_field": "settlePrice",
                "deductible_per_ton": 0,
                "payout_cap": None,
                "outputs": outputs,
            }
        )
    bundle = {
        "schema_version": "comparison-v1",
        "run_id": run_id,
        "comparison_group_id": "corn-price20-2026",
        "title": "玉米价格险：2026有限历史研究",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_kind": "measured",
        "label_kind": "rule_generated",
        "run_status": "completed" if all(predictions.values()) else "incomplete",
        "data_start": START,
        "data_end": END,
        "warnings": [
            "仅历史行情与研究条款生成的标签，不是真实赔案；仅供研究。",
            "不足一年历史，20日目标重叠；不支持正式选型、定价、理赔或生产发布。",
            "回看期缩短为20交易日，仅为限定数据范围的独立研究版本；历史重采样仅19个收益，尾部覆盖有限。",
            "未打开最终测试集，未批准默认模型；P90未验证。",
        ],
        "protocol": {
            "task": "payout_risk",
            "window_trading_days": 20,
            "lookback_trading_days": 20,
            "data_version": digest(manifest),
            "rule_version": "price-domain-v1",
            "split_version": split["version"],
            "sample_hash": digest(validation.sample_id.tolist()),
            "split_manifest": split,
            "feature_schema_version": "market-terms-20d-v1",
            "seed": 42,
            "terms": {
                "strike_ratios": [0.95, 1, 1.05],
                "quantity": 100,
                "deductible": 0,
                "cap": None,
            },
            "weighting": "equal_date_then_equal_contract_terms",
            "environment_lock_hash": hashlib.sha256(
                (Path(__file__).parents[1] / "uv.lock").read_bytes()
            ).hexdigest(),
            "research_source_hashes": {
                file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                for file in sorted(Path(__file__).parent.glob("*.py"))
            },
            "parameters": {
                "historical_blocks": {"paths": 512, "block": 5},
                "hurdles": {"search_trials": 1, "calibration": "sigmoid"},
            },
        },
        "selection": {
            "frozen": False,
            "selected_method_id": None,
            "reason_code": "limited_history_research_only",
        },
        "test_review": {"approved": False},
        "released_partitions": ["validation"],
        "partitions": {
            "validation": {
                "sample_count": len(validation),
                "date_count": validation.as_of.nunique(),
                "models": models,
                "evidence": {
                    "calibration": bins,
                    "error_slices": error_slices(validation, predictions),
                    "data_quality": [
                        {"check": "purged_date_split", "status": "passed", "detail": split},
                        {"check": "source_quality", "detail": manifest.get("quality", {})},
                    ],
                },
                "cases": cases[:2000],
            }
        },
    }
    from app.domain.comparison import Bundle

    Bundle.model_validate(json.loads(encode(bundle)))
    model_dir = output.parent / "models" / run_id
    model_dir.mkdir(parents=True, exist_ok=False)
    import joblib

    artifacts = {}
    for method, fitted in fitted_models.items():
        artifact = model_dir / f"{method}.joblib"
        joblib.dump(fitted, artifact)
        artifacts[method] = {
            "filename": artifact.name,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "release_state": "research_only",
            "warning": "Trusted offline artifact only; never load untrusted pickle.",
        }
    (model_dir / "model-artifacts.json").write_bytes(encode(artifacts))
    (model_dir / "split-manifest.json").write_bytes(encode(split))
    bundle["protocol"]["model_artifacts"] = artifacts
    from research.export_models import export_models

    export_models(model_dir, bundle, encode(bundle), cache)
    return publish(bundle, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("../var/market"))
    parser.add_argument("--output", type=Path, default=Path("../var/comparison"))
    parser.add_argument("--run-id", default="corn-2026-v1")
    args = parser.parse_args()
    print(run(args.cache, args.output, args.run_id))


if __name__ == "__main__":
    main()
