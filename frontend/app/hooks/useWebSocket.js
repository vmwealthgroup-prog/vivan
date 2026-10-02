'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
  .replace(/^http/, 'ws');

/**
 * useWebSocket(path)
 * Connects to `WS_BASE + path`, auto-reconnects on drop with exponential
 * backoff (max 30s). Returns { events, status, send, reset }.
 *
 * events  — array of parsed JSON objects received, newest last
 * status  — "connecting" | "open" | "closed" | "error"
 * send(obj) — sends JSON to the server
 * reset() — clears the event log
 */
export function useWebSocket(path, { maxEvents = 200 } = {}) {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState('connecting');
  const wsRef = useRef(null);
  const backoffRef = useRef(1000);
  const pathRef = useRef(path);
  const unmountedRef = useRef(false);

  useEffect(() => { pathRef.current = path; }, [path]);

  const connect = useCallback(() => {
    if (unmountedRef.current) return;
    setStatus('connecting');
    const url = `${WS_BASE}${pathRef.current}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return; }
      setStatus('open');
      backoffRef.current = 1000;
      // Start keepalive ping every 25s
      ws._pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 25_000);
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.kind === 'pong') return;
        setEvents(prev => {
          const next = [...prev, data];
          return next.length > maxEvents ? next.slice(-maxEvents) : next;
        });
      } catch { /* non-JSON frame — ignore */ }
    };

    ws.onerror = () => setStatus('error');

    ws.onclose = () => {
      clearInterval(ws._pingInterval);
      if (unmountedRef.current) return;
      setStatus('closed');
      // Reconnect with backoff
      setTimeout(() => {
        backoffRef.current = Math.min(backoffRef.current * 1.5, 30_000);
        connect();
      }, backoffRef.current);
    };
  }, [maxEvents]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (wsRef.current) {
        clearInterval(wsRef.current._pingInterval);
        wsRef.current.close();
      }
    };
  }, [connect, path]);

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === WebSocket.OPEN)
      wsRef.current.send(JSON.stringify(obj));
  }, []);

  const reset = useCallback(() => setEvents([]), []);

  return { events, status, send, reset };
}
