from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Wilder ATR. First value is SMA of TR over `period` bars that have a prior close."""
    if period < 1:
        raise ValueError("period must be >= 1")
    tr = true_range(high, low, close)
    atr = pd.Series(index=tr.index, dtype="float64")
    values = tr.to_numpy(dtype="float64")
    out = np.full(len(values), np.nan)
    seed_end = None
    acc = 0.0
    counted = 0
    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        counted += 1
        acc += v
        if counted == period:
            out[i] = acc / period
            seed_end = i
            break
    if seed_end is None:
        return atr
    prev = out[seed_end]
    for i in range(seed_end + 1, len(values)):
        v = values[i]
        if np.isnan(v):
            out[i] = prev
            continue
        prev = (prev * (period - 1) + v) / period
        out[i] = prev
    atr.iloc[:] = out
    return atr


def sma(series: pd.Series, period: int) -> pd.Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    return series.rolling(period, min_periods=1).mean()


def rel_vol_at(today_volume: float | None, prior_volumes: list[float]) -> tuple[float | None, int]:
    """today / mean(prior). Prior only; today is not in the denominator."""
    clean = [v for v in prior_volumes if v is not None and v > 0]
    if today_volume is None or today_volume < 0 or not clean:
        return None, len(clean)
    return today_volume / (sum(clean) / len(clean)), len(clean)
