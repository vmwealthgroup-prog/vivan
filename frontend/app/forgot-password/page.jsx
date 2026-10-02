'use client';

import { useState } from 'react';
import { TrendingUp, Mail, ArrowLeft, CheckCircle } from 'lucide-react';
import { auth, ApiError } from '../lib/api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await auth.forgotPassword(email);
      setDone(true);
    } catch (err) {
      // Only show errors that aren't the expected "sent if exists" 202
      if (err instanceof ApiError && err.status !== 202) {
        setError(err.message);
      } else {
        setDone(true); // treat any non-network error as done (user-enumeration prevention)
      }
    } finally {
      setLoading(false);
    }
  }

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
          {done ? (
            <div className="text-center py-4">
              <CheckCircle className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
              <h2 className="text-lg font-semibold text-white mb-2">Check your email</h2>
              <p className="text-slate-400 text-sm mb-4">
                If an account exists for <span className="text-white">{email}</span>,
                a reset link has been sent. It expires in 1 hour.
              </p>
              <a href="/login"
                className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300">
                <ArrowLeft className="w-4 h-4" /> Back to login
              </a>
            </div>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-white mb-1">Reset password</h2>
              <p className="text-slate-400 text-sm mb-5">
                Enter your email and we'll send a reset link if the account exists.
              </p>

              {error && (
                <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1.5">Email</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                      required placeholder="trader@example.com"
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-10 pr-4 py-2.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition" />
                  </div>
                </div>
                <button type="submit" disabled={loading}
                  className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition text-sm">
                  {loading ? 'Sending…' : 'Send reset link'}
                </button>
              </form>

              <div className="mt-4 text-center">
                <a href="/login" className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200">
                  <ArrowLeft className="w-4 h-4" /> Back to login
                </a>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
