"""Deterministic historical block scenarios with as-of data only."""

import numpy as np


def historical_prediction(row, seed: int = 42, scenarios: int = 512, block: int = 5) -> dict:
    returns = np.asarray(row.history_returns)
    if len(returns) < block:
        raise ValueError("Insufficient historical return block")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(returns) - block + 1, size=(scenarios, 4))
    simulated = np.concatenate(
        [returns[starts[:, j, None] + np.arange(block)] for j in range(4)], axis=1
    )
    prices = row.settlement * np.exp(np.cumsum(simulated, axis=1))
    losses = np.round(np.maximum(row.strike - prices.mean(axis=1), 0) * row.quantity, 2)
    positive = losses[losses > 0]
    return {
        "trigger_probability": float(np.mean(losses > 0)),
        "conditional_mean_payout": float(positive.mean()) if len(positive) else None,
        "expected_payout": float(losses.mean()),
        "p90_payout": None,
        "p90_status": "unvalidated",
    }
