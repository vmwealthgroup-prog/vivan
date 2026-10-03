import hashlib
from datetime import datetime


def generate_idempotency_key(symbol: str, timeframe: str, bar_time, event: str) -> str:
    ts = bar_time.isoformat() if isinstance(bar_time, datetime) else str(bar_time)
    raw = f"{symbol.upper().strip()}|{timeframe}|{ts}|{event.upper().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]
