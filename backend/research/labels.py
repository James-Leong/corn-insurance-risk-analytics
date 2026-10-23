"""Frozen synthetic terms with observed future settlement labels, not claims."""

import numpy as np
import pandas as pd
from app.domain.insurance import PriceInsuranceScenario
from research.features import FEATURES, HORIZON, LOOKBACK, prepare_market


def payout(strike: float, settlement: float, quantity: float = 100.0) -> float:
    return float(PriceInsuranceScenario(quantity, strike, settlement).calculate()["gross_payout"])


def build_samples(market: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    frame, dates = prepare_market(market, calendar)
    rows = []
    for ticker, group in frame.groupby("ticker"):
        series = group.set_index("tradeDate").settlePrice.reindex(dates)
        for i in range(LOOKBACK - 1, len(dates) - HORIZON):
            past = series.iloc[i - LOOKBACK + 1 : i + 1].to_numpy(dtype=float)
            future = series.iloc[i + 1 : i + 1 + HORIZON].to_numpy(dtype=float)
            if not np.isfinite(np.concatenate([past, future])).all():
                continue  # fixed shared eligibility, before any method runs
            returns = np.diff(np.log(past))
            for ratio in (0.95, 1.0, 1.05):
                strike = round(float(past[-1] * ratio), 2)
                observed = float(future.mean())
                loss = payout(strike, observed)
                row = dict(
                    sample_id=f"{ticker}:{dates[i]}:{ratio}",
                    ticker=ticker,
                    as_of=dates[i],
                    label_available_at=dates[i + HORIZON],
                    observation_dates=dates[i + 1 : i + 1 + HORIZON],
                    settlement=float(past[-1]),
                    observation_mean=observed,
                    strike=strike,
                    quantity=100.0,
                    actual_payout=loss,
                    loss_ratio=loss / (strike * 100),
                    triggered=int(loss > 0),
                    return_5=float(past[-1] / past[-6] - 1),
                    return_19=float(past[-1] / past[0] - 1),
                    volatility_19=float(returns.std()),
                    ma_ratio=float(past[-1] / past.mean() - 1),
                    strike_ratio=ratio,
                    price_last=float(past[-1]),
                    price_ma20=float(past.mean()),
                    history_returns=returns.tolist(),
                )
                rows.append(row)
    columns = [
        "sample_id",
        "ticker",
        "as_of",
        "label_available_at",
        "actual_payout",
        "triggered",
        *FEATURES,
    ]
    result = pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)
    if len(result):
        result["weight"] = 1.0 / result.groupby("as_of").sample_id.transform("count")
    return result
