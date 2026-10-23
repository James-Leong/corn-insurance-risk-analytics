"""Frozen, offline 20-trading-day mean settlement experiment; no API calls."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from app.repositories.market_cache import read_market_snapshot
from app.services.price_service import has_horizon_capacity
from research.features import END, START, prepare_market
from research.labels import build_samples

FEATURES = ["return_5", "return_19", "volatility_19", "ma_ratio"]
VERSION = "price-2026-v1"
METHODS = ["price_last", "price_ma20", "price_ridge"]


def features(past):
    past = np.asarray(past, dtype=float)
    if len(past) != 20 or not (np.isfinite(past) & (past > 0)).all():
        raise ValueError("Exactly20 finite positive settlements required")
    return [
        past[-1] / past[-6] - 1,
        past[-1] / past[0] - 1,
        np.diff(np.log(past)).std(),
        past[-1] / past.mean() - 1,
    ]


def predict(parameters, matrix, settlements):
    normalized = (np.asarray(matrix) - parameters["mean"]) / parameters["scale"]
    returns = normalized @ parameters["coef"] + parameters["intercept"]
    return np.asarray(settlements) * (1 + returns)


def fit(train):
    scaler = StandardScaler().fit(train[FEATURES])
    ridge = Ridge(alpha=1.0).fit(
        scaler.transform(train[FEATURES]),
        train.observation_mean / train.settlement - 1,
        sample_weight=(1 / train.groupby("as_of").ticker.transform("count")).to_numpy(),
    )
    return {
        "model_version": VERSION,
        "features": FEATURES,
        "alpha": 1.0,
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coef": ridge.coef_.tolist(),
        "intercept": float(ridge.intercept_),
        "target": "future20_mean_divided_by_current_minus_one",
    }


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()


def run(cache, output, model_dir, split_path):
    if output.exists() or model_dir.exists():
        raise ValueError("Immutable experiment already exists")
    source = json.loads((cache / "manifest.json").read_text())
    for ticker in source["tickers"]:
        read_market_snapshot(cache, ticker, START, END)
    market = pd.read_parquet(cache / "market.parquet")
    calendar = pd.read_parquet(cache / "calendar.parquet")
    contracts = pd.read_parquet(cache / "contracts.parquet")
    frame, dates = prepare_market(market, calendar)
    samples = build_samples(market, calendar).drop_duplicates(["ticker", "as_of"]).copy()
    split = json.loads(split_path.read_text())
    train = samples[
        (samples.as_of < split["calibration_start"])
        & (samples.label_available_at < split["calibration_start"])
    ]
    validation = samples[samples.as_of >= split["validation_start"]].copy()
    if train.empty or validation.empty:
        raise ValueError("Insufficient frozen partitions")
    parameters = fit(train)
    parameters["train_last_label_date"] = train.label_available_at.max()
    parameters["train_rows"] = len(train)
    parameters["split_manifest"] = split
    validation["price_ridge"] = predict(parameters, validation[FEATURES], validation.settlement)
    model_dir.mkdir(parents=True)
    parameter_bytes = encode(parameters)
    (model_dir / "parameters.json").write_bytes(parameter_bytes)
    output.mkdir(parents=True)
    tickers = [
        {"ticker": str(row.ticker), "last_trade_date": str(row.lastTradeDate)[:10]}
        for row in contracts.itertuples()
    ]
    documents = {}
    for contract in tickers:
        ticker = contract["ticker"]
        group = frame[frame.ticker == ticker]
        as_of = group.tradeDate.max()
        series = group.set_index("tradeDate").settlePrice.reindex(dates)
        past = series.loc[:as_of].tail(20).to_numpy()
        reason = None
        if as_of != END or contract["last_trade_date"] <= END:
            reason = "合约已到期或行情未覆盖快照截止日，不提供未来价格参照"
        elif not has_horizon_capacity(as_of, contract["last_trade_date"]):
            reason = "合约到期前不足20个工作日，无法覆盖20交易日目标"
        elif len(past) != 20 or not np.isfinite(past).all():
            reason = "缺少连续20交易日结算价"
        forecast = []
        if reason is None:
            estimates = [
                float(past[-1]),
                float(past.mean()),
                float(predict(parameters, [features(past)], [past[-1]])[0]),
            ]
            if not all(np.isfinite(estimates)) or min(estimates) <= 0:
                reason = "模型输出不满足有效价格范围"
            else:
                forecast = [dict(method_id=m, value=v) for m, v in zip(METHODS, estimates)]
        valid = validation[validation.ticker == ticker]
        metrics = []
        for method in METHODS:
            if len(valid):
                error = valid[method] - valid.observation_mean
                metrics.append(
                    dict(
                        method_id=method,
                        mae=float(abs(error).mean()),
                        rmse=float(np.sqrt((error**2).mean())),
                        bias=float(error.mean()),
                    )
                )
        backtest = [
            dict(
                as_of=row.as_of,
                label_available_at=row.label_available_at,
                actual=row.observation_mean,
                **{m: float(getattr(row, m)) for m in METHODS},
            )
            for row in valid.itertuples()
        ]
        document = dict(
            schema_version="price-v1",
            model_version=VERSION,
            data_start=START,
            data_end=END,
            tickers=tickers,
            ticker=ticker,
            as_of=as_of,
            latest_settlement=float(group.iloc[-1].settlePrice),
            last_trade_date=contract["last_trade_date"],
            series=[
                dict(date=row.tradeDate, settlement=float(row.settlePrice))
                for row in group.itertuples()
            ],
            forecast=dict(
                status="unavailable" if reason else "available",
                reason=reason,
                horizon_trading_days=20,
                target="future_mean_settlement",
                target_dates=None,
                methods=forecast,
            ),
            validation=dict(
                partition="validation",
                sample_count=len(valid),
                date_count=int(valid.as_of.nunique()),
                methods=metrics,
                backtest=backtest,
            ),
            warnings=[
                "离线历史快照；非实时行情，未来20交易日均价参照不是逐日价格。",
                "未来交易日历未缓存，具体观察日期待确认，不作为合同结算依据。",
                "Ridge固定参数仅在训练集拟合；验证集未用于调参，最终测试未打开。",
                "历史不足一年且目标窗口重叠，结果仅供研究，不代表未来准确率。",
            ],
        )
        raw = encode(document)
        filename = f"{ticker}.json"
        (output / filename).write_bytes(raw)
        documents[ticker] = {"file": filename, "sha256": hashlib.sha256(raw).hexdigest()}
    (output / "manifest.json").write_bytes(
        encode(
            dict(
                schema_version="price-store-v1",
                model_version=VERSION,
                data_start=START,
                data_end=END,
                documents=documents,
                parameters_sha256=hashlib.sha256(parameter_bytes).hexdigest(),
                source_manifest_sha256=hashlib.sha256(
                    (cache / "manifest.json").read_bytes()
                ).hexdigest(),
                split_manifest=split,
                training_rows=len(train),
                validation_rows=len(validation),
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            )
        )
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("../var/market"))
    parser.add_argument("--output", type=Path, default=Path("../var/price"))
    parser.add_argument("--models", type=Path, default=Path("../var/models/price-2026-v1"))
    parser.add_argument(
        "--split", type=Path, default=Path("../var/models/corn-2026-v1/split-manifest.json")
    )
    args = parser.parse_args()
    print(run(args.cache, args.output, args.models, args.split))
