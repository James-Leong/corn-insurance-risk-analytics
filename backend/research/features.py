"""Strict as-of features: no fill, no roll-over series, no earlier history."""

import numpy as np
import pandas as pd

START = "2025-12-31"
END = "2026-10-23"
LOOKBACK = 20
HORIZON = 20
FEATURES = ["return_5", "return_19", "volatility_19", "ma_ratio", "strike_ratio"]


def prepare_market(market: pd.DataFrame, calendar: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = market.copy()
    frame["tradeDate"] = pd.to_datetime(frame.tradeDate).dt.strftime("%Y-%m-%d")
    if not frame.tradeDate.between(START, END).all():
        raise ValueError("Market data outside frozen 2025-12-31..2026-10-23 range")
    frame["ticker"] = frame.ticker.astype(str)
    if not frame.ticker.str.fullmatch(r"c\d{4}").all():
        raise ValueError("Only individual corn contracts cYYMM are allowed")
    if frame.duplicated(["ticker", "tradeDate"]).any():
        raise ValueError("Duplicate contract/date rows")
    frame["settlePrice"] = pd.to_numeric(frame.settlePrice, errors="raise")
    if not (np.isfinite(frame.settlePrice) & (frame.settlePrice > 0)).all():
        raise ValueError("Invalid settlement; close prices must not silently substitute")
    cal = calendar.copy()
    cal["calendarDate"] = pd.to_datetime(cal.calendarDate).dt.strftime("%Y-%m-%d")
    dates = sorted(
        cal.loc[
            (cal.isOpen.astype(int) == 1) & cal.calendarDate.between(START, END), "calendarDate"
        ].unique()
    )
    if not set(frame.tradeDate).issubset(dates):
        raise ValueError("Market dates absent from exchange open-day calendar")
    return frame.sort_values(["ticker", "tradeDate"]), dates
