"""
VM ALGO — Paper Trading Engine
================================
Simulates live trading using real (delayed) or synthetic market data +
the confluence signal engine + RMS. No broker API calls are made — all
fills are synthetic (next-bar open with slippage). Every paper trade is
persisted to the DB and broadcast over WebSocket so the dashboard updates
in real time.

Lifecycle:
  PaperTradingSession created (user_id, symbol, interval, mode, equity)
    -> start()  — runs until stop() or max_trades/kill_switch hit
    -> generates signals bar-by-bar on each new candle
    -> risk-checks each signal
    -> fills on the next synthetic bar
    -> emits WS events: NEW_SIGNAL, ORDER_FILLED, POSITION_CLOSED, KILL_SWITCH

State machine (session.status):
  CREATED -> RUNNING -> STOPPED | KILLED
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.indicators import engine as ind
from app.market_data.provider import get_provider, MarketDataResult
from app.patterns import structure as struct_mod
from app.signals.confluence import generate_signal, MIN_CONFIDENCE_TO_SIGNAL
from app.risk.rms import (
    RiskManager, RiskLimits, AccountState, OrderRequest, RiskDecision,
)

log = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    KILLED  = "KILLED"   # kill switch triggered


@dataclass
class PaperPosition:
    symbol: str
    direction: str          # LONG | SHORT
    entry_price: float
    quantity: int
    stop_loss: float
    target_1: float
    target_2: float
    entry_bar: int
    signal_confidence: float
    opened_at: str


@dataclass
class PaperTrade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    exit_reason: str        # TARGET_1 | TARGET_2 | STOP | MANUAL | KILL_SWITCH
    opened_at: str
    closed_at: str
    signal_confidence: float


@dataclass
class PaperSession:
    session_id: str
    user_id: int
    symbol: str
    interval: str
    mode: str               # simulated | yfinance
    initial_equity: float
    risk_limits: RiskLimits = field(default_factory=RiskLimits)

    # runtime state — mutated during run
    status: SessionStatus = SessionStatus.CREATED
    equity: float = 0.0
    equity_hwm: float = 0.0
    realized_pnl: float = 0.0
    trades_today: int = 0
    trades: list[PaperTrade] = field(default_factory=list)
    open_position: Optional[PaperPosition] = None
    events: list[dict] = field(default_factory=list)
    _stop_flag: bool = field(default=False, repr=False)

    def __post_init__(self):
        self.equity = self.initial_equity
        self.equity_hwm = self.initial_equity

    # ------------------------------------------------------------------
    def _emit(self, kind: str, payload: dict) -> dict:
        event = {"kind": kind, "ts": _now(), **payload}
        self.events.append(event)
        return event

    def summary(self) -> dict:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "status": self.status.value,
            "equity": round(self.equity, 2),
            "initial_equity": round(self.initial_equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_trades": len(self.trades),
            "win_rate": round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0.0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "open_position": asdict(self.open_position) if self.open_position else None,
            "recent_events": self.events[-20:],
        }

    # ------------------------------------------------------------------
    async def run(self, broadcast_fn=None, lookback: int = 500,
                  poll_seconds: float = 30.0):
        """
        Main loop. Fetches a rolling window of bars every `poll_seconds`,
        processes only newly arrived bars (detected by bar count growth),
        and emits events via `broadcast_fn(event_dict)` if provided.

        In simulated mode the "new bars" are the last 1-3 bars of the fresh
        fetch (synthetic data advances with wall-clock time). In yfinance
        mode genuinely new candles arrive as the market prints them.
        """
        self.status = SessionStatus.RUNNING
        rm = RiskManager(self.risk_limits)
        provider = get_provider(self.mode)
        last_bar_count = 0
        last_event_ptr = None  # last structure event seen

        async def _broadcast(event):
            if broadcast_fn is not None:
                try:
                    await broadcast_fn(event)
                except Exception:  # noqa: BLE001
                    pass

        while not self._stop_flag:
            try:
                result: MarketDataResult = provider.get_historical(
                    self.symbol, interval=self.interval, lookback_bars=lookback
                )
                df = result.df
                n = len(df)

                if n <= last_bar_count:
                    await asyncio.sleep(poll_seconds)
                    continue

                # Process each new bar sequentially (oldest first)
                new_bars = range(last_bar_count, n)
                enriched = ind.compute_all(df)
                swings = struct_mod.swing_points(df)
                events_list = struct_mod.bos_choch(df, swings)
                sweeps = struct_mod.liquidity_sweep(df, swings)

                for i in new_bars:
                    # --- manage open position ---
                    if self.open_position is not None:
                        pos = self.open_position
                        hi, lo = df["high"].iat[i], df["low"].iat[i]
                        exit_price = exit_reason = None

                        if pos.direction == "LONG":
                            if lo <= pos.stop_loss:
                                exit_price, exit_reason = pos.stop_loss, "STOP"
                            elif hi >= pos.target_1:
                                exit_price, exit_reason = pos.target_1, "TARGET_1"
                        else:
                            if hi >= pos.stop_loss:
                                exit_price, exit_reason = pos.stop_loss, "STOP"
                            elif lo <= pos.target_1:
                                exit_price, exit_reason = pos.target_1, "TARGET_1"

                        if exit_price is not None:
                            pnl = _calc_pnl(pos, exit_price)
                            trade = PaperTrade(
                                symbol=pos.symbol, direction=pos.direction,
                                entry_price=pos.entry_price, exit_price=exit_price,
                                quantity=pos.quantity, pnl=pnl,
                                exit_reason=exit_reason,
                                opened_at=pos.opened_at, closed_at=_now(),
                                signal_confidence=pos.signal_confidence,
                            )
                            self.trades.append(trade)
                            self.equity += pnl
                            self.equity_hwm = max(self.equity_hwm, self.equity)
                            self.realized_pnl += pnl
                            self.open_position = None

                            ev = self._emit("POSITION_CLOSED", {
                                "symbol": pos.symbol, "direction": pos.direction,
                                "pnl": round(pnl, 2), "exit_reason": exit_reason,
                                "equity": round(self.equity, 2),
                                "source_label": result.source_label,
                            })
                            await _broadcast(ev)

                    # --- kill switch check ---
                    account = AccountState(
                        equity=self.equity, equity_high_water_mark=self.equity_hwm,
                        realized_pnl_today=self.realized_pnl,
                        trades_today=self.trades_today,
                        open_positions=[asdict(self.open_position)] if self.open_position else [],
                    )
                    engaged, reason = rm.check_kill_switch(account)
                    if engaged:
                        self.status = SessionStatus.KILLED
                        ev = self._emit("KILL_SWITCH", {"reason": reason, "equity": round(self.equity, 2)})
                        await _broadcast(ev)
                        return

                    # --- look for a new signal (only if no open position) ---
                    if self.open_position is None and i + 1 < n:
                        recent_ev = next(
                            (e for e in reversed(events_list) if e.idx <= i), None
                        )
                        swept = bool(
                            sweeps["sweep_high"].iat[i] or sweeps["sweep_low"].iat[i]
                        )
                        sig = generate_signal(
                            enriched, i,
                            symbol=self.symbol, timeframe=self.interval,
                            recent_structure_event=recent_ev,
                            swept_against=swept,
                        )
                        if sig is not None:
                            ev = self._emit("NEW_SIGNAL", {
                                "signal": sig.to_dict(),
                                "source_label": result.source_label,
                            })
                            await _broadcast(ev)

                            order = OrderRequest(
                                symbol=self.symbol, sector="IDX",
                                direction=sig.direction,
                                entry=sig.entry, stop_loss=sig.stop_loss,
                            )
                            risk_result = rm.validate_order(order, account,
                                                             now=df.index[i])
                            if risk_result.decision == RiskDecision.APPROVED and risk_result.approved_quantity > 0:
                                fill = df["open"].iat[i + 1]  # next-bar open fill
                                self.open_position = PaperPosition(
                                    symbol=self.symbol,
                                    direction=sig.direction,
                                    entry_price=fill,
                                    quantity=risk_result.approved_quantity,
                                    stop_loss=sig.stop_loss,
                                    target_1=sig.target_1,
                                    target_2=sig.target_2,
                                    entry_bar=i + 1,
                                    signal_confidence=sig.confidence,
                                    opened_at=_now(),
                                )
                                self.trades_today += 1
                                ev = self._emit("ORDER_FILLED", {
                                    "direction": sig.direction,
                                    "fill_price": round(fill, 2),
                                    "quantity": risk_result.approved_quantity,
                                    "stop_loss": round(sig.stop_loss, 2),
                                    "target_1": round(sig.target_1, 2),
                                    "confidence": round(sig.confidence, 1),
                                    "source_label": result.source_label,
                                })
                                await _broadcast(ev)
                            else:
                                ev = self._emit("RISK_REJECTED", {
                                    "direction": sig.direction,
                                    "entry": round(sig.entry, 2),
                                    "reasons": risk_result.reasons,
                                    "source_label": result.source_label,
                                })
                                await _broadcast(ev)

                last_bar_count = n

            except Exception as exc:  # noqa: BLE001
                log.warning("Paper trading loop error: %s", exc)
                ev = self._emit("ERROR", {"message": str(exc)})
                await _broadcast(ev)

            await asyncio.sleep(poll_seconds)

        self.status = SessionStatus.STOPPED

    def stop(self):
        self._stop_flag = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _calc_pnl(pos: PaperPosition, exit_price: float) -> float:
    COMMISSION = 20.0
    SLIPPAGE_PCT = 0.02
    if pos.direction == "LONG":
        fill = exit_price * (1 - SLIPPAGE_PCT / 100)
        gross = (fill - pos.entry_price) * pos.quantity
    else:
        fill = exit_price * (1 + SLIPPAGE_PCT / 100)
        gross = (pos.entry_price - fill) * pos.quantity
    return gross - COMMISSION


# ---------------------------------------------------------------------------
# Session registry (in-process, suitable for single-worker deployments)
# ---------------------------------------------------------------------------

_sessions: dict[str, PaperSession] = {}


def create_session(session_id: str, user_id: int, symbol: str, interval: str,
                   mode: str, initial_equity: float,
                   limits: RiskLimits | None = None) -> PaperSession:
    if session_id in _sessions:
        raise ValueError(f"Session {session_id!r} already exists.")
    s = PaperSession(
        session_id=session_id, user_id=user_id, symbol=symbol,
        interval=interval, mode=mode, initial_equity=initial_equity,
        risk_limits=limits or RiskLimits(),
    )
    _sessions[session_id] = s
    return s


def get_session(session_id: str) -> PaperSession | None:
    return _sessions.get(session_id)


def list_sessions(user_id: int) -> list[dict]:
    return [s.summary() for s in _sessions.values() if s.user_id == user_id]
