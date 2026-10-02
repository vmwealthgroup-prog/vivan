VM ALGO — Roadmap
====================

STATUS AS OF THIS PASS
-----------------------

Phase 1 — Quant core                                               [DONE]
  [x] 20+ indicators (EMA/RSI/MACD/ATR/Supertrend/ADX/Bollinger/
      Ichimoku/OBV/CMF/MFI/pivot points etc)
  [x] Candlestick pattern detection (12 patterns)
  [x] Market structure (swings, HH/HL/LH/LL, BOS/CHoCH, FVGs,
      liquidity sweeps, order blocks)
  [x] Market regime classifier (trend + volatility)
  [x] Confluence signal engine with documented scoring methodology
  [x] Risk Management System (joint position sizing, kill switches,
      trading-hours gate, sector/exposure caps)
  [x] Bar-by-bar backtester (no look-ahead)
  [x] Market data provider abstraction (LIVE/DELAYED/SIMULATED labels)
  [x] FastAPI wiring: health, market-data, indicators, signals, backtest, risk/check
  Tests: 8/8 passing

Phase 1b — Auth                                                    [DONE]
  [x] JWT access tokens (15 min, HttpOnly cookie)
  [x] Opaque refresh tokens (7 day, HttpOnly cookie, rotated on use)
  [x] Register + email verification
  [x] Login with 2FA/TOTP
  [x] Forgot / reset password
  [x] RBAC (user / admin roles)
  [x] Alembic migrations (initial_auth_schema)
  [x] SQLite for dev, PostgreSQL-ready (env var)
  Tests: 9/9 passing

Phase 2 — Paper Trading + WebSockets + Broker abstraction         [DONE]
  [x] Paper trading engine (signal engine + RMS loop, simulated fills,
      real-time events, kill switch, PnL tracking)
  [x] WebSocket connection manager (multi-channel, auto-remove stale connections)
  [x] WS endpoints: /ws/paper/{session_id}, /ws/signals/{symbol}
  [x] Paper trading REST: create/start/stop/list/get sessions
  [x] Broker abstraction layer (BrokerBase interface)
  [x] SimulatedBroker (fills instantly, no network)
  [x] KotakNeoAdapter STUB (documented placeholder, raises NotImplementedError
      until you wire credentials — intentionally prevents accidental live orders)
  Tests: 6/6 passing

Phase 2 — Frontend                                                 [DONE]
  [x] Next.js 15 + React 18 + Tailwind + lucide-react
  [x] Login page (email+password, 2FA step)
  [x] Register page (password rules, email sent confirmation)
  [x] Forgot/reset password pages
  [x] Dashboard (real API data, source label always shown, 15 indicators,
      signal card with full WHY reasoning + scoring breakdown, 30s auto-refresh)
  [x] Paper trading page (session config, live WS event feed, open position,
      P&L tracking, auto-reconnect WebSocket)
  [x] useWebSocket hook (exponential backoff reconnect, keepalive ping)
  [x] SourceBadge component (mandatory on every price/signal display)
  Build: 8/8 routes compile clean

Phase 3 — Kotak Neo live integration                               [NEXT]
  [ ] Wire KotakNeoAdapter with real API calls (kotak-neo-api package)
  [ ] OMS: order lifecycle (NEW→VALIDATED→SENT→FILLED→COMPLETED)
  [ ] Live trading session (paper engine variant that routes to real broker)
  [ ] Broker WS callbacks → push to user WS channel

Phase 4 — Production hardening
  [ ] NSE holiday calendar (currently weekday + 09:15-15:30 only)
  [ ] Alembic migration for paper trade history persistence (currently in-process only)
  [ ] Multi-worker Redis pub/sub for WS (current manager is single-process)
  [ ] SMTP / SES for real email delivery (currently Console sender)
  [ ] Admin panel, audit logs, monitoring

Phase 5 — AI/ML layer
  [ ] LSTM/XGBoost/RandomForest/LightGBM ensemble
  [ ] Output plugs into the "AI model agreement" slot in signals/confluence.py
      (present, explicitly zero-weighted until rule-based baseline is established)

NOT SOLVED (flagged, not forgotten)
  - NSE holiday calendar
  - Survivorship-bias-safe universe backtesting
  - Walk-forward / Monte Carlo robustness testing
  - Kotak Neo credentials not wired (see broker/base.py)
  - Paper trade history not persisted to DB between server restarts
    (in-process dict only — needs its own Alembic migration in Phase 3)
