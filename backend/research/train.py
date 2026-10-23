"""Small fixed model budget and independent temporal probability calibration."""

import numpy as np
from sklearn.linear_model import GammaRegressor, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from research.features import FEATURES


def fit_hurdle(method: str, train, calibration):
    if train.as_of.nunique() < 15 or train.triggered.nunique() < 2:
        raise ValueError("Insufficient training dates/classes")
    positive = train[train.triggered > 0]
    if positive.as_of.nunique() < 10:
        raise ValueError("Fewer than10 positive training dates")
    if calibration.as_of.nunique() < 10 or calibration.triggered.nunique() < 2:
        raise ValueError("Insufficient independent calibration dates/classes")
    if method == "glm_hurdle":
        classifier = make_pipeline(
            StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=42)
        )
        regressor = make_pipeline(StandardScaler(), GammaRegressor(alpha=0.1, max_iter=1000))
    elif method == "xgboost_hurdle":
        from xgboost import XGBClassifier, XGBRegressor

        params = dict(n_estimators=100, max_depth=2, learning_rate=0.05, n_jobs=1, random_state=42)
        classifier = XGBClassifier(**params, objective="binary:logistic", eval_metric="logloss")
        regressor = XGBRegressor(**params, objective="reg:squarederror")
    else:
        raise ValueError("Unknown hurdle method")

    def fit(model, x, y, weights):
        key = f"{model.steps[-1][0]}__sample_weight" if hasattr(model, "steps") else "sample_weight"
        model.fit(x, y, **{key: weights})

    fit(classifier, train[FEATURES], train.triggered, train.weight)
    fit(regressor, positive[FEATURES], positive.loss_ratio, positive.weight)
    raw = np.clip(classifier.predict_proba(calibration[FEATURES])[:, 1], 1e-6, 1 - 1e-6)
    calibrator = LogisticRegression(C=1, random_state=42)
    calibrator.fit(
        np.log(raw / (1 - raw)).reshape(-1, 1),
        calibration.triggered,
        sample_weight=calibration.weight,
    )
    return classifier, regressor, calibrator


def predict_hurdle(models, rows):
    classifier, regressor, calibrator = models
    raw = np.clip(classifier.predict_proba(rows[FEATURES])[:, 1], 1e-6, 1 - 1e-6)
    probability = calibrator.predict_proba(np.log(raw / (1 - raw)).reshape(-1, 1))[:, 1]
    conditional = np.clip(regressor.predict(rows[FEATURES]), 0, 1) * rows.strike * rows.quantity
    return [
        {
            "trigger_probability": float(p),
            "conditional_mean_payout": float(c),
            "expected_payout": float(p * c),
            "p90_payout": None,
            "p90_status": "unsupported",
        }
        for p, c in zip(probability, conditional)
    ]
