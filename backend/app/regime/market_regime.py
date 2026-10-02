"""
VM ALGO — Market Regime Detection
====================================
Classifies each bar into a trend regime and a volatility regime using only
indicators already computed up to and including that bar (no look-ahead).

Trend regime (via ADX + EMA stack + Supertrend direction):
  TRENDING_UP / TRENDING_DOWN / RANGING

Volatility regime (via ATR relative to its own rolling median, and
Bollinger Bandwidth percentile):
  HIGH / NORMAL / LOW

The signal engine uses this to decide which strategies/indicators to weight
more heavily (e.g. trend-following signals get more weight in a trending
regime; mean-reversion signals get more weight in a ranging regime).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ADX_TREND_THRESHOLD = 22.0
ATR_LOOKBACK = 100
BANDWIDTH_LOOKBACK = 100


def classify_trend(indicator_df: pd.DataFrame) -> pd.Series:
    required = {"adx_14", "plus_di_14", "minus_di_14", "ema_20", "ema_50", "supertrend_dir"}
    missing = required - set(indicator_df.columns)
    if missing:
        raise ValueError(f"classify_trend requires columns {missing} — run indicators.compute_all first")

    adx_trending = indicator_df["adx_14"] >= ADX_TREND_THRESHOLD
    di_bull = indicator_df["plus_di_14"] > indicator_df["minus_di_14"]
    ema_bull = indicator_df["ema_20"] > indicator_df["ema_50"]
    st_bull = indicator_df["supertrend_dir"] > 0

    bull_votes = di_bull.astype(int) + ema_bull.astype(int) + st_bull.astype(int)
    bear_votes = (~di_bull).astype(int) + (~ema_bull).astype(int) + (~st_bull).astype(int)

    regime = pd.Series("RANGING", index=indicator_df.index)
    regime = regime.where(~(adx_trending & (bull_votes >= 2)), "TRENDING_UP")
    regime = regime.where(~(adx_trending & (bear_votes >= 2)), "TRENDING_DOWN")
    return regime


def classify_volatility(indicator_df: pd.DataFrame) -> pd.Series:
    required = {"atr_14", "bb_bandwidth"} if "bb_bandwidth" in indicator_df.columns else {"atr_14"}
    if "atr_14" not in indicator_df.columns:
        raise ValueError("classify_volatility requires atr_14 — run indicators.compute_all first")

    atr_median = indicator_df["atr_14"].rolling(ATR_LOOKBACK, min_periods=20).median()
    ratio = indicator_df["atr_14"] / atr_median.replace(0, np.nan)

    regime = pd.Series("NORMAL", index=indicator_df.index)
    regime = regime.where(ratio <= 1.3, "HIGH")
    regime = regime.where(ratio >= 0.7, "LOW")
    return regime


def classify(indicator_df: pd.DataFrame) -> pd.DataFrame:
    trend = classify_trend(indicator_df)
    vol = classify_volatility(indicator_df)
    return pd.DataFrame({"trend_regime": trend, "volatility_regime": vol}, index=indicator_df.index)
