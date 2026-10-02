'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { TrendingUp, Lock, Eye, EyeOff, CheckCircle, AlertTriangle } from 'lucide-react';
import { auth, ApiError } from '../lib/api';

function ResetForm() {
  const params = useSearchParams();
  const token = params.get('token');

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    setError('');
    setLoading(true);
    try {
      await auth.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Reset failed. The link may have expired.');
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="text-center py-4">
        <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />
        <p className="text-white font-semibold">Invalid link</p>
        <p className="text-slate-400 text-sm mt-1 mb-4">No reset token found in the URL.</p>
        <a href="/forgot-password" className="text-emerald-400 hover:text-emerald-300 text-sm">Request a new link</a>
      </div>
    );
  }

  if (done) {
    return (
      <div className="text-center py-4">
        <CheckCircle className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
        <h2 className="text-lg font-semibold text-white mb-2">Password updated</h2>
        <p className="text-slate-400 text-sm mb-4">All sessions have been signed out. Sign in with your new password.</p>
        <a href="/login" className="inline-block bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2.5 px-6 rounded-lg transition text-sm">
          Sign in
        </a>
      </div>
    );
  }

  return (
    <>
      <h2 className="text-lg font-semibold text-white mb-5">Set new password</h2>
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">{error}</div>
      )}
      <form onSubmit={handleSubmit} className="space-y-4">
        {[
          { label: 'New password', val: password, set: setPassword, placeholder: 'Min 8 chars, mix letters + numbers' },
          { label: 'Confirm password', val: confirm, set: setConfirm, placeholder: 'Repeat password' },
        ].map(({ label, val, set, placeholder }) => (
          <div key={label}>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">{label}</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input type={showPassword ? 'text' : 'password'} value={val}
                onChange={e => set(e.target.value)} required placeholder={placeholder}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-10 pr-10 py-2.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition" />
              <button type="button" onClick={() => setShowPassword(p => !p)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        ))}
        <button type="submit" disabled={loading}
          className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition text-sm">
          {loading ? 'Updating…' : 'Update password'}
        </button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 mb-4">
            <TrendingUp className="w-7 h-7 text-emerald-400" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">VM ALGO</h1>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
          <Suspense fallback={<div className="py-8 text-center text-slate-400 text-sm">Loading…</div>}>
            <ResetForm />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
