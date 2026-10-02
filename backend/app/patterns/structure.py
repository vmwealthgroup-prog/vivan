"""
VM ALGO — Market Structure Engine
====================================
Swing points, HH/HL/LH/LL sequencing, Break of Structure (BOS), Change of
Character (CHoCH), Fair Value Gaps (FVG), liquidity sweeps, and a simplified
order-block detector.

IMPORTANT — confirmation lag, not look-ahead:
A swing high/low at bar i can only be *known* once `lookahead` bars after it
have printed (that's the definition of a local extreme). Every function here
exposes a `confirmed_idx` alongside the swing's own index, and every
downstream consumer (BOS/CHoCH, backtester, signal engine) must only act on
a swing once bar `confirmed_idx` has closed. This is standard practice
(the same lag exists in a live chart drawing swing markers) and is NOT
look-ahead bias, provided callers respect confirmed_idx. The backtester in
backtest/backtester.py does this correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, lookback: int = 3, lookahead: int = 3) -> pd.DataFrame:
    """
    Returns a DataFrame indexed like df with:
      swing_high (bool), swing_low (bool), confirmed_idx (int, positional index
      into df at which the swing becomes known — always > the swing's own
      positional index).
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    confirmed_idx = np.full(n, -1, dtype=int)

    for i in range(lookback, n - lookahead):
        window_h = high[i - lookback:i + lookahead + 1]
        window_l = low[i - lookback:i + lookahead + 1]
        if high[i] == window_h.max() and np.sum(window_h == window_h.max()) == 1:
            swing_high[i] = True
            confirmed_idx[i] = i + lookahead
        if low[i] == window_l.min() and np.sum(window_l == window_l.min()) == 1:
            swing_low[i] = True
            confirmed_idx[i] = max(confirmed_idx[i], i + lookahead)

    return pd.DataFrame(
        {"swing_high": swing_high, "swing_low": swing_low, "confirmed_idx": confirmed_idx},
        index=df.index,
    )


