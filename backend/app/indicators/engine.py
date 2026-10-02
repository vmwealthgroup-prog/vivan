"""
VM ALGO — Indicator Engine
===========================
Pure, vectorized technical indicator calculations over OHLCV data.

Design rules (per VM ALGO master spec):
  - No indicator is treated as a standalone trading signal here — this module
    only computes values. Confluence / weighting happens in signals/confluence.py.
  - No look-ahead: every function only uses data up to and including row `i`
    when producing the value at row `i`. Safe to use directly inside a
    bar-by-bar backtest loop.
  - Input: a pandas DataFrame with columns open, high, low, close, volume,
    indexed by datetime, ascending order (oldest first).

All functions return a pandas Series or DataFrame aligned to the input index.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV dataframe missing columns: {missing}")
    if len(df) == 0:
        raise ValueError("OHLCV dataframe is empty")


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-cumulative VWAP. Resets at the start of each calendar day."""
    _validate(df)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical * df["volume"]
    day_key = df.index.normalize() if isinstance(df.index, pd.DatetimeIndex) else pd.Series(
        np.zeros(len(df)), index=df.index
    )
    cum_tp_vol = tp_vol.groupby(day_key).cumsum()
    cum_vol = df["volume"].groupby(day_key).cumsum().replace(0, np.nan)
    return cum_tp_vol / cum_vol


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)  # no losses at all -> RSI 100
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # flat -> neutral
    return out


def stoch_rsi(series: pd.Series, rsi_length: int = 14, stoch_length: int = 14,
              smooth_k: int = 3, smooth_d: int = 3) -> pd.DataFrame:
    r = rsi(series, rsi_length)
    lowest = r.rolling(stoch_length, min_periods=stoch_length).min()
    highest = r.rolling(stoch_length, min_periods=stoch_length).max()
    raw_k = 100 * (r - lowest) / (highest - lowest).replace(0, np.nan)
    k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(smooth_d, min_periods=smooth_d).mean()
    return pd.DataFrame({"k": k, "d": d})


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def roc(series: pd.Series, length: int = 12) -> pd.Series:
    return 100 * (series - series.shift(length)) / series.shift(length)


def cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    _validate(df)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    sma_tp = typical.rolling(length, min_periods=length).mean()
    mean_dev = typical.rolling(length, min_periods=length).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (typical - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def true_range(df: pd.DataFrame) -> pd.Series:
    _validate(df)
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def bollinger_bands(series: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(series, length)
    std = series.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    percent_b = (series - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                          "bandwidth": bandwidth, "percent_b": percent_b})


def keltner_channels(df: pd.DataFrame, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df["close"], length)
    rng = atr(df, length)
    return pd.DataFrame({
        "mid": mid,
        "upper": mid + mult * rng,
        "lower": mid - mult * rng,
    })


def donchian_channels(df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
    upper = df["high"].rolling(length, min_periods=length).max()
    lower = df["low"].rolling(length, min_periods=length).min()
    mid = (upper + lower) / 2.0
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


# ---------------------------------------------------------------------------
# Trend strength / direction
# ---------------------------------------------------------------------------

def adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """Wilder's ADX / +DI / -DI."""
    _validate(df)
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    tr = true_range(df)
    atr_ = tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr_.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr_.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    return pd.DataFrame({"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di})


def supertrend(df: pd.DataFrame, length: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """
    Returns columns: value (the trailing stop line), direction (1 = bullish, -1 = bearish).
    Sequential/stateful — computed via an explicit loop (no look-ahead: each row only
    depends on rows <= i).
    """
    _validate(df)
    rng = atr(df, length)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + mult * rng
    lower_basic = hl2 - mult * rng

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st_value = np.full(n, np.nan)
    direction = np.full(n, np.nan)  # float, NaN until `start` — NOT 0, which isn't a valid direction

    close = df["close"].to_numpy()
    ub = upper_basic.to_numpy()
    lb = lower_basic.to_numpy()

    start = length  # first index with a valid ATR
    if start >= n:
        return pd.DataFrame({"value": st_value, "direction": direction}, index=df.index)

    final_upper[start] = ub[start]
    final_lower[start] = lb[start]
    direction[start] = 1 if close[start] > final_upper[start] else -1
    st_value[start] = final_lower[start] if direction[start] == 1 else final_upper[start]

    for i in range(start + 1, n):
        final_upper[i] = ub[i] if (ub[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = lb[i] if (lb[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]) else final_lower[i - 1]

        if direction[i - 1] == 1:
            direction[i] = -1 if close[i] < final_lower[i] else 1
        else:
            direction[i] = 1 if close[i] > final_upper[i] else -1

        st_value[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return pd.DataFrame({"value": st_value, "direction": direction}, index=df.index)


def ichimoku(df: pd.DataFrame, conversion: int = 9, base: int = 26,
             span_b_len: int = 52, displacement: int = 26) -> pd.DataFrame:
    high, low = df["high"], df["low"]
    conv = (high.rolling(conversion).max() + low.rolling(conversion).min()) / 2
    base_line = (high.rolling(base).max() + low.rolling(base).min()) / 2
    span_a = ((conv + base_line) / 2).shift(displacement)
    span_b = ((high.rolling(span_b_len).max() + low.rolling(span_b_len).min()) / 2).shift(displacement)
    lagging = df["close"].shift(-displacement)
    return pd.DataFrame({
        "conversion": conv, "base": base_line,
        "span_a": span_a, "span_b": span_b, "lagging": lagging,
    })


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def obv(df: pd.DataFrame) -> pd.Series:
    _validate(df)
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def cmf(df: pd.DataFrame, length: int = 20) -> pd.Series:
    _validate(df)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mfv = mfm * df["volume"]
    return mfv.rolling(length, min_periods=length).sum() / df["volume"].rolling(length, min_periods=length).sum()


def mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    _validate(df)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    raw_flow = typical * df["volume"]
    pos_flow = raw_flow.where(typical.diff() > 0, 0.0)
    neg_flow = raw_flow.where(typical.diff() < 0, 0.0)
    pos_sum = pos_flow.rolling(length, min_periods=length).sum()
    neg_sum = neg_flow.rolling(length, min_periods=length).sum()
    money_ratio = pos_sum / neg_sum.replace(0, np.nan)
    out = 100 - (100 / (1 + money_ratio))
    return out.where(neg_sum != 0, 100.0)


# ---------------------------------------------------------------------------
# Pivot points
# ---------------------------------------------------------------------------

def classic_pivot_points(prev_high: float, prev_low: float, prev_close: float) -> dict:
    pivot = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    r3 = prev_high + 2 * (pivot - prev_low)
    s3 = prev_low - 2 * (prev_high - pivot)
    return {"pivot": pivot, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}


# ---------------------------------------------------------------------------
# One-shot: compute the full indicator set used by the signal engine
# ---------------------------------------------------------------------------

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the standard indicator set and return it merged onto the input frame."""
    _validate(df)
    out = df.copy()

    for length in (9, 20, 50, 100, 200):
        out[f"ema_{length}"] = ema(df["close"], length)
    out["sma_20"] = sma(df["close"], 20)
    out["vwap"] = vwap(df)

    out["rsi_14"] = rsi(df["close"], 14)
    macd_df = macd(df["close"])
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]

    srsi = stoch_rsi(df["close"])
    out["stoch_rsi_k"] = srsi["k"]
    out["stoch_rsi_d"] = srsi["d"]

    out["cci_20"] = cci(df, 20)
    out["roc_12"] = roc(df["close"], 12)

    out["atr_14"] = atr(df, 14)
    bb = bollinger_bands(df["close"])
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bb["upper"], bb["mid"], bb["lower"]
    out["bb_percent_b"] = bb["percent_b"]

    adx_df = adx(df, 14)
    out["adx_14"] = adx_df["adx"]
    out["plus_di_14"] = adx_df["plus_di"]
    out["minus_di_14"] = adx_df["minus_di"]

    st = supertrend(df, 10, 3.0)
    out["supertrend"] = st["value"]
    out["supertrend_dir"] = st["direction"]

    donch = donchian_channels(df, 20)
    out["donchian_upper"], out["donchian_lower"] = donch["upper"], donch["lower"]

    out["obv"] = obv(df)
    out["cmf_20"] = cmf(df, 20)
    out["mfi_14"] = mfi(df, 14)

    return out
