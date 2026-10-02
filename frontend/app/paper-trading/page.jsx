'use client';

import { useState, useEffect } from 'react';
import {
  Play, Square, TrendingUp, TrendingDown, AlertTriangle,
  CheckCircle, XCircle, Activity, Zap, DollarSign, ShieldAlert,
} from 'lucide-react';
import { api, auth, ApiError } from '../lib/api';
import { SourceBadge } from '../components/SourceBadge';
import { useWebSocket } from '../hooks/useWebSocket';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function WsStatus({ status }) {
  const map = {
    open: 'bg-emerald-500',
    connecting: 'bg-amber-500 animate-pulse',
    closed: 'bg-slate-500',
    error: 'bg-rose-500',
  };
  return (
    <div className="flex items-center gap-1.5 text-xs text-slate-400">
      <span className={`w-2 h-2 rounded-full ${map[status] ?? 'bg-slate-600'}`} />
      {status}
    </div>
  );
}

function EventRow({ ev }) {
  const icons = {
    NEW_SIGNAL:      <Zap className="w-3.5 h-3.5 text-amber-400" />,
    ORDER_FILLED:    <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />,
    POSITION_CLOSED: <DollarSign className="w-3.5 h-3.5 text-blue-400" />,
    KILL_SWITCH:     <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />,
    RISK_REJECTED:   <ShieldAlert className="w-3.5 h-3.5 text-orange-400" />,
    ERROR:           <XCircle className="w-3.5 h-3.5 text-rose-400" />,
  };
  const pnl = ev.pnl !== undefined ? ev.pnl : null;

  return (
    <div className="flex items-start gap-2 py-2 border-b border-slate-800/50 last:border-0">
      <span className="mt-0.5 shrink-0">{icons[ev.kind] ?? <Activity className="w-3.5 h-3.5 text-slate-500" />}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-semibold text-white">{ev.kind.replace(/_/g, ' ')}</span>
          {ev.direction && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${ev.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
              {ev.direction}
            </span>
          )}
          {pnl !== null && (
            <span className={`text-xs font-semibold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
            </span>
          )}
          {ev.source_label && <SourceBadge label={ev.source_label} />}
        </div>
        <div className="text-[10px] text-slate-500 mt-0.5">
          {ev.fill_price && `Fill: ₹${ev.fill_price} × ${ev.quantity}`}
          {ev.stop_loss && ` · SL: ₹${ev.stop_loss}`}
          {ev.confidence && ` · ${ev.confidence}% conf`}
          {ev.exit_reason && ` · ${ev.exit_reason}`}
          {ev.reason && ev.kind === 'KILL_SWITCH' && ` ${ev.reason}`}
          {ev.reasons && ev.kind === 'RISK_REJECTED' && ` ${ev.reasons.join(' ')}`}
          {ev.message && ev.kind === 'ERROR' && ` ${ev.message}`}
        </div>
      </div>
      <span className="text-[10px] text-slate-600 shrink-0">
        {ev.ts ? new Date(ev.ts).toLocaleTimeString() : ''}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PaperTradingPage() {
  const [user, setUser] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Form state
  const [symbol, setSymbol] = useState('NIFTY_TEST');
  const [interval, setInterval] = useState('5m');
  const [mode, setMode] = useState('simulated');
  const [equity, setEquity] = useState(100000);
  const [maxRisk, setMaxRisk] = useState(1.0);
  const [maxDailyLoss, setMaxDailyLoss] = useState(2.0);
  const [maxDD, setMaxDD] = useState(5.0);
  const [maxTradesPerDay, setMaxTradesPerDay] = useState(10);
  const [maxExposure, setMaxExposure] = useState(50);
  const [maxSectorExposure, setMaxSectorExposure] = useState(25);

  // WebSocket for active session
  const wsPath = activeSession ? `/ws/paper/${activeSession.session_id}` : null;
  const { events, status: wsStatus, reset: resetEvents } = useWebSocket(
    wsPath ?? '/ws/signals/NIFTY_TEST',
    { maxEvents: 150 }
  );

  // Extract latest snapshot from WS events
  const snapshot = [...events].reverse().find(e => e.kind === 'SESSION_SNAPSHOT' || e.equity !== undefined);

  useEffect(() => {
    auth.me().then(setUser).catch(() => { window.location.href = '/login'; });
  }, []);

  useEffect(() => {
    if (!user) return;
    api.request?.('/api/paper/sessions') // soft call — use raw fetch
      ?? fetch('/api/paper/sessions', { credentials: 'include' })
        .then(r => r.ok ? r.json() : [])
        .then(setSessions)
        .catch(() => {});
  }, [user]);

  async function createAndStart() {
    setError(''); setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/paper/sessions`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol, interval, mode,
          initial_equity: equity,
          max_risk_per_trade_pct: maxRisk,
          max_daily_loss_pct: maxDailyLoss,
          max_drawdown_pct: maxDD,
          max_trades_per_day: maxTradesPerDay,
          max_exposure_pct: maxExposure,
          max_single_sector_exposure_pct: maxSectorExposure,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const created = await res.json();

      // Start it
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/paper/sessions/${created.session_id}/start`, {
        method: 'POST', credentials: 'include',
      });

      setActiveSession({ session_id: created.session_id, symbol, interval, mode });
      resetEvents();
    } catch (err) {
      setError(err.message || 'Failed to start session.');
    } finally {
      setLoading(false);
    }
  }

  async function stopSession() {
    if (!activeSession) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/paper/sessions/${activeSession.session_id}/stop`, {
      method: 'POST', credentials: 'include',
    }).catch(() => {});
    setActiveSession(null);
  }

  if (!user) return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="animate-spin rounded-full h-6 w-6 border-2 border-emerald-500 border-t-transparent" />
    </div>
  );

  const running = !!activeSession;
  const currentEquity = snapshot?.equity ?? equity;
  const pnl = currentEquity - equity;

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="w-5 h-5 text-emerald-400" />
            <span className="font-bold text-white">Paper Trading</span>
            {running && <WsStatus status={wsStatus} />}
          </div>
          <a href="/dashboard" className="text-xs text-slate-400 hover:text-white transition">← Dashboard</a>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {error && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {error}
          </div>
        )}

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Config panel */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <h2 className="font-semibold text-white text-sm">Session Configuration</h2>

            {[
              { label: 'Symbol', value: symbol, setter: setSymbol, options: ['NIFTY_TEST','BANKNIFTY_TEST','RELIANCE.NS'] },
              { label: 'Interval', value: interval, setter: setInterval, options: ['1m','5m','15m','1h'] },
              { label: 'Data Mode', value: mode, setter: setMode, options: ['simulated','yfinance'] },
            ].map(({ label, value, setter, options }) => (
              <div key={label}>
                <label className="text-xs text-slate-400 mb-1 block">{label}</label>
                <select value={value} onChange={e => setter(e.target.value)} disabled={running}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 disabled:opacity-40">
                  {options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            ))}

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Starting Equity (₹)</label>
              <input type="number" value={equity} onChange={e => setEquity(+e.target.value)}
                disabled={running} min={10000} step={10000}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 disabled:opacity-40" />
            </div>

            <div className="space-y-2 border-t border-slate-800 pt-3">
              <p className="text-xs text-slate-500 font-medium uppercase tracking-wider">Risk Limits</p>
              {[
                { label: 'Max risk / trade %', value: maxRisk, setter: setMaxRisk, min: 0.1, max: 5, step: 0.1 },
                { label: 'Max daily loss %', value: maxDailyLoss, setter: setMaxDailyLoss, min: 0.5, max: 10, step: 0.5 },
                { label: 'Max drawdown %', value: maxDD, setter: setMaxDD, min: 1, max: 20, step: 1 },
                { label: 'Max trades / day', value: maxTradesPerDay, setter: setMaxTradesPerDay, min: 1, max: 100, step: 1 },
                { label: 'Max total exposure %', value: maxExposure, setter: setMaxExposure, min: 1, max: 100, step: 1 },
                { label: 'Max sector exposure %', value: maxSectorExposure, setter: setMaxSectorExposure, min: 1, max: 100, step: 1 },
              ].map(({ label, value, setter, ...props }) => (
                <div key={label} className="flex items-center justify-between">
                  <label className="text-xs text-slate-400">{label}</label>
                  <input type="number" value={value} onChange={e => setter(+e.target.value)}
                    disabled={running} className="w-20 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white text-right focus:outline-none focus:border-emerald-500 disabled:opacity-40"
                    {...props} />
                </div>
              ))}
            </div>

            <button onClick={running ? stopSession : createAndStart}
              disabled={loading}
              className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg font-semibold text-sm transition disabled:opacity-50 ${running ? 'bg-rose-600 hover:bg-rose-500' : 'bg-emerald-600 hover:bg-emerald-500'} text-white`}>
              {running ? <><Square className="w-4 h-4" /> Stop Session</> : loading ? 'Starting…' : <><Play className="w-4 h-4" /> Start Paper Trading</>}
            </button>

            {mode === 'simulated' && (
              <p className="text-[10px] text-slate-600 text-center">
                Synthetic data — not real market prices.<br />
                Switch to "yfinance" for exchange-delayed NSE data.
              </p>
            )}
          </div>

          {/* Stats + live feed */}
          <div className="lg:col-span-2 space-y-4">
            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Equity</p>
                <p className="text-xl font-bold text-white">₹{currentEquity.toLocaleString('en-IN')}</p>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">P&L</p>
                <p className={`text-xl font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
                </p>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Trades</p>
                <p className="text-xl font-bold text-white">
                  {snapshot?.total_trades ?? 0}
                </p>
              </div>
            </div>

            {/* Open position */}
            {snapshot?.open_position && (
              <div className={`border rounded-xl p-4 ${snapshot.open_position.direction === 'LONG' ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-rose-500/5 border-rose-500/20'}`}>
                <div className="flex items-center gap-2 mb-2">
                  {snapshot.open_position.direction === 'LONG'
                    ? <TrendingUp className="w-4 h-4 text-emerald-400" />
                    : <TrendingDown className="w-4 h-4 text-rose-400" />}
                  <span className="font-semibold text-sm text-white">Open Position</span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[
                    ['Symbol', snapshot.open_position.symbol],
                    ['Entry', `₹${snapshot.open_position.entry_price?.toFixed(2)}`],
                    ['Qty', snapshot.open_position.quantity],
                    ['Conf', `${snapshot.open_position.signal_confidence?.toFixed(0)}%`],
                  ].map(([l, v]) => (
                    <div key={l} className="bg-slate-900/60 rounded p-1.5">
                      <div className="text-[10px] text-slate-500">{l}</div>
                      <div className="text-sm font-semibold text-white">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Live event feed */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-slate-300">Live Event Feed</h3>
                <button onClick={resetEvents} className="text-xs text-slate-500 hover:text-slate-300">Clear</button>
              </div>
              {events.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-slate-600">
                  <Activity className="w-8 h-8 mb-2" />
                  <p className="text-sm">{running ? 'Waiting for first signal…' : 'Start a session to see live events.'}</p>
                </div>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  {[...events].reverse().map((ev, i) => (
                    <EventRow key={i} ev={ev} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