class SwingLabel(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


def label_swing_sequence(df: pd.DataFrame, swings: pd.DataFrame) -> pd.DataFrame:
    """
    Labels each confirmed swing high as HH/LH relative to the prior swing high,
    and each confirmed swing low as HL/LL relative to the prior swing low.
    Returns a frame with one row per swing event, in confirmation order:
    columns = idx (positional), kind ('high'/'low'), price, label, confirmed_idx.
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    events = []
    for i in range(n):
        if swings["swing_high"].iat[i]:
            events.append({"idx": i, "kind": "high", "price": high[i],
                            "confirmed_idx": int(swings["confirmed_idx"].iat[i])})
        if swings["swing_low"].iat[i]:
            events.append({"idx": i, "kind": "low", "price": low[i],
                            "confirmed_idx": int(swings["confirmed_idx"].iat[i])})
    events.sort(key=lambda e: e["confirmed_idx"])

    last_high = None
    last_low = None
    labeled = []
    for e in events:
        if e["kind"] == "high":
            label = None
            if last_high is not None:
                label = SwingLabel.HH if e["price"] > last_high else SwingLabel.LH
            last_high = e["price"]
        else:
            label = None
            if last_low is not None:
                label = SwingLabel.HL if e["price"] > last_low else SwingLabel.LL
            last_low = e["price"]
        labeled.append({**e, "label": label.value if label else None})

    return pd.DataFrame(labeled)


@dataclass
class StructureEvent:
    idx: int              # positional index of the bar that triggered the break
    kind: str              # "BOS_BULL" | "BOS_BEAR" | "CHOCH_BULL" | "CHOCH_BEAR"
    level: float           # the swing level that was broken
    price: float            # close price of the break bar


def bos_choch(df: pd.DataFrame, swings: pd.DataFrame) -> list[StructureEvent]:
    """
    Walks bar-by-bar. Maintains the most recent CONFIRMED swing high/low and a
    running trend state. A close beyond the most recent confirmed swing high:
      - BOS_BULL  if trend was already up (continuation)
      - CHOCH_BULL if trend was down (first reversal signal)
    Mirrored for closes beyond the most recent confirmed swing low.
    Only ever looks at swings whose confirmed_idx <= current bar.
    """
    n = len(df)
    close = df["close"].to_numpy()

    pending = []  # (idx, kind, price, confirmed_idx) not yet confirmed
    last_confirmed_high = None
    last_confirmed_low = None
    trend = None  # "up" | "down" | None
    events: list[StructureEvent] = []

    high_flags = swings["swing_high"].to_numpy()
    low_flags = swings["swing_low"].to_numpy()
    conf_idx = swings["confirmed_idx"].to_numpy()
    high_px = df["high"].to_numpy()
    low_px = df["low"].to_numpy()

    for i in range(n):
        if high_flags[i]:
            pending.append((i, "high", high_px[i], conf_idx[i]))
        if low_flags[i]:
            pending.append((i, "low", low_px[i], conf_idx[i]))

        still_pending = []
        for (sidx, kind, price, cidx) in pending:
            if cidx <= i:
                if kind == "high":
                    last_confirmed_high = price
                else:
                    last_confirmed_low = price
            else:
                still_pending.append((sidx, kind, price, cidx))
        pending = still_pending

        if last_confirmed_high is not None and close[i] > last_confirmed_high:
            kind = "BOS_BULL" if trend == "up" else "CHOCH_BULL"
            events.append(StructureEvent(i, kind, last_confirmed_high, close[i]))
            trend = "up"
            last_confirmed_high = None  # require a fresh swing before signalling again
        elif last_confirmed_low is not None and close[i] < last_confirmed_low:
            kind = "BOS_BEAR" if trend == "down" else "CHOCH_BEAR"
            events.append(StructureEvent(i, kind, last_confirmed_low, close[i]))
            trend = "down"
            last_confirmed_low = None

    return events


def fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    3-candle imbalance. Bullish FVG confirmed at bar i (comparing bars i-2, i-1, i):
      low[i] > high[i-2]  -> gap between candle[i-2].high and candle[i].low
    Bearish FVG: high[i] < low[i-2].
    Returns bool columns bullish_fvg, bearish_fvg, gap_top, gap_bottom (aligned to df.index).
    """
    high, low = df["high"], df["low"]
    bullish = low > high.shift(2)
    bearish = high < low.shift(2)
    gap_top = np.where(bullish, low, np.where(bearish, low.shift(2), np.nan))
    gap_bottom = np.where(bullish, high.shift(2), np.where(bearish, high, np.nan))
    return pd.DataFrame({
        "bullish_fvg": bullish.fillna(False),
        "bearish_fvg": bearish.fillna(False),
        "gap_top": gap_top,
        "gap_bottom": gap_bottom,
    }, index=df.index)


def liquidity_sweep(df: pd.DataFrame, swings: pd.DataFrame, wick_min_pct: float = 0.3) -> pd.DataFrame:
    """
    Flags a bar as a liquidity sweep if it pierces a prior confirmed swing
    high/low with its wick but closes back on the other side — a classic
    stop-hunt / liquidity grab.
    wick_min_pct: the piercing wick must be at least this fraction of the bar's range.
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    rng = np.maximum(high - low, 1e-9)

    sweep_high = np.zeros(n, dtype=bool)
    sweep_low = np.zeros(n, dtype=bool)

    last_confirmed_high = None
    last_confirmed_low = None
    high_flags = swings["swing_high"].to_numpy()
    low_flags = swings["swing_low"].to_numpy()
    conf_idx = swings["confirmed_idx"].to_numpy()
    high_px = df["high"].to_numpy()
    low_px = df["low"].to_numpy()
    pending = []

    for i in range(n):
        if high_flags[i]:
            pending.append((i, "high", high_px[i], conf_idx[i]))
        if low_flags[i]:
            pending.append((i, "low", low_px[i], conf_idx[i]))
        still_pending = []
        for (sidx, kind, price, cidx) in pending:
            if cidx <= i:
                if kind == "high":
                    last_confirmed_high = price
                else:
                    last_confirmed_low = price
            else:
                still_pending.append((sidx, kind, price, cidx))
        pending = still_pending

        if last_confirmed_high is not None and high[i] > last_confirmed_high and close[i] < last_confirmed_high:
            upper_wick = high[i] - max(open_[i], close[i])
            if upper_wick / rng[i] >= wick_min_pct:
                sweep_high[i] = True
        if last_confirmed_low is not None and low[i] < last_confirmed_low and close[i] > last_confirmed_low:
            lower_wick = min(open_[i], close[i]) - low[i]
            if lower_wick / rng[i] >= wick_min_pct:
                sweep_low[i] = True

    return pd.DataFrame({"sweep_high": sweep_high, "sweep_low": sweep_low}, index=df.index)


def order_blocks(df: pd.DataFrame, structure_events: list[StructureEvent], lookback: int = 5) -> pd.DataFrame:
    """
    Simplified order-block detector: for each BOS/CHOCH event, walk backward
    up to `lookback` bars from the break bar and find the last opposite-colored
    candle before the impulsive move. That candle's high/low is the order block zone.
    Returns a DataFrame: event_idx, ob_idx, kind (demand/supply), zone_top, zone_bottom.
    """
    rows = []
    open_ = df["open"].to_numpy()
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    for ev in structure_events:
        bullish_break = ev.kind in ("BOS_BULL", "CHOCH_BULL")
        start = max(0, ev.idx - lookback)
        ob_idx = None
        for j in range(ev.idx - 1, start - 1, -1):
            is_down = close[j] < open_[j]
            is_up = close[j] > open_[j]
            if bullish_break and is_down:
                ob_idx = j
                break
            if not bullish_break and is_up:
                ob_idx = j
                break
        if ob_idx is not None:
            rows.append({
                "event_idx": ev.idx,
                "ob_idx": ob_idx,
                "kind": "demand" if bullish_break else "supply",
                "zone_top": float(high[ob_idx]),
                "zone_bottom": float(low[ob_idx]),
            })
    return pd.DataFrame(rows)


def recent_support_resistance(swings: pd.DataFrame, df: pd.DataFrame, lookback_bars: int = 100,
                                as_of_idx: int | None = None) -> dict:
    """
    Cheap S/R estimate: nearest confirmed swing high above and swing low below
    the current close, within the last `lookback_bars`, as of `as_of_idx`
    (defaults to the last bar). Only considers swings already confirmed by as_of_idx.
    """
    n = len(df)
    if as_of_idx is None:
        as_of_idx = n - 1
    start = max(0, as_of_idx - lookback_bars)
    current_close = df["close"].iat[as_of_idx]

    window = swings.iloc[start:as_of_idx + 1]
    confirmed = window[window["confirmed_idx"] <= as_of_idx]

    resistances = df["high"].iloc[start:as_of_idx + 1][confirmed["swing_high"]]
    supports = df["low"].iloc[start:as_of_idx + 1][confirmed["swing_low"]]

    resistance_above = resistances[resistances > current_close]
    support_below = supports[supports < current_close]

    return {
        "resistance": float(resistance_above.min()) if len(resistance_above) else None,
        "support": float(support_below.max()) if len(support_below) else None,
    }
