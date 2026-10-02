"""
VM ALGO — WebSocket Connection Manager
=========================================
Manages multiple WebSocket channels. Each channel is keyed by a string
(e.g. "paper:{session_id}", "signals:{symbol}", "user:{user_id}").
Any number of subscribers can join a channel; broadcast sends to all of them.

Used by:
  - Paper trading engine  → channel "paper:{session_id}"
  - Signal feed           → channel "signals:{symbol}:{interval}"
  - Order/position feed   → channel "user:{user_id}"

Design: intentionally simple — no Redis pub/sub yet. This works perfectly
for a single-worker uvicorn deployment (which is what Hostinger provides).
When you scale to multiple workers, replace the in-process dict with a
Redis pub/sub adapter in this file only; the API layer above is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # channel_id -> list[WebSocket]
        self._channels: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, ws: WebSocket, channel: str) -> None:
        await ws.accept()
        self._channels[channel].append(ws)
        log.debug("WS connect: channel=%s  total=%d", channel, len(self._channels[channel]))

    def disconnect(self, ws: WebSocket, channel: str) -> None:
        try:
            self._channels[channel].remove(ws)
        except ValueError:
            pass
        if not self._channels[channel]:
            del self._channels[channel]
        log.debug("WS disconnect: channel=%s", channel)

    async def broadcast(self, channel: str, data: dict) -> None:
        """Send `data` as JSON to every subscriber on `channel`.
        Stale connections are silently removed."""
        payload = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in list(self._channels.get(channel, [])):
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    async def send_personal(self, ws: WebSocket, data: dict) -> None:
        await ws.send_text(json.dumps(data))

    def subscriber_count(self, channel: str) -> int:
        return len(self._channels.get(channel, []))


# Singleton — imported everywhere
manager = ConnectionManager()
