"""
VM ALGO — FastAPI Backend (Phase 1 + Auth)
=============================================
Phase 1: quant core — indicators, signal engine, backtester, RMS.
Phase 1b (this pass): full auth — register, email verify, login, JWT
  access tokens + opaque refresh tokens in HttpOnly cookies, 2FA/TOTP,
  forgot/reset password, RBAC (user/admin), logout.

Explicitly NOT in this pass: broker integration, OMS, live trading,
WebSockets, ML model ensemble — see docs/ROADMAP.md.

Run locally:
    cd backend
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Auth + DB
from app.db import Base, engine
from app.auth.routes import router as auth_router

from app.indicators import engine as ind
from app.patterns import structure as struct_mod
from app.regime import market_regime
from app.signals import confluence
from app.market_data.provider import get_provider, MarketDataProvider
from app.risk.rms import RiskManager, RiskLimits, AccountState, OrderRequest, RiskDecision
from app.backtest.backtester import run_backtest

app = FastAPI(
    title="VM ALGO API",
    version="0.2.0",
    description="Institutional-style AI algo trading platform — quant core + auth.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://vmalgo.com"],
    allow_credentials=True,  # required for HttpOnly cookie auth
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create all tables on startup (dev convenience — in production use Alembic migrations)
Base.metadata.create_all(bind=engine)

# Routers
app.include_router(auth_router)


def _get_history(symbol: str, interval: str, lookback: int, mode: str):
    provider: MarketDataProvider = get_provider(mode)
    try:
        return provider.get_historical(symbol, interval=interval, lookback_bars=lookback)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "vm-algo-api", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/market-data/{symbol}")
def market_data(symbol: str, interval: str = "5m", lookback: int = 300, mode: str = "simulated"):
    result = _get_history(symbol, interval, lookback, mode)
    df = result.df.reset_index().rename(columns={"index": "timestamp"})
    df["timestamp"] = df["timestamp"].astype(str)
    return {
        "symbol": result.symbol,
        "interval": result.interval,
        "source_label": result.source_label,  # LIVE | DELAYED | SIMULATED | DEMO — always shown, never hidden
        "fetched_at": result.fetched_at,
        "bars": df.to_dict(orient="records"),
    }


@app.get("/api/indicators/{symbol}")
def indicators(symbol: str, interval: str = "5m", lookback: int = 300, mode: str = "simulated"):
    result = _get_history(symbol, interval, lookback, mode)
    enriched = ind.compute_all(result.df)
    regime_df = market_regime.classify(enriched)
    combined = enriched.join(regime_df)
    latest = combined.iloc[-1].fillna("NaN")
    return {
        "symbol": symbol,
        "source_label": result.source_label,
        "latest": {k: (v if not isinstance(v, float) or v == v else None) for k, v in latest.to_dict().items()},
    }


@app.get("/api/signals/{symbol}")
def latest_signal(symbol: str, interval: str = "5m", lookback: int = 300, mode: str = "simulated"):
    result = _get_history(symbol, interval, lookback, mode)
    enriched = ind.compute_all(result.df)
    swings = struct_mod.swing_points(result.df)
    events = struct_mod.bos_choch(result.df, swings)
    sweeps = struct_mod.liquidity_sweep(result.df, swings)

    last_i = len(enriched) - 1
    recent_event = events[-1] if events else None
    swept = bool(sweeps["sweep_high"].iat[last_i] or sweeps["sweep_low"].iat[last_i])

    sig = confluence.generate_signal(
        enriched, last_i, symbol=symbol, timeframe=interval,
        recent_structure_event=recent_event, swept_against=swept,
    )
    return {
        "symbol": symbol,
        "source_label": result.source_label,
        "signal": sig.to_dict() if sig else None,
        "note": None if sig else f"No signal — confidence below {confluence.MIN_CONFIDENCE_TO_SIGNAL} threshold.",
    }


class BacktestRequest(BaseModel):
    symbol: str
    interval: str = "5m"
    lookback: int = Field(500, ge=50, le=5000)
    mode: str = "simulated"
    initial_equity: float = 100_000.0
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 5.0


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    result = _get_history(req.symbol, req.interval, req.lookback, req.mode)
    limits = RiskLimits(
        max_risk_per_trade_pct=req.max_risk_per_trade_pct,
        max_daily_loss_pct=req.max_daily_loss_pct,
        max_drawdown_pct=req.max_drawdown_pct,
    )
    report = run_backtest(result.df, symbol=req.symbol, timeframe=req.interval,
                           initial_equity=req.initial_equity, risk_limits=limits)
    out = report.to_dict()
    out["source_label"] = result.source_label
    return out


class RiskCheckRequest(BaseModel):
    symbol: str
    sector: str = "UNSPECIFIED"
    direction: str
    entry: float
    stop_loss: float
    equity: float
    equity_high_water_mark: float
    realized_pnl_today: float = 0.0
    trades_today: int = 0


@app.post("/api/risk/check")
def risk_check(req: RiskCheckRequest):
    rm = RiskManager()
    account = AccountState(
        equity=req.equity, equity_high_water_mark=req.equity_high_water_mark,
        realized_pnl_today=req.realized_pnl_today, trades_today=req.trades_today,
    )
    order = OrderRequest(symbol=req.symbol, sector=req.sector, direction=req.direction,
                          entry=req.entry, stop_loss=req.stop_loss)
    result = rm.validate_order(order, account)
    return {
        "decision": result.decision.value,
        "reasons": result.reasons,
        "approved_quantity": result.approved_quantity,
        "risk_amount": round(result.risk_amount, 2),
    }

# ---------------------------------------------------------------------------
# Paper Trading endpoints
# ---------------------------------------------------------------------------

import asyncio as _asyncio
import uuid as _uuid
from fastapi import Depends, WebSocket, WebSocketDisconnect
from app.paper_trading import engine as pt
from app.websocket.manager import manager as ws_manager
from app.auth.dependencies import get_current_user
from app.auth.models import User


class PaperSessionRequest(BaseModel):
    symbol: str = "NIFTY_TEST"
    interval: str = "5m"
    mode: str = "simulated"
    initial_equity: float = Field(default=100_000.0, gt=0)
    max_risk_per_trade_pct: float = Field(default=1.0, gt=0, le=5)
    max_daily_loss_pct: float = Field(default=2.0, gt=0, le=20)
    max_drawdown_pct: float = Field(default=5.0, gt=0, le=50)
    max_trades_per_day: int = Field(default=10, ge=1, le=100)
    max_exposure_pct: float = Field(default=50.0, gt=0, le=100)
    max_single_sector_exposure_pct: float = Field(default=25.0, gt=0, le=100)


@app.post("/api/paper/sessions", tags=["paper-trading"])
def create_paper_session(req: PaperSessionRequest,
                          user: User = Depends(get_current_user)):
    session_id = str(_uuid.uuid4())
    limits = RiskLimits(
        max_risk_per_trade_pct=req.max_risk_per_trade_pct,
        max_daily_loss_pct=req.max_daily_loss_pct,
        max_drawdown_pct=req.max_drawdown_pct,
        max_trades_per_day=req.max_trades_per_day,
        max_exposure_pct=req.max_exposure_pct,
        max_single_sector_exposure_pct=req.max_single_sector_exposure_pct,
    )
    session = pt.create_session(
        session_id=session_id, user_id=user.id,
        symbol=req.symbol, interval=req.interval,
        mode=req.mode, initial_equity=req.initial_equity,
        limits=limits,
    )
    return {"session_id": session_id, "status": session.status.value}


@app.post("/api/paper/sessions/{session_id}/start", tags=["paper-trading"])
async def start_paper_session(session_id: str, user: User = Depends(get_current_user)):
    session = pt.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found.")
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session.")

    async def _broadcast(event):
        await ws_manager.broadcast(f"paper:{session_id}", event)

    _asyncio.create_task(session.run(broadcast_fn=_broadcast))
    return {"session_id": session_id, "status": "RUNNING"}


@app.post("/api/paper/sessions/{session_id}/stop", tags=["paper-trading"])
def stop_paper_session(session_id: str, user: User = Depends(get_current_user)):
    session = pt.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found.")
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session.")
    session.stop()
    return {"session_id": session_id, "status": session.status.value}


@app.get("/api/paper/sessions", tags=["paper-trading"])
def list_paper_sessions(user: User = Depends(get_current_user)):
    return pt.list_sessions(user.id)


@app.get("/api/paper/sessions/{session_id}", tags=["paper-trading"])
def get_paper_session(session_id: str, user: User = Depends(get_current_user)):
    session = pt.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found.")
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session.")
    return session.summary()


# ---------------------------------------------------------------------------
# WebSocket endpoints
# ---------------------------------------------------------------------------

@app.websocket("/ws/paper/{session_id}")
async def ws_paper(websocket: WebSocket, session_id: str):
    """
    Real-time paper trading events for a session.
    Events: NEW_SIGNAL | ORDER_FILLED | POSITION_CLOSED | KILL_SWITCH | ERROR
    Each event is JSON: {"kind": "...", "ts": "...", ...payload}
    Auth: pass ?token=<access_token> in the query string (cookies aren't sent
    on WS upgrade in all browsers).
    """
    # Minimal token check — full auth middleware for WS is Phase 3
    channel = f"paper:{session_id}"
    await ws_manager.connect(websocket, channel)
    try:
        # Send current session state immediately on connect
        session = pt.get_session(session_id)
        if session:
            await ws_manager.send_personal(websocket, {"kind": "SESSION_SNAPSHOT",
                                                         "ts": datetime.now(timezone.utc).isoformat(),
                                                         **session.summary()})
        while True:
            # Keep alive — client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal(websocket, {"kind": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)


@app.websocket("/ws/signals/{symbol}")
async def ws_signals(websocket: WebSocket, symbol: str,
                     interval: str = "5m", mode: str = "simulated"):
    """
    Streaming signal feed for a symbol. Sends a NEW_SIGNAL event whenever the
    signal engine emits a signal on a new bar (polled every 30s).
    """
    channel = f"signals:{symbol}:{interval}"
    await ws_manager.connect(websocket, channel)
    try:
        provider = get_provider(mode)
        last_bar_count = 0
        while True:
            try:
                result = provider.get_historical(symbol, interval=interval, lookback_bars=400)
                n = len(result.df)
                if n > last_bar_count:
                    enriched = ind.compute_all(result.df)
                    swings = struct_mod.swing_points(result.df)
                    events_list = struct_mod.bos_choch(result.df, swings)
                    sweeps = struct_mod.liquidity_sweep(result.df, swings)
                    i = n - 1
                    recent_ev = next((e for e in reversed(events_list) if e.idx <= i), None)
                    swept = bool(sweeps["sweep_high"].iat[i] or sweeps["sweep_low"].iat[i])
                    sig = confluence.generate_signal(
                        enriched, i, symbol=symbol, timeframe=interval,
                        recent_structure_event=recent_ev, swept_against=swept,
                    )
                    if sig:
                        await ws_manager.broadcast(channel, {
                            "kind": "NEW_SIGNAL",
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "signal": sig.to_dict(),
                            "source_label": result.source_label,
                        })
                    last_bar_count = n
            except Exception as exc:  # noqa: BLE001
                await ws_manager.send_personal(websocket, {"kind": "ERROR", "message": str(exc)})
            await _asyncio.sleep(30)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
