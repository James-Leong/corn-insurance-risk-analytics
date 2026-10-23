"""Token-free inference on released historical validation dates; never trains models."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.domain.analysis import AnalysisRequest
from app.domain.insurance import PriceInsuranceScenario
from app.repositories.comparison_repository import ComparisonError, ComparisonRepository
from app.repositories.market_cache import read_market_snapshot
from app.repositories.model_repository import ModelRepository, RUN_ID

FEATURES = ["return_5", "return_19", "volatility_19", "ma_ratio", "strike_ratio"]
NAMES = {
    "historical_blocks": "历史重采样",
    "glm_hurdle": "Logistic＋Gamma",
    "xgboost_hurdle": "XGBoost",
}
WARNINGS = [
    "历史研究合同：未来20个交易日的具体合约平均结算价，不是现货保单或正式报价。",
    "模型只使用估值日及之前的行情；观察期实际结果仅用于事后核对，不参与推断。",
    "概率与预期赔款采用无免赔、无封顶的研究条款；免赔与封顶仅影响下方确定性压力情景。",
    "压力情景不代表发生概率；资金缺口不是正式偿付能力结论。",
    "当前没有正式获选的生产模型；各方法仅供研究比较，P90尚不可用。",
]


class AnalysisService:
    def __init__(self, market_root: Path, model_root: Path, comparison_root: Path):
        self.market_root, self.model_root, self.comparison_root = (
            market_root,
            model_root,
            comparison_root,
        )

    def context(self):
        repository = ComparisonRepository(self.comparison_root)
        bundle = repository.get(RUN_ID)
        if "validation" not in bundle.released_partitions or bundle.source_kind != "measured":
            raise ComparisonError(503, "analysis_unavailable", "暂无已发布的真实数据验证样本")
        raw = repository._read(repository.root / "runs" / RUN_ID / "bundle.json")
        models, manifest, parameters, split = ModelRepository(self.model_root).load(
            hashlib.sha256(raw).hexdigest()
        )
        if (
            parameters["features"] != FEATURES
            or manifest["data_version"] != bundle.protocol["data_version"]
        ):
            raise ComparisonError(503, "analysis_version_mismatch", "模型特征或数据版本不一致")
        cases = bundle.partitions["validation"].cases
        if any(case.valuation_date < split["validation_start"] for case in cases):
            raise ComparisonError(503, "analysis_invalid_partition", "验证样本时间边界不一致")
        return bundle, models, manifest, cases

    def options(self):
        bundle, _, _, cases = self.context()
        contracts = []
        for ticker in sorted({case.contract_id for case in cases}):
            contracts.append(
                {
                    "ticker": ticker,
                    "valuation_dates": sorted(
                        {case.valuation_date for case in cases if case.contract_id == ticker}
                    ),
                }
            )
        if not contracts:
            raise ComparisonError(503, "analysis_unavailable", "暂无可演示历史合同")
        default = next((c for c in contracts if c["ticker"] == "c2701"), contracts[0])
        return {
            "schema_version": "analysis-v1",
            "run_id": bundle.run_id,
            "contracts": contracts,
            "strike_ratios": [0.95, 1.0, 1.05],
            "defaults": AnalysisRequest(
                ticker=default["ticker"], valuation_date=default["valuation_dates"][-1]
            ).model_dump(),
            "warnings": WARNINGS,
        }

    def estimate(self, request: AnalysisRequest):
        bundle, models, manifest, cases = self.context()
        eligible = [
            c
            for c in cases
            if c.contract_id == request.ticker and c.valuation_date == request.valuation_date
        ]
        if not eligible:
            raise ComparisonError(422, "analysis_date_unsupported", "请选择可用的历史验证估值日")
        try:
            rows, cache_manifest = read_market_snapshot(
                self.market_root, request.ticker, bundle.data_start, bundle.data_end
            )
            cache_hash = hashlib.sha256(
                json.dumps(cache_manifest, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            # The training data version is the hash of the exact manifest bytes.
            if (
                hashlib.sha256(
                    (
                        json.dumps(cache_manifest, ensure_ascii=False, indent=2, allow_nan=False)
                        + "\n"
                    ).encode()
                ).hexdigest()
                != manifest["data_version"]
            ):
                raise ValueError("Cache/model version mismatch")
            dates = [str(r["tradeDate"])[:10] for r in rows]
            i = dates.index(request.valuation_date)
            past = np.asarray([r["settlePrice"] for r in rows[max(0, i - 19) : i + 1]], dtype=float)
            future = np.asarray([r["settlePrice"] for r in rows[i + 1 : i + 21]], dtype=float)
            if len(past) != 20 or len(future) != 20:
                raise ValueError("Incomplete observation window")
        except (ValueError, OSError) as exc:
            raise ComparisonError(
                503, "analysis_cache_unavailable", "行情快照无法支持该历史估值或版本不一致"
            ) from exc
        strike = round(float(past[-1] * request.strike_ratio), 2)
        if not any(c.guarantee_price == strike for c in eligible):
            raise ComparisonError(
                422, "analysis_terms_unsupported", "保障价格比例不属于当前模型研究条款"
            )
        returns = np.diff(np.log(past))
        features = pd.DataFrame(
            [
                [
                    float(past[-1] / past[-6] - 1),
                    float(past[-1] / past[0] - 1),
                    float(returns.std()),
                    float(past[-1] / past.mean() - 1),
                    request.strike_ratio,
                ]
            ],
            columns=FEATURES,
        )
        rng = np.random.default_rng(42)
        starts = rng.integers(0, len(returns) - 4, size=(512, 4))
        sampled = np.concatenate(
            [returns[starts[:, j, None] + np.arange(5)] for j in range(4)], axis=1
        )
        prices = past[-1] * np.exp(np.cumsum(sampled, axis=1))
        losses = (
            np.round(np.maximum(strike - prices.mean(axis=1), 0) * 100, 2) * request.quantity / 100
        )
        positive = losses[losses > 0]
        methods = [
            {
                "method_id": "historical_blocks",
                "name": NAMES["historical_blocks"],
                "claim_probability": float(np.mean(losses > 0)),
                "conditional_mean_payout": float(positive.mean()) if len(positive) else None,
                "expected_payout": float(losses.mean()),
                "p90_payout": None,
            }
        ]
        for method, (classifier, regressor, calibrator) in models.items():
            raw = np.clip(classifier.predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)
            probability = calibrator.predict_proba(np.log(raw / (1 - raw)).reshape(-1, 1))[0, 1]
            conditional = (
                float(np.clip(regressor.predict(features)[0], 0, 1)) * strike * request.quantity
            )
            methods.append(
                {
                    "method_id": method,
                    "name": NAMES[method],
                    "claim_probability": float(probability),
                    "conditional_mean_payout": conditional,
                    "expected_payout": float(probability * conditional),
                    "p90_payout": None,
                }
            )
        stress = []
        for shock in request.shocks:
            price = round(float(past[-1] * (1 + shock / 100)), 2)
            gross = PriceInsuranceScenario(request.quantity, strike, price).calculate()[
                "gross_payout"
            ]
            net = PriceInsuranceScenario(
                request.quantity, strike, price, request.deductible, request.payout_cap
            ).calculate()["gross_payout"]
            stress.append(
                {
                    "shock_percent": shock,
                    "scenario_price": price,
                    "gross_payout": gross,
                    "net_payout": net,
                    "budget_gap": round(max(net - request.budget, 0), 2),
                }
            )
        payload = {
            "schema_version": "analysis-v1",
            "run_id": RUN_ID,
            "release_state": "research_only",
            "request": request.model_dump(),
            "contract": {
                "ticker": request.ticker,
                "valuation_date": request.valuation_date,
                "settlement": float(past[-1]),
                "guarantee_price": strike,
                "quantity": request.quantity,
                "observation_start": dates[i + 1],
                "observation_end": dates[i + 20],
            },
            "methods": methods,
            "price_references": {"last": float(past[-1]), "ma20": float(past.mean())},
            "observed": {
                "mean_settlement": float(future.mean()),
                "payout": PriceInsuranceScenario(
                    request.quantity, strike, float(future.mean())
                ).calculate()["gross_payout"],
            },
            "stress": stress,
            "versions": {
                "data": manifest["data_version"],
                "model": RUN_ID,
                "rule": "price-loss-20d-v1",
                "cache_scope": cache_hash,
            },
            "warnings": WARNINGS,
        }
        payload["report_id"] = (
            "analysis-"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:16]
        )
        return payload
