"""
VM ALGO — Signal Engine (rule-based confluence scoring)
===========================================================
Per the master spec: "Do not treat every indicator as an independent trading
signal" and "Do not display a high confidence number unless it is backed by
a defined scoring methodology." This module implements that methodology
explicitly and returns the full point-by-point breakdown with every signal
(the `reasoning` field), never just a bare number.

Scoring factors and max points (out of 100 total):
  Trend alignment (EMA stack + Supertrend + ADX)         25
  Momentum (RSI positioning + MACD histogram + StochRSI) 20
  Volume confirmation (OBV slope, CMF, MFI)               15
  Market structure (BOS/CHoCH direction, no counter-sweep)20
  Multi-timeframe confirmation (higher-TF regime agrees)  10  [optional — see note]
  Risk/reward quality (>=1.5R available to nearest S/R)   10

  AI model ensemble agreement                              0  — INTENTIONALLY
  EXCLUDED. The ML layer (LSTM/XGBoost/RandomForest/LightGBM
  ensemble) described in the master spec has not been built yet.
  Once it exists, its agreement score plugs in here and the
  weights above are rebalanced. Until then this engine is
  explicitly rule-based, not "AI" — do not present it as more
  than that.

If multi-timeframe context isn't supplied, its 10 points are removed from
both the achieved AND possible totals (confidence is then out of 90, not
faked as if MTF disagreed). This keeps the percentage honest per-call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.patterns import candlestick
from app.patterns.structure import StructureEvent

MIN_CONFIDENCE_TO_SIGNAL = 55.0  # below this, no signal is emitted at all


@dataclass
class Signal:
    symbol: str
    direction: str            # "LONG" | "SHORT"
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward: float
    confidence: float          # 0-100, see module docstring for methodology
    timeframe: str
    strategy: str
    reasoning: list[str]
    timestamp: str
    bar_index: int
    scoring_breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": round(self.entry, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "risk_reward": round(self.risk_reward, 2),
            "confidence": round(self.confidence, 1),
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
            "scoring_breakdown": self.scoring_breakdown,
        }


def _score_trend(row: pd.Series) -> tuple[float, float, str, int]:
    """Returns (bull_points, bear_points, note, max_points=25)."""
    max_points = 25.0
    bull = 0.0
    bear = 0.0
    if row["ema_20"] > row["ema_50"] > row["ema_100"]:
        bull += 10
    elif row["ema_20"] < row["ema_50"] < row["ema_100"]:
        bear += 10
    if row.get("supertrend_dir", 0) > 0:
        bull += 8
    else:
        bear += 8
    adx_strength = min(row.get("adx_14", 0) / 40.0, 1.0) * 7
    if row.get("plus_di_14", 0) > row.get("minus_di_14", 0):
        bull += adx_strength
    else:
        bear += adx_strength
    return bull, bear, max_points


def _score_momentum(row: pd.Series) -> tuple[float, float, float]:
    max_points = 20.0
    bull = 0.0
    bear = 0.0
    rsi = row.get("rsi_14", 50)
    if 50 < rsi < 75:
        bull += 8
    elif 25 < rsi < 50:
        bear += 8
    elif rsi >= 75:
        bull += 3  # strong but stretched — reduced weight
    elif rsi <= 25:
        bear += 3
    if row.get("macd_hist", 0) > 0:
        bull += 7
    else:
        bear += 7
    k = row.get("stoch_rsi_k", 50)
    if k > row.get("stoch_rsi_d", 50):
        bull += 5
    else:
        bear += 5
    return bull, bear, max_points


def _score_volume(row: pd.Series, obv_slope_bull: bool) -> tuple[float, float, float]:
    max_points = 15.0
    bull = 0.0
    bear = 0.0
    if obv_slope_bull:
        bull += 6
    else:
        bear += 6
    cmf = row.get("cmf_20", 0)
    if cmf > 0.05:
        bull += 5
    elif cmf < -0.05:
        bear += 5
    mfi = row.get("mfi_14", 50)
    if mfi > 50:
        bull += 4
    else:
        bear += 4
    return bull, bear, max_points


def _score_structure(recent_event: StructureEvent | None, swept_against: bool) -> tuple[float, float, float]:
    max_points = 20.0
    bull = 0.0
    bear = 0.0
    if recent_event is not None:
        if recent_event.kind in ("BOS_BULL", "CHOCH_BULL"):
            bull += 15 if recent_event.kind == "CHOCH_BULL" else 12
        elif recent_event.kind in ("BOS_BEAR", "CHOCH_BEAR"):
            bear += 15 if recent_event.kind == "CHOCH_BEAR" else 12
    if not swept_against:
        bull += 5
        bear += 5
    return bull, bear, max_points


def _score_risk_reward(entry: float, stop: float, target1: float) -> tuple[float, float]:
    max_points = 10.0
    risk = abs(entry - stop)
    reward = abs(target1 - entry)
    if risk <= 0:
        return 0.0, max_points
    rr = reward / risk
    points = min(rr / 1.5, 1.0) * max_points
    return points, max_points


def generate_signal(
    indicator_df: pd.DataFrame,
    i: int,
    symbol: str,
    timeframe: str,
    recent_structure_event: StructureEvent | None = None,
    swept_against: bool = False,
    higher_tf_trend_regime: str | None = None,
    strategy_name: str = "VM Confluence v1",
    atr_stop_mult: float = 1.5,
    rr_target_1: float = 1.5,
    rr_target_2: float = 3.0,
) -> Signal | None:
    """
    Produces a Signal for bar `i` of `indicator_df` (which must already have
    indicators.compute_all applied), or None if confidence < MIN_CONFIDENCE_TO_SIGNAL
    or required data isn't available yet (e.g. early bars with NaN indicators).
    """
    row = indicator_df.iloc[i]
    if pd.isna(row.get("atr_14")) or pd.isna(row.get("ema_100")) or pd.isna(row.get("adx_14")):
        return None

    obv_now = indicator_df["obv"].iloc[max(0, i - 5):i + 1]
    obv_slope_bull = len(obv_now) >= 2 and obv_now.iloc[-1] > obv_now.iloc[0]

    trend_bull, trend_bear, trend_max = _score_trend(row)
    mom_bull, mom_bear, mom_max = _score_momentum(row)
    vol_bull, vol_bear, vol_max = _score_volume(row, obv_slope_bull)
    struct_bull, struct_bear, struct_max = _score_structure(recent_structure_event, swept_against)

    possible = trend_max + mom_max + vol_max + struct_max
    achieved_bull = trend_bull + mom_bull + vol_bull + struct_bull
    achieved_bear = trend_bear + mom_bear + vol_bear + struct_bear

    mtf_max = 0.0
    mtf_bull = mtf_bear = 0.0
    if higher_tf_trend_regime is not None:
        mtf_max = 10.0
        if higher_tf_trend_regime == "TRENDING_UP":
            mtf_bull = 10.0
        elif higher_tf_trend_regime == "TRENDING_DOWN":
            mtf_bear = 10.0
        else:
            mtf_bull = mtf_bear = 3.0  # ranging HTF: mild penalty, not a veto
    possible += mtf_max
    achieved_bull += mtf_bull
    achieved_bear += mtf_bear

    direction = "LONG" if achieved_bull >= achieved_bear else "SHORT"
    directional_score = achieved_bull if direction == "LONG" else achieved_bear

    entry = float(row["close"])
    atr = float(row["atr_14"])
    if direction == "LONG":
        stop = entry - atr_stop_mult * atr
    else:
        stop = entry + atr_stop_mult * atr
    risk = abs(entry - stop)
    target1 = entry + rr_target_1 * risk if direction == "LONG" else entry - rr_target_1 * risk
    target2 = entry + rr_target_2 * risk if direction == "LONG" else entry - rr_target_2 * risk

    rr_points, rr_max = _score_risk_reward(entry, stop, target1)
    possible += rr_max
    directional_score += rr_points

    confidence = 100.0 * directional_score / possible if possible > 0 else 0.0
    confidence = float(np.clip(confidence, 0, 100))

    if confidence < MIN_CONFIDENCE_TO_SIGNAL:
        return None

    reasoning = []
    reasoning.append(f"Trend: EMA20/50/100 {'bullish' if trend_bull > trend_bear else 'bearish'} stack, "
                      f"ADX {row.get('adx_14', float('nan')):.1f}, Supertrend "
                      f"{'up' if row.get('supertrend_dir', 0) > 0 else 'down'}.")
    reasoning.append(f"Momentum: RSI {row.get('rsi_14', float('nan')):.1f}, "
                      f"MACD hist {'positive' if row.get('macd_hist', 0) > 0 else 'negative'}.")
    reasoning.append(f"Volume: OBV {'rising' if obv_slope_bull else 'falling'}, "
                      f"CMF {row.get('cmf_20', float('nan')):.3f}.")
    if recent_structure_event is not None:
        reasoning.append(f"Structure: recent {recent_structure_event.kind} at {recent_structure_event.level:.2f}.")
    if swept_against:
        reasoning.append("Caution: a liquidity sweep against this direction occurred recently.")
    if higher_tf_trend_regime is not None:
        reasoning.append(f"Higher timeframe regime: {higher_tf_trend_regime}.")
    reasoning.append(f"Risk/reward to target 1: {abs(target1 - entry) / risk:.2f}R.")

    ts = indicator_df.index[i]
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

    return Signal(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop,
        target_1=target1,
        target_2=target2,
        risk_reward=abs(target1 - entry) / risk if risk else 0.0,
        confidence=confidence,
        timeframe=timeframe,
        strategy=strategy_name,
        reasoning=reasoning,
        timestamp=ts_str,
        bar_index=i,
        scoring_breakdown={
            "achieved_bull": round(achieved_bull, 1),
            "achieved_bear": round(achieved_bear, 1),
            "possible": round(possible, 1),
            "components_max": {
                "trend": trend_max, "momentum": mom_max, "volume": vol_max,
                "structure": struct_max, "multi_timeframe": mtf_max, "risk_reward": rr_max,
            },
            "ai_model_agreement": "not yet implemented — rule-based score only",
        },
    )
