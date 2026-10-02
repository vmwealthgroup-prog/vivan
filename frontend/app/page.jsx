'use client';

import { useEffect } from 'react';
import { TrendingUp } from 'lucide-react';

/** Root route — immediately redirects to dashboard (auth guard there sends
 *  unauthenticated users to /login). Shows a brief splash so there's no
 *  blank white flash on slower connections. */
export default function HomePage() {
  useEffect(() => {
    window.location.replace('/dashboard');
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-4">
      <div className="flex items-center gap-3">
        <TrendingUp className="w-8 h-8 text-emerald-400" />
        <span className="text-2xl font-bold text-white tracking-tight">VM ALGO</span>
      </div>
      <div className="animate-spin rounded-full h-6 w-6 border-2 border-emerald-500 border-t-transparent" />
    </div>
  );
}
