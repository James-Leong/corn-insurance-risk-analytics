"""Export trusted local fitted artifacts without training or changing reports."""

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from research.export import encode
from research.features import FEATURES
from research.labels import build_samples
from research.train import predict_hurdle


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linear_parameters(model) -> dict:
    result = {"class": type(model).__name__, "hyperparameters": model.get_params(deep=False)}
    for name in ("coef_", "intercept_", "classes_", "mean_", "scale_", "var_", "n_features_in_"):
        if hasattr(model, name):
            value = getattr(model, name)
            result[name] = value.tolist() if hasattr(value, "tolist") else value
    return result


def write_new(path: Path, value) -> None:
    with path.open("xb") as stream:
        stream.write(encode(value))


def export_models(model_dir: Path, bundle: dict, report_bytes: bytes, cache: Path) -> dict:
    """Only load artifacts from the local trusted directory, after recorded hash checks."""
    metadata = json.loads((model_dir / "model-artifacts.json").read_text())
    for name in ("parameters.json", "deployment-manifest.json"):
        if (model_dir / name).exists():
            raise ValueError(f"Export already exists: {name}; existing artifacts are immutable")
    market = pd.read_parquet(cache / "market.parquet")
    calendar = pd.read_parquet(cache / "calendar.parquet")
    samples = build_samples(market, calendar)
    cases = bundle["partitions"]["validation"]["cases"]
    selected_cases = (
        [cases[i] for i in sorted(set([0, len(cases) // 2, len(cases) - 1]))] if cases else []
    )
    rows = []
    for case in selected_cases:
        matched = samples[
            (samples.as_of == case["valuation_date"])
            & (samples.ticker == case["contract_id"])
            & (samples.strike == case["guarantee_price"])
        ]
        if len(matched) != 1:
            raise ValueError("Report case cannot be uniquely reproduced from cache")
        rows.append(matched.iloc[0])
    check_rows = pd.DataFrame(rows)
    parameters = {
        "schema_version": "model-parameters-v1",
        "features": FEATURES,
        "libraries": {
            name: version(name) for name in ("numpy", "scikit-learn", "xgboost", "joblib", "pandas")
        },
        "python": platform.python_version(),
        "release_state": "research_only",
        "applicability": {
            "data_start": bundle["data_start"],
            "data_end": bundle["data_end"],
            "lookback_trading_days": 20,
            "horizon_trading_days": 20,
            "price_field": "settlePrice",
            "terms": bundle["protocol"]["terms"],
            "restriction": "Frozen historical research only; no current-policy or pricing approval",
        },
        "methods": {},
    }
    checks = []
    for method, record in metadata.items():
        path = model_dir / record["filename"]
        if (
            path.parent.resolve() != model_dir.resolve()
            or path.is_symlink()
            or sha(path) != record["sha256"]
        ):
            raise ValueError("Untrusted or altered model artifact")
        classifier, regressor, calibrator = models = joblib.load(path)
        detail = {
            "calibrator": linear_parameters(calibrator),
            "probability_formula": "sigmoid(intercept + coefficient * logit(clip(raw_probability,1e-6,1-1e-6)))",
            "expected_payout_formula": "calibrated_probability * clip(conditional_loss_ratio,0,1) * strike * quantity",
        }
        if method == "glm_hurdle":
            detail["classifier"] = {
                "scaler": linear_parameters(classifier.steps[0][1]),
                "model": linear_parameters(classifier.steps[-1][1]),
            }
            detail["regressor"] = {
                "scaler": linear_parameters(regressor.steps[0][1]),
                "model": linear_parameters(regressor.steps[-1][1]),
            }
        else:
            for name, estimator in (("classifier", classifier), ("regressor", regressor)):
                native = model_dir / f"{method}-{name}.json"
                if native.exists():
                    raise ValueError("Native model already exists")
                estimator.save_model(native)
                detail[name] = {
                    "native_file": native.name,
                    "booster_config": json.loads(estimator.get_booster().save_config()),
                }
        parameters["methods"][method] = detail
        if len(check_rows):
            restored = predict_hurdle(models, check_rows)
            for case, prediction in zip(selected_cases, restored):
                recorded = next(item for item in case["outputs"] if item["method_id"] == method)
                for field, report_field in (
                    ("expected_payout", "expected_payout"),
                    ("trigger_probability", "claim_probability"),
                    ("conditional_mean_payout", "conditional_mean_payout"),
                ):
                    if not np.isclose(
                        prediction[field], recorded[report_field], rtol=1e-9, atol=1e-8
                    ):
                        raise ValueError(
                            f"Reload prediction differs: {method}/{case['case_id']}/{field}"
                        )
            checks.append(
                {
                    "method_id": method,
                    "cases": [case["case_id"] for case in selected_cases],
                    "joblib_reload_matches_report": True,
                    "rtol": 1e-9,
                    "atol": 1e-8,
                }
            )
            if method == "xgboost_hurdle":
                from xgboost import XGBClassifier, XGBRegressor

                native_classifier, native_regressor = XGBClassifier(), XGBRegressor()
                native_classifier.load_model(model_dir / f"{method}-classifier.json")
                native_regressor.load_model(model_dir / f"{method}-regressor.json")
                native_result = predict_hurdle(
                    (native_classifier, native_regressor, calibrator), check_rows
                )
                if not np.allclose(
                    [item["expected_payout"] for item in restored],
                    [item["expected_payout"] for item in native_result],
                    rtol=1e-9,
                    atol=1e-8,
                ):
                    raise ValueError("Native XGBoost reload differs")
                checks[-1]["native_reload_matches_joblib"] = True
    write_new(model_dir / "parameters.json", parameters)
    manifest = {
        "schema_version": "model-deployment-v1",
        "run_id": bundle["run_id"],
        "release_state": "research_only",
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "original_training_source_hashes": bundle["protocol"].get("research_source_hashes", {}),
        "data_version": bundle["protocol"]["data_version"],
        "environment_lock_hash": bundle["protocol"].get("environment_lock_hash"),
        "export_script_sha256": sha(Path(__file__)),
        "files": {
            file.name: {"sha256": sha(file), "bytes": file.stat().st_size}
            for file in sorted(model_dir.iterdir())
            if file.is_file()
        },
        "verification": checks,
        "note": "Additional exports from original fitted artifacts; no retraining, no changes to published report or original joblib.",
    }
    write_new(model_dir / "deployment-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.read_bytes()
    result = export_models(args.models, json.loads(report), report, args.cache)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "files": list(result["files"]),
                "verification": result["verification"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
