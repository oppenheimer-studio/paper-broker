import pandas as pd

from paper_broker.domain.indicators import rel_vol_at, sma, wilder_atr


def test_wilder_atr_seed_and_smooth():
    high = pd.Series([10.0, 11, 12, 13, 14, 15, 16, 17])
    low = pd.Series([9.0, 10, 11, 12, 13, 14, 15, 16])
    close = pd.Series([9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5])
    atr = wilder_atr(high, low, close, period=3)
    assert atr.dropna().iloc[-1] > 0
    assert atr.dropna().shape[0] >= 1


def test_sma_min_periods():
    s = pd.Series([1.0, 2, 3, 4])
    out = sma(s, 3)
    assert out.iloc[0] == 1
    assert out.iloc[2] == 2


def test_rel_vol_at_excludes_today():
    value, n = rel_vol_at(20, [10, 10])
    assert n == 2
    assert value == 2.0
    assert rel_vol_at(10, [])[0] is None
