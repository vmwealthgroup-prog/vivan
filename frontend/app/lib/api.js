/**
 * VM ALGO — API client
 * All requests go through here so auth/error handling is centralised.
 * Credentials: "include" on every call → the browser sends the HttpOnly
 * access-token cookie automatically; no token is ever read from JS.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (res.status === 401) {
    // Try to silently refresh once
    const refreshed = await fetch(`${BASE}/api/auth/refresh`, {
      method: 'POST', credentials: 'include',
    });
    if (refreshed.ok) {
      // Retry original request
      const retry = await fetch(`${BASE}${path}`, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
      });
      if (!retry.ok) throw new ApiError(retry.status, await retry.json().catch(() => ({})));
      return retry.json();
    }
    // Refresh failed — redirect to login
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new ApiError(401, { detail: 'Session expired.' });
  }

  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({})));
  return res.json();
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

// Auth
export const auth = {
  register: (name, email, password) =>
    request('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) }),
  login: (email, password, totp_code = null) =>
    request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password, totp_code }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  me: () => request('/api/auth/me'),
  forgotPassword: (email) =>
    request('/api/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (token, new_password) =>
    request('/api/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, new_password }) }),
  verifyEmail: (token) =>
    request('/api/auth/verify-email/confirm', { method: 'POST', body: JSON.stringify({ token }) }),
};

// Quant / trading
export const api = {
  health: () => request('/api/health'),
  signal: (symbol, interval = '5m', mode = 'simulated') =>
    request(`/api/signals/${symbol}?interval=${interval}&mode=${mode}`),
  indicators: (symbol, interval = '5m', mode = 'simulated') =>
    request(`/api/indicators/${symbol}?interval=${interval}&mode=${mode}`),
  marketData: (symbol, interval = '5m', lookback = 300, mode = 'simulated') =>
    request(`/api/market-data/${symbol}?interval=${interval}&lookback=${lookback}&mode=${mode}`),
  backtest: (body) =>
    request('/api/backtest', { method: 'POST', body: JSON.stringify(body) }),
  riskCheck: (body) =>
    request('/api/risk/check', { method: 'POST', body: JSON.stringify(body) }),
};
