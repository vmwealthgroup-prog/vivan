"""
Smoke + correctness tests for the Phase-1 quant core. Run with:
    cd backend && python -m pytest app/tests/test_pipeline.py -v
or directly:
    cd backend && python app/tests/test_pipeline.py
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from app.indicators import engine as ind
from app.patterns import candlestick, structure as struct_mod
from app.regime import market_regime
from app.signals import confluence
from app.market_data.provider import SimulatedDataProvider
from app.risk.rms import RiskManager, RiskLimits, AccountState, OrderRequest, RiskDecision
from app.backtest.backtester import run_backtest


def make_data(symbol="NIFTY_TEST", bars=600):
    provider = SimulatedDataProvider(base_price=22000, annual_vol=0.15)
    return provider.get_historical(symbol, interval="5m", lookback_bars=bars).df


def test_indicators_sane_ranges():
    df = make_data()
    out = ind.compute_all(df)

    rsi_valid = out["rsi_14"].dropna()
    assert (rsi_valid >= 0).all() and (rsi_valid <= 100).all(), "RSI out of [0,100] bounds"

    mfi_valid = out["mfi_14"].dropna()
    assert (mfi_valid >= 0).all() and (mfi_valid <= 100).all(), "MFI out of [0,100] bounds"

    atr_valid = out["atr_14"].dropna()
    assert (atr_valid >= 0).all(), "ATR must be non-negative"

    bb_valid = out.dropna(subset=["bb_upper", "bb_lower"])
    assert (bb_valid["bb_upper"] >= bb_valid["bb_lower"]).all(), "Bollinger upper must be >= lower"

    st_valid = out["supertrend_dir"].dropna()
    assert set(st_valid.unique()).issubset({1, -1}), "Supertrend direction must be +/-1"
    print("[OK] indicator ranges sane")


def test_no_lookahead_indicators():
    """Truncating the dataframe must not change historical indicator values
    (aside from the last `warmup` rows near the truncation point, which is
    expected because rolling windows need bars on both... no: all indicators
    here are backward-only, so truncating the END must leave every earlier
    value byte-identical)."""
    df = make_data(bars=400)
    full = ind.compute_all(df)
    truncated = ind.compute_all(df.iloc[:300])

    compare_cols = ["ema_20", "rsi_14", "atr_14", "macd", "supertrend", "adx_14"]
    for col in compare_cols:
        a = full[col].iloc[:300].to_numpy()
        b = truncated[col].to_numpy()
        assert np.allclose(a, b, equal_nan=True), f"{col} changed after truncating future bars — look-ahead bug"
    print("[OK] no look-ahead in indicator engine (truncation-invariance test)")


def test_candlestick_patterns_run():
    df = make_data()
    flags = candlestick.detect_all(df)
    assert flags.shape[0] == len(df)
    assert flags.dtypes.apply(lambda d: d == bool).all()
    print(f"[OK] candlestick patterns computed — e.g. {int(flags['doji'].sum())} doji bars detected")


def test_market_structure():
    df = make_data(bars=500)
    swings = struct_mod.swing_points(df)
    assert swings["swing_high"].sum() > 0 and swings["swing_low"].sum() > 0

    events = struct_mod.bos_choch(df, swings)
    assert isinstance(events, list)

    fvgs = struct_mod.fair_value_gaps(df)
    assert fvgs.shape[0] == len(df)

    sweeps = struct_mod.liquidity_sweep(df, swings)
    assert sweeps.shape[0] == len(df)

    obs = struct_mod.order_blocks(df, events)
    print(f"[OK] structure: {len(events)} BOS/CHoCH events, {int(fvgs['bullish_fvg'].sum())} bullish FVGs, "
          f"{len(obs)} order blocks derived")


def test_regime_classification():
    df = make_data()
    enriched = ind.compute_all(df)
    regime = market_regime.classify(enriched)
    assert set(regime["trend_regime"].dropna().unique()).issubset({"TRENDING_UP", "TRENDING_DOWN", "RANGING"})
    assert set(regime["volatility_regime"].dropna().unique()).issubset({"HIGH", "NORMAL", "LOW"})
    print("[OK] regime classification produces valid labels")


def test_signal_engine_confidence_bounds():
    df = make_data(bars=400)
    enriched = ind.compute_all(df)
    swings = struct_mod.swing_points(df)
    events = struct_mod.bos_choch(df, swings)

    signals_emitted = 0
    for i in range(210, len(enriched)):
        sig = confluence.generate_signal(enriched, i, symbol="NIFTY_TEST", timeframe="5m",
                                          recent_structure_event=events[-1] if events else None)
        if sig is not None:
            signals_emitted += 1
            assert 0 <= sig.confidence <= 100
            assert sig.confidence >= confluence.MIN_CONFIDENCE_TO_SIGNAL
            assert sig.direction in ("LONG", "SHORT")
            assert sig.risk_reward > 0
    print(f"[OK] signal engine: {signals_emitted} signals emitted over {len(enriched) - 210} bars, "
          f"all confidence scores within bounds and above the emission threshold")


def test_risk_manager_position_sizing_and_kill_switch():
    rm = RiskManager(RiskLimits(max_risk_per_trade_pct=1.0, max_daily_loss_pct=2.0, max_drawdown_pct=5.0))
    account = AccountState(equity=100_000, equity_high_water_mark=100_000)

    qty = rm.position_size(account, entry=1000, stop_loss=990)
    assert qty == 100, f"expected 100 shares (1% of 100k / 10 risk-per-share), got {qty}"

    # Same tight stop (10 pts on a 1000 entry) — pure risk sizing wants 100
    # shares (100k notional = 100% of equity). The default 25% single-sector
    # cap is the binding constraint here (25k / 1000 = 25 shares), tighter
    # than the 50% total-exposure cap (50 shares) — validate_order must
    # return the smallest of the three, i.e. 25.
    order = OrderRequest(symbol="TEST", sector="IT", direction="LONG", entry=1000, stop_loss=990)
    import datetime
    weekday_market_hours = datetime.datetime(2026, 8, 24, 11, 0)  # a Monday, 11:00
    result = rm.validate_order(order, account, now=weekday_market_hours)
    assert result.decision == RiskDecision.APPROVED, result.reasons
    assert result.approved_quantity == 25, result.approved_quantity

    weekend = datetime.datetime(2026, 8, 22, 11, 0)  # a Saturday
    result_weekend = rm.validate_order(order, account, now=weekend)
    assert result_weekend.decision == RiskDecision.REJECTED

    drawn_down = AccountState(equity=94_000, equity_high_water_mark=100_000)
    engaged, reason = rm.check_kill_switch(drawn_down)
    assert engaged, "6% drawdown should trip a 5% max-drawdown kill switch"
    print("[OK] risk manager: position sizing, trading-hours gate, and drawdown kill switch all correct")


def test_full_backtest_runs():
    df = make_data(bars=800)
    report = run_backtest(df, symbol="NIFTY_TEST", timeframe="5m", initial_equity=100_000)
    d = report.to_dict()
    assert d["total_trades"] >= 0
    assert d["initial_equity"] == 100_000
    assert isinstance(d["trades"], list)
    print(f"[OK] full backtest ran: {d['total_trades']} trades, "
          f"final equity {d['final_equity']}, win rate {d['win_rate_pct']}%, "
          f"max drawdown {d['max_drawdown_pct']}%")
    return d


if __name__ == "__main__":
    tests = [
        test_indicators_sane_ranges,
        test_no_lookahead_indicators,
        test_candlestick_patterns_run,
        test_market_structure,
        test_regime_classification,
        test_signal_engine_confidence_bounds,
        test_risk_manager_position_sizing_and_kill_switch,
        test_full_backtest_runs,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} test groups passed.")
    sys.exit(1 if failed else 0)
