"""
VM ALGO — Backtesting Engine
===============================
Bar-by-bar simulation. Rules followed to avoid the biases the master spec
explicitly calls out:

  Look-ahead bias   — a signal generated using bar i's CLOSE is only ever
                       filled at bar i+1's OPEN, never at bar i's own close.
                       Every indicator/structure function it calls is itself
                       backward-looking only (see indicators/engine.py and
                       patterns/structure.py docstrings).
  Survivorship bias — out of scope for a single-symbol backtest; when this
                       engine is extended to a universe/portfolio backtest,
                       the symbol list must be the point-in-time index
                       constituents, not today's constituents applied
                       retroactively. Flagged in ROADMAP, not solved here.
  Data leakage       — the engine never fits anything on the full series;
                       there is no parameter fitting in this rule-based
                       engine at all (confluence weights are fixed constants).
  Overfitting         — walk-forward / Monte Carlo harnesses are a follow-up
                       phase (see doc/backtest_roadmap note in run_backtest
                       output). This module is the execution core they'll sit on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.indicators import engine as ind
from app.patterns import structure as struct_mod
from app.regime import market_regime
from app.signals import confluence
from app.risk.rms import RiskManager, RiskLimits, AccountState, OrderRequest, RiskDecision


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_idx: int
    entry_price: float
    exit_idx: int | None = None
    exit_price: float | None = None
    stop_loss: float = 0.0
    target_1: float = 0.0
    quantity: int = 0
    exit_reason: str | None = None   # "TARGET_1" | "STOP" | "END_OF_DATA"
    pnl: float = 0.0
    confidence: float = 0.0


@dataclass
class BacktestReport:
    trades: list[Trade]
    equity_curve: list[float]
    initial_equity: float
    final_equity: float
    total_trades: int
    win_rate: float
    profit_factor: float
    average_win: float
    average_loss: float
    max_drawdown_pct: float
    sharpe_like: float
    total_return_pct: float

    def to_dict(self) -> dict:
        return {
            "initial_equity": round(self.initial_equity, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "profit_factor": round(self.profit_factor, 2) if np.isfinite(self.profit_factor) else None,
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_like": round(self.sharpe_like, 2),
            "trades": [
                {
                    "symbol": t.symbol, "direction": t.direction,
                    "entry_idx": t.entry_idx, "entry_price": round(t.entry_price, 2),
                    "exit_idx": t.exit_idx,
                    "exit_price": round(t.exit_price, 2) if t.exit_price is not None else None,
                    "quantity": t.quantity, "exit_reason": t.exit_reason,
                    "pnl": round(t.pnl, 2), "confidence": round(t.confidence, 1),
                }
                for t in self.trades
            ],
            "notes": [
                "Rule-based confluence engine only — no ML ensemble yet (see signals/confluence.py docstring).",
                "Walk-forward and Monte Carlo robustness testing are a follow-up phase, not run here.",
                "Commission/slippage are configurable inputs (see run_backtest kwargs); defaults are conservative estimates, not broker-verified.",
            ],
        }


def run_backtest(
    raw_df: pd.DataFrame,
    symbol: str,
    timeframe: str = "5m",
    initial_equity: float = 100_000.0,
    risk_limits: RiskLimits | None = None,
    commission_per_trade: float = 20.0,
    slippage_pct: float = 0.02,
    sector: str = "UNSPECIFIED",
) -> BacktestReport:
    df = ind.compute_all(raw_df)
    swings = struct_mod.swing_points(raw_df, lookback=3, lookahead=3)
    structure_events = struct_mod.bos_choch(raw_df, swings)
    sweeps = struct_mod.liquidity_sweep(raw_df, swings)
    regime_df = market_regime.classify(df)

    events_by_idx: dict[int, struct_mod.StructureEvent] = {}
    last_event: struct_mod.StructureEvent | None = None
    events_sorted = sorted(structure_events, key=lambda e: e.idx)
    event_pointer = 0

    rm = RiskManager(risk_limits)
    account = AccountState(equity=initial_equity, equity_high_water_mark=initial_equity)

    trades: list[Trade] = []
    equity_curve: list[float] = [initial_equity]
    open_trade: Trade | None = None

    n = len(df)
    for i in range(n):
        # advance "most recent structure event known as of bar i"
        while event_pointer < len(events_sorted) and events_sorted[event_pointer].idx <= i:
            last_event = events_sorted[event_pointer]
            event_pointer += 1

        if open_trade is not None:
            high = df["high"].iat[i]
            low = df["low"].iat[i]
            exit_price = None
            reason = None
            if open_trade.direction == "LONG":
                if low <= open_trade.stop_loss:
                    exit_price, reason = open_trade.stop_loss, "STOP"
                elif high >= open_trade.target_1:
                    exit_price, reason = open_trade.target_1, "TARGET_1"
            else:
                if high >= open_trade.stop_loss:
                    exit_price, reason = open_trade.stop_loss, "STOP"
                elif low <= open_trade.target_1:
                    exit_price, reason = open_trade.target_1, "TARGET_1"

            if exit_price is not None:
                fill = exit_price * (1 - slippage_pct / 100.0 if open_trade.direction == "LONG" else 1 + slippage_pct / 100.0)
                gross = (fill - open_trade.entry_price) * open_trade.quantity if open_trade.direction == "LONG" \
                    else (open_trade.entry_price - fill) * open_trade.quantity
                pnl = gross - commission_per_trade
                open_trade.exit_idx = i
                open_trade.exit_price = fill
                open_trade.exit_reason = reason
                open_trade.pnl = pnl
                account.equity += pnl
                account.realized_pnl_today += pnl
                account.equity_high_water_mark = max(account.equity_high_water_mark, account.equity)
                account.open_positions = []
                trades.append(open_trade)
                open_trade = None

        elif i + 1 < n:  # only look for a new entry if we can fill on the NEXT bar's open
            sig = confluence.generate_signal(
                df, i, symbol=symbol, timeframe=timeframe,
                recent_structure_event=last_event,
                swept_against=bool(sweeps["sweep_high"].iat[i] or sweeps["sweep_low"].iat[i]),
            )
            if sig is not None:
                order = OrderRequest(symbol=symbol, sector=sector, direction=sig.direction,
                                      entry=sig.entry, stop_loss=sig.stop_loss)
                # Use the bar's own session timestamp for the trading-hours gate, not
                # wall-clock "now" — a backtest replays history, it doesn't run live.
                result = rm.validate_order(order, account, now=df.index[i])
                if result.decision == RiskDecision.APPROVED and result.approved_quantity > 0:
                    fill_open = df["open"].iat[i + 1]
                    open_trade = Trade(
                        symbol=symbol, direction=sig.direction, entry_idx=i + 1,
                        entry_price=fill_open, stop_loss=sig.stop_loss, target_1=sig.target_1,
                        quantity=result.approved_quantity, confidence=sig.confidence,
                    )
                    account.open_positions = [{"symbol": symbol, "sector": sector,
                                                "notional": fill_open * result.approved_quantity}]
                    account.trades_today += 1

        engaged, _ = rm.check_kill_switch(account)
        if engaged:
            equity_curve.append(account.equity)
            break

        equity_curve.append(account.equity)

    if open_trade is not None:
        last_close = df["close"].iat[-1]
        gross = (last_close - open_trade.entry_price) * open_trade.quantity if open_trade.direction == "LONG" \
            else (open_trade.entry_price - last_close) * open_trade.quantity
        open_trade.exit_idx = n - 1
        open_trade.exit_price = last_close
        open_trade.exit_reason = "END_OF_DATA"
        open_trade.pnl = gross - commission_per_trade
        account.equity += open_trade.pnl
        trades.append(open_trade)
        equity_curve.append(account.equity)

    return _build_report(trades, equity_curve, initial_equity)


def _build_report(trades: list[Trade], equity_curve: list[float], initial_equity: float) -> BacktestReport:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    total_trades = len(trades)
    win_rate = len(wins) / total_trades if total_trades else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0

    curve = np.array(equity_curve)
    running_max = np.maximum.accumulate(curve)
    drawdowns = np.where(running_max > 0, (running_max - curve) / running_max, 0.0)
    max_dd_pct = float(drawdowns.max() * 100) if len(drawdowns) else 0.0

    returns = np.diff(curve) / curve[:-1] if len(curve) > 1 else np.array([0.0])
    returns = returns[np.isfinite(returns)]
    sharpe_like = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if len(returns) > 1 and np.std(returns) > 0 else 0.0

    final_equity = curve[-1] if len(curve) else initial_equity
    total_return_pct = 100.0 * (final_equity - initial_equity) / initial_equity if initial_equity else 0.0

    return BacktestReport(
        trades=trades, equity_curve=list(curve), initial_equity=initial_equity,
        final_equity=float(final_equity), total_trades=total_trades, win_rate=win_rate,
        profit_factor=profit_factor, average_win=float(avg_win), average_loss=float(avg_loss),
        max_drawdown_pct=max_dd_pct, sharpe_like=sharpe_like, total_return_pct=total_return_pct,
    )
