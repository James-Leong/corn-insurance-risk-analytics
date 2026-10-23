"""Date-weighted metrics; failed coverage never changes the target cohort."""

import numpy as np


def evaluate(rows, predictions):
    complete = len(predictions) == len(rows) and len(rows) > 0
    records = []
    if complete:
        weights = rows.weight.to_numpy()
        error = np.array([p["expected_payout"] for p in predictions]) - rows.actual_payout
        probabilities = np.array([p["trigger_probability"] for p in predictions])
        values = {
            "expected_payout_rmse": float(np.sqrt(np.average(error**2, weights=weights))),
            "expected_payout_mae": float(np.average(abs(error), weights=weights)),
            "expected_payout_bias": float(np.average(error, weights=weights)),
            "trigger_brier": float(
                np.average((probabilities - rows.triggered) ** 2, weights=weights)
            ),
        }
    else:
        values = dict.fromkeys(
            ["expected_payout_rmse", "expected_payout_mae", "expected_payout_bias", "trigger_brier"]
        )
    for metric, value in values.items():
        records.append(
            {
                "metric_id": metric,
                "value": value,
                "unit": "probability_squared" if metric == "trigger_brier" else "CNY",
                "direction": "closer_to_zero" if metric.endswith("bias") else "lower_is_better",
                "missing_reason": None if value is not None else "method_unavailable",
            }
        )
    return records


def calibration_bins(rows, predictions, method):
    if not predictions:
        return []
    probabilities = np.array([p["trigger_probability"] for p in predictions])
    result = []
    for low in np.arange(0, 1, 0.2):
        mask = (probabilities >= low) & (
            probabilities <= low + 0.2 if low > 0.79 else probabilities < low + 0.2
        )
        if mask.any():
            part = rows[mask]
            result.append(
                {
                    "method_id": method,
                    "bin_lower": float(low),
                    "bin_upper": float(low + 0.2),
                    "predicted_probability": float(
                        np.average(probabilities[mask], weights=part.weight)
                    ),
                    "observed_frequency": float(np.average(part.triggered, weights=part.weight)),
                    "sample_count": int(mask.sum()),
                    "date_count": int(part.as_of.nunique()),
                }
            )
    return result


def error_slices(rows, predictions):
    records = []
    for method, estimates in predictions.items():
        if not estimates:
            continue
        expected = np.array([p["expected_payout"] for p in estimates])
        for ticker in sorted(rows.ticker.unique()):
            mask = rows.ticker.to_numpy() == ticker
            part = rows[mask]
            error = expected[mask] - part.actual_payout
            records.append(
                {
                    "method_id": method,
                    "group": ticker,
                    "sample_count": len(part),
                    "date_count": int(part.as_of.nunique()),
                    "rmse": float(np.sqrt(np.average(error**2, weights=part.weight))),
                    "bias": float(np.average(error, weights=part.weight)),
                    "unit": "CNY",
                }
            )
    return records
