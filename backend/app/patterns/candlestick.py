"""
VM ALGO — Candlestick Pattern Detection
=========================================
Each detector returns a boolean pandas Series aligned to the input index:
True on the bar where the pattern completes. Multi-bar patterns (engulfing,
morning/evening star, three soldiers/crows, harami) only look backward
(shift(1), shift(2)) — never forward — so these are safe inside a
bar-by-bar backtest loop.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).replace(0, np.nan)


def _upper_wick(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df[["open", "close"]].max(axis=1)


def _lower_wick(df: pd.DataFrame) -> pd.Series:
    return df[["open", "close"]].min(axis=1) - df["low"]


def is_bullish(df: pd.DataFrame) -> pd.Series:
    return df["close"] > df["open"]


def is_bearish(df: pd.DataFrame) -> pd.Series:
    return df["close"] < df["open"]


def doji(df: pd.DataFrame, body_ratio: float = 0.1) -> pd.Series:
    return (_body(df) / _range(df)) <= body_ratio


def hammer(df: pd.DataFrame, wick_ratio: float = 2.0, upper_ratio: float = 0.3) -> pd.Series:
    body = _body(df)
    lower = _lower_wick(df)
    upper = _upper_wick(df)
    return (lower >= wick_ratio * body.replace(0, np.nan)) & (upper <= upper_ratio * body.replace(0, np.nan).fillna(_range(df)))


def shooting_star(df: pd.DataFrame, wick_ratio: float = 2.0, lower_ratio: float = 0.3) -> pd.Series:
    body = _body(df)
    upper = _upper_wick(df)
    lower = _lower_wick(df)
    return (upper >= wick_ratio * body.replace(0, np.nan)) & (lower <= lower_ratio * body.replace(0, np.nan).fillna(_range(df)))


def marubozu(df: pd.DataFrame, wick_tolerance: float = 0.03) -> pd.Series:
    rng = _range(df)
    return ((_upper_wick(df) / rng) <= wick_tolerance) & ((_lower_wick(df) / rng) <= wick_tolerance)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bear = is_bearish(df).shift(1)
    curr_bull = is_bullish(df)
    engulfs = (df["open"] <= df["close"].shift(1)) & (df["close"] >= df["open"].shift(1))
    return prev_bear.fillna(False) & curr_bull & engulfs


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bull = is_bullish(df).shift(1)
    curr_bear = is_bearish(df)
    engulfs = (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))
    return prev_bull.fillna(False) & curr_bear & engulfs


def bullish_harami(df: pd.DataFrame) -> pd.Series:
    prev_bear = is_bearish(df).shift(1)
    curr_bull = is_bullish(df)
    inside = (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))
    return prev_bear.fillna(False) & curr_bull & inside


def bearish_harami(df: pd.DataFrame) -> pd.Series:
    prev_bull = is_bullish(df).shift(1)
    curr_bear = is_bearish(df)
    inside = (df["open"] <= df["close"].shift(1)) & (df["close"] >= df["open"].shift(1))
    return prev_bull.fillna(False) & curr_bear & inside


def morning_star(df: pd.DataFrame, small_body_ratio: float = 0.35) -> pd.Series:
    b0 = is_bearish(df).shift(2).fillna(False)
    body0 = _body(df).shift(2)
    small_mid = (_body(df).shift(1) / _range(df).shift(1)) <= small_body_ratio
    bull_close = is_bullish(df)
    recovers = df["close"] >= (df["open"].shift(2) + df["close"].shift(2)) / 2
    return b0 & small_mid.fillna(False) & bull_close & recovers


def evening_star(df: pd.DataFrame, small_body_ratio: float = 0.35) -> pd.Series:
    b0 = is_bullish(df).shift(2).fillna(False)
    small_mid = (_body(df).shift(1) / _range(df).shift(1)) <= small_body_ratio
    bear_close = is_bearish(df)
    reverses = df["close"] <= (df["open"].shift(2) + df["close"].shift(2)) / 2
    return b0 & small_mid.fillna(False) & bear_close & reverses


def three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    bull = is_bullish(df)
    rising = (df["close"] > df["close"].shift(1)) & (df["close"].shift(1) > df["close"].shift(2))
    opens_within = (df["open"] > df["open"].shift(1)) & (df["open"].shift(1) > df["open"].shift(2))
    return bull & bull.shift(1).fillna(False) & bull.shift(2).fillna(False) & rising & opens_within


def three_black_crows(df: pd.DataFrame) -> pd.Series:
    bear = is_bearish(df)
    falling = (df["close"] < df["close"].shift(1)) & (df["close"].shift(1) < df["close"].shift(2))
    opens_within = (df["open"] < df["open"].shift(1)) & (df["open"].shift(1) < df["open"].shift(2))
    return bear & bear.shift(1).fillna(False) & bear.shift(2).fillna(False) & falling & opens_within


PATTERNS = {
    "doji": doji,
    "hammer": hammer,
    "shooting_star": shooting_star,
    "marubozu": marubozu,
    "bullish_engulfing": bullish_engulfing,
    "bearish_engulfing": bearish_engulfing,
    "bullish_harami": bullish_harami,
    "bearish_harami": bearish_harami,
    "morning_star": morning_star,
    "evening_star": evening_star,
    "three_white_soldiers": three_white_soldiers,
    "three_black_crows": three_black_crows,
}

BULLISH_PATTERNS = {
    "hammer", "bullish_engulfing", "bullish_harami", "morning_star", "three_white_soldiers",
}
BEARISH_PATTERNS = {
    "shooting_star", "bearish_engulfing", "bearish_harami", "evening_star", "three_black_crows",
}


def detect_all(df: pd.DataFrame) -> pd.DataFrame:
    """Returns a boolean DataFrame, one column per pattern, aligned to df.index."""
    return pd.DataFrame({name: fn(df).fillna(False) for name, fn in PATTERNS.items()}, index=df.index)


def active_patterns_at(flags_row: pd.Series) -> list[str]:
    return [name for name, val in flags_row.items() if bool(val)]
