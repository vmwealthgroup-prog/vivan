'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Shield,
  LogOut,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  User,
} from 'lucide-react';
import { api, auth, ApiError } from '../lib/api';
import { SourceBadge } from '../components/SourceBadge';

// ---------------------------------------------------------------------------
// Tiny reusable bits
// ---------------------------------------------------------------------------

function Spinner() {
  return <div className="animate-spin rounded-full h-5 w-5 border-2 border-emerald-500 border-t-transparent" />;
}

function StatCard({ label, value, sub, highlight }) {
  return (
    <div className={`bg-slate-900 border rounded-xl p-4 ${highlight ? 'border-emerald-500/40' : 'border-slate-800'}`}>
      <p className="text-xs text-slate-500 uppercase tracking-wider font-medium mb-1">{label}</p>
      <p className={`text-xl font-bold ${highlight ? 'text-emerald-400' : 'text-white'}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function SignalCard({ sig }) {
  const [expanded, setExpanded] = useState(false);
  if (!sig) return null;
  const bull = sig.direction === 'LONG';
  const Icon = bull ? TrendingUp : TrendingDown;
  const colDir = bull ? 'text-emerald-400' : 'text-rose-400';
  const bgDir = bull ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-rose-500/10 border-rose-500/25';

  return (
    <div className={`border rounded-xl p-4 ${bgDir}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className={`w-5 h-5 ${colDir} shrink-0`} />
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-white">{sig.symbol}</span>
              <span
                className={`text-xs font-semibold uppercase px-1.5 py-0.5 rounded ${
                  bull ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
                }`}
              >
                {sig.direction}
              </span>
              <span className="text-xs text-slate-400">{sig.timeframe}</span>
            </div>
            <div className="text-xs text-slate-400 mt-0.5">{sig.strategy}</div>
          </div>
        </div>

        {/* Confidence ring */}
        <div className="text-right shrink-0">
          <div
            className={`text-2xl font-black ${
              sig.confidence >= 75
                ? 'text-emerald-400'
                : sig.confidence >= 60
                ? 'text-amber-400'
                : 'text-slate-400'
            }`}
          >
            {typeof sig.confidence === 'number' ? `${sig.confidence.toFixed(0)}%` : '—'}
          </div>
          <div className="text-xs text-slate-500">confidence</div>
        </div>
      </div>

      {/* Key levels */}
      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        {[
          { label: 'Entry', val: sig.entry },
          { label: 'Stop', val: sig.stop_loss },
          { label: 'T1', val: sig.target_1 },
          { label: 'T2', val: sig.target_2 },
        ].map(({ label, val }) => (
          <div key={label} className="bg-slate-900/60 rounded-lg p-1.5">
            <div className="text-[10px] text-slate-500 uppercase">{label}</div>
            <div className="text-sm font-semibold text-white">
              {typeof val === 'number' ? val.toFixed(2) : '—'}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-slate-400">
          R:R = {typeof sig.risk_reward === 'number' ? sig.risk_reward.toFixed(2) : '—'}
        </span>
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-1 text-slate-400 hover:text-white transition"
        >
          WHY? {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-1.5 border-t border-white/5 pt-3">
          {(sig.reasoning ?? []).map((r, i) => (
            <div key={i} className="flex gap-2 text-xs text-slate-300">
              <CheckCircle className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
              <span>{r}</span>
            </div>
          ))}
          {/* Scoring breakdown */}
          {sig.scoring_breakdown && (
            <div className="mt-2 text-xs text-slate-500 border-t border-white/5 pt-2">
              Score: {sig.scoring_breakdown.achieved_bull ?? sig.scoring_breakdown.achieved_bear}
              /{sig.scoring_breakdown.possible} pts
              {' · '}
              <span className="text-amber-500/80">{sig.scoring_breakdown.ai_model_agreement}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function IndicatorRow({ label, value, note }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-800/50 last:border-0">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="text-right">
        <span className="text-sm font-mono font-medium text-white">
          {typeof value === 'number' ? value.toFixed(2) : value ?? '—'}
        </span>
        {note && (
          <span
            className={`ml-2 text-[10px] font-semibold ${
              note === 'BULLISH' || note === 'TRENDING_UP'
                ? 'text-emerald-400'
                : note === 'BEARISH' || note === 'TRENDING_DOWN'
                ? 'text-rose-400'
                : 'text-slate-400'
            }`}
          >
            {note}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

const SYMBOLS = ['NIFTY_TEST', 'BANKNIFTY_TEST', 'RELIANCE_TEST'];
const INTERVALS = ['1m', '5m', '15m', '1h'];
const MODES = [
  { value: 'simulated', label: 'Simulated' },
  { value: 'yfinance', label: 'Yahoo Finance (delayed)' },
];

export default function DashboardPage() {
  const [user, setUser] = useState(null);
  const [symbol, setSymbol] = useState('NIFTY_TEST');
  const [interval, setInterval] = useState('5m');
  const [mode, setMode] = useState('simulated');

  const [signal, setSignal] = useState(null);
  const [indicators, setIndicators] = useState(null);
  const [sourceLabel, setSourceLabel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [error, setError] = useState('');
  const [lastRefresh, setLastRefresh] = useState(null);

  // Auth guard
  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .catch(() => {
        window.location.href = '/login';
      });
  }, []);

  const refresh = useCallback(
    async (showFullLoader = false) => {
      if (showFullLoader) setLoading(true);
      setError('');
      try {
        const [sigRes, indRes] = await Promise.all([
          api.signal(symbol, interval, mode),
          api.indicators(symbol, interval, mode),
        ]);
        setSignal(sigRes.signal);
        setSourceLabel(sigRes.source_label);
        setIndicators(indRes.latest);
        setLastRefresh(new Date());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to fetch market data.');
      } finally {
        setLoading(false);
        setIsInitialLoad(false);
      }
    },
    [symbol, interval, mode]
  );

  useEffect(() => {
    if (user) refresh(true);
  }, [user, refresh]);

  // Auto-refresh every 30s seamlessly without triggering full container skeleton/spinner
  useEffect(() => {
    if (!user) return;
    const id = window.setInterval(() => {
      refresh(false);
    }, 30_000);
    return () => window.clearInterval(id);
  }, [user, refresh]);

  async function handleLogout() {
    await auth.logout().catch(() => {});
    window.location.href = '/login';
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const ind = indicators ?? {};
  const rsiVal = ind.rsi_14;
  const rsiNote = rsiVal != null ? (rsiVal > 60 ? 'BULLISH' : rsiVal < 40 ? 'BEARISH' : 'NEUTRAL') : null;
  const stDir = ind.supertrend_dir;
  const stNote = stDir != null ? (stDir > 0 ? 'BULLISH' : 'BEARISH') : null;
  const trendNote = ind.trend_regime ?? null;

  const plusDiStr = typeof ind.plus_di_14 === 'number' ? ind.plus_di_14.toFixed(1) : '—';
  const minusDiStr = typeof ind.minus_di_14 === 'number' ? ind.minus_di_14.toFixed(1) : '—';

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Top bar */}
      <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-6 h-6 text-emerald-400" />
            <span className="font-bold tracking-tight text-white">VM ALGO</span>
            {sourceLabel && <SourceBadge label={sourceLabel} />}
          </div>

          <div className="flex items-center gap-2">
            {/* Controls */}
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="text-xs bg-slate-800 border border-slate-700 text-white rounded-lg px-2 py-1.5 focus:outline-none focus:border-emerald-500"
            >
              {SYMBOLS.map(s => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <select
              value={interval}
              onChange={e => setInterval(e.target.value)}
              className="text-xs bg-slate-800 border border-slate-700 text-white rounded-lg px-2 py-1.5 focus:outline-none focus:border-emerald-500"
            >
              {INTERVALS.map(i => (
                <option key={i}>{i}</option>
              ))}
            </select>
            <select
              value={mode}
              onChange={e => setMode(e.target.value)}
              className="text-xs bg-slate-800 border border-slate-700 text-white rounded-lg px-2 py-1.5 focus:outline-none focus:border-emerald-500"
            >
              {MODES.map(m => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>

            <button
              onClick={() => refresh(true)}
              disabled={loading}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 transition disabled:opacity-50"
              title="Refresh Data"
            >
              <RefreshCw className={`w-4 h-4 text-slate-300 ${loading ? 'animate-spin' : ''}`} />
            </button>

            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              <User className="w-4 h-4" />
              <span className="hidden sm:inline">{user.name}</span>
            </div>
            <a
              href="/paper-trading"
              className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs text-slate-300 hover:text-white transition"
            >
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              Paper Trade
            </a>

            <button
              onClick={handleLogout}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-500/20 border border-slate-700 hover:border-rose-500/40 transition"
              title="Logout"
            >
              <LogOut className="w-4 h-4 text-slate-400 hover:text-rose-400" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Error banner */}
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Last refresh note */}
        {lastRefresh && (
          <p className="text-xs text-slate-600">
            Last updated {lastRefresh.toLocaleTimeString()} ·{' '}
            {mode === 'simulated' ? 'Data is synthetic — not real market prices' : 'Yahoo Finance (exchange-delayed)'}
          </p>
        )}

        {/* Key indicator stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Close" value={typeof ind.close === 'number' ? ind.close.toFixed(2) : null} />
          <StatCard
            label="RSI 14"
            value={typeof rsiVal === 'number' ? rsiVal.toFixed(1) : null}
            sub={rsiNote}
            highlight={rsiVal > 60}
          />
          <StatCard
            label="ADX 14"
            value={typeof ind.adx_14 === 'number' ? ind.adx_14.toFixed(1) : null}
            sub={ind.adx_14 > 22 ? 'Trending' : 'Ranging'}
          />
          <StatCard
            label="Regime"
            value={trendNote ? trendNote.replace('_', ' ') : null}
            highlight={trendNote === 'TRENDING_UP'}
          />
        </div>

        {/* Two-column: signal + indicators */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Signal */}
          <div>
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              Latest Signal
            </h2>
            {loading && isInitialLoad ? (
              <div className="flex justify-center py-12">
                <Spinner />
              </div>
            ) : signal ? (
              <SignalCard sig={signal} />
            ) : (
              <div className="flex flex-col items-center justify-center py-12 border border-slate-800 rounded-xl text-slate-500">
                <XCircle className="w-8 h-8 mb-2" />
                <p className="text-sm">No signal — confluence below threshold</p>
                <p className="text-xs mt-1">This is expected most of the time.</p>
              </div>
            )}
          </div>

          {/* Indicators panel */}
          <div>
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Shield className="w-4 h-4 text-blue-400" />
              Indicators
            </h2>
            {loading && isInitialLoad ? (
              <div className="flex justify-center py-12">
                <Spinner />
              </div>
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-0">
                <IndicatorRow label="EMA 9" value={ind.ema_9} />
                <IndicatorRow label="EMA 20" value={ind.ema_20} />
                <IndicatorRow label="EMA 50" value={ind.ema_50} />
                <IndicatorRow label="RSI 14" value={rsiVal} note={rsiNote} />
                <IndicatorRow
                  label="MACD hist"
                  value={ind.macd_hist}
                  note={ind.macd_hist > 0 ? 'BULLISH' : ind.macd_hist < 0 ? 'BEARISH' : null}
                />
                <IndicatorRow label="StochRSI K" value={ind.stoch_rsi_k} />
                <IndicatorRow label="ATR 14" value={ind.atr_14} />
                <IndicatorRow label="ADX 14" value={ind.adx_14} />
                <IndicatorRow
                  label="+DI / -DI"
                  value={`${plusDiStr} / ${minusDiStr}`}
                  note={ind.plus_di_14 > ind.minus_di_14 ? 'BULLISH' : 'BEARISH'}
                />
                <IndicatorRow
                  label="Supertrend"
                  value={typeof ind.supertrend === 'number' ? ind.supertrend : null}
                  note={stNote}
                />
                <IndicatorRow label="BB %B" value={ind.bb_percent_b} />
                <IndicatorRow
                  label="CMF 20"
                  value={ind.cmf_20}
                  note={ind.cmf_20 > 0.05 ? 'BULLISH' : ind.cmf_20 < -0.05 ? 'BEARISH' : null}
                />
                <IndicatorRow label="MFI 14" value={ind.mfi_14} />
                <IndicatorRow label="Trend Regime" value={trendNote} note={trendNote} />
                <IndicatorRow label="Vol Regime" value={ind.volatility_regime} />
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
