"use client";

import React, { useState, useEffect } from "react";
import { MetricsCard } from "./MetricsCard";
import { EventFeed } from "./EventFeed";
import { KillSwitchModal } from "./KillSwitchModal";

interface SessionData {
  symbol: string;
  equity: number;
  pnl: number;
  trades: number;
  state: "RUNNING" | "STOPPED" | "LOCKED_OUT";
  mode: "PAPER" | "LIVE";
}

export default function Dashboard() {
  const [session, setSession] = useState<SessionData>({
    symbol: "NIFTY",
    equity: 100000.0,
    pnl: -243.25,
    trades: 10,
    state: "RUNNING",
    mode: "PAPER",
  });

  const [events, setEvents] = useState<any[]>([]);
  const [showKillModal, setShowKillModal] = useState(false);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws");
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setEvents((prev) => [data, ...prev.slice(0, 49)]);
    };
    return () => ws.close();
  }, []);

  const handleKillSwitch = async () => {
    await fetch("http://localhost:8000/api/risk/kill-switch", { method: "POST" });
    setSession((prev) => ({ ...prev, state: "LOCKED_OUT" }));
    setShowKillModal(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-8 font-sans">
      {/* Top Header Navigation */}
      <header className="flex justify-between items-center pb-6 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-emerald-400">VM ALGO Quant Suite</h1>
          <p className="text-xs text-slate-400">Production Paper-First Execution Engine</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
            MODE: {session.mode}
          </span>
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
            session.state === "RUNNING" ? "bg-cyan-950 text-cyan-400 border border-cyan-800" : "bg-red-950 text-red-400 border border-red-800"
          }`}>
            STATUS: {session.state}
          </span>
          <button
            onClick={() => setShowKillModal(true)}
            className="bg-red-600 hover:bg-red-700 text-white text-xs font-bold px-4 py-2 rounded transition"
          >
            KILL SWITCH
          </button>
        </div>
      </header>

      {/* Primary Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 my-8">
        <MetricsCard title="EQUITY" value={`₹${session.equity.toLocaleString("en-IN")}`} color="text-slate-100" />
        <MetricsCard
          title="P&L"
          value={`₹${session.pnl.toLocaleString("en-IN")}`}
          color={session.pnl >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <MetricsCard title="EXECUTED TRADES" value={session.trades.toString()} color="text-slate-100" />
        <MetricsCard title="DAILY RISK CAP" value="2.0%" color="text-amber-400" />
      </div>

      {/* Main Real-time Stream Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-slate-200 mb-4">Execution Stream</h2>
          <EventFeed events={events} />
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-slate-200 mb-4">Live Safety Controls</h2>
          <p className="text-sm text-slate-400 mb-4">
            Live broker execution is safely hard-locked server-side.
          </p>
          <button disabled className="w-full bg-slate-800 text-slate-500 font-bold py-3 rounded cursor-not-allowed">
            SWITCH TO LIVE EXECUTION (LOCKED)
          </button>
        </div>
      </div>

      {showKillModal && (
        <KillSwitchModal onClose={() => setShowKillModal(false)} onConfirm={handleKillSwitch} />
      )}
    </div>
  );
}
