'use client';

/** Renders a pill badge for the data source label.
 *  Per spec: every displayed price/signal must clearly show its source.
 *  This component is mandatory wherever API data is shown — never skip it. */
export function SourceBadge({ label }) {
  const styles = {
    LIVE:      'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 animate-pulse',
    DELAYED:   'bg-amber-500/15 text-amber-400 border-amber-500/30',
    SIMULATED: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    DEMO:      'bg-purple-500/15 text-purple-400 border-purple-500/30',
  };
  const base = 'text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border';
  return (
    <span className={`${base} ${styles[label] ?? 'bg-slate-700 text-slate-400 border-slate-600'}`}>
      {label ?? 'UNKNOWN'}
    </span>
  );
}
