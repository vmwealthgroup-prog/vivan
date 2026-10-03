'use client'; // 1. Always put 'use client' on line 1 for interactive pages

import { useState } from 'react';
import { useRouter } from 'next/navigation'; // 2. Paste router import here at the top!

export default function LoginPage() {
  const router = useRouter(); // 3. Initialize the router inside your component
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = (e) => {
    e.preventDefault();
    
    // Example: redirect user to dashboard after successful login
    router.push('/dashboard');
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
      <form onSubmit={handleLogin} className="space-y-4 rounded-lg bg-slate-900 p-6">
        <h1 className="text-xl font-bold">Sign In</h1>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded bg-slate-800 p-2 text-white"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded bg-slate-800 p-2 text-white"
        />
        <button type="submit" className="w-full rounded bg-emerald-500 py-2 font-semibold text-slate-950">
          Login
        </button>
      </form>
    </div>
  );
}
