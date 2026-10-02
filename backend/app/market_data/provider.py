"""
VM ALGO — Market Data Provider Abstraction
=============================================
Per the master spec: "All displayed market prices must clearly distinguish
LIVE / DELAYED / SIMULATED / DEMO. Do not hard-code market prices and
present them as live." Every provider below sets `source_label` on its
output; the API layer (app/main.py) forwards that label to the frontend
unchanged so the UI can badge it correctly. This is the fix for the current
frontend, which hard-codes "NIFTY 50 24,850.35 / +1.24%" and labels the
market "Connected" with no real data behind it at all.

Providers:
  SimulatedDataProvider  — deterministic synthetic OHLCV, source_label="SIMULATED".
                            Zero network calls. Used for local dev, tests, and
                            backtesting demos before a real data key is wired up.
  YFinanceDataProvider   — real historical OHLCV via yfinance, source_label="DELAYED"
                            (Yahoo's NSE quotes are exchange-delayed, not tick-live).
                            Requires the `yfinance` package and outbound internet
                            access, neither of which is guaranteed in every
                            deployment target — import is lazy so the rest of the
                            app works without it installed.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN = (9, 15)
NSE_CLOSE = (15, 30)


def _nse_session_index(end: pd.Timestamp, bar_minutes: int, n_bars: int) -> pd.DatetimeIndex:
    """
    Builds a DatetimeIndex of the most recent `n_bars` bars that fall inside
    real NSE sessions (09:15-15:30 IST, Mon-Fri; exchange holidays are NOT
    excluded yet — see rms.py docstring for the same caveat). Walking
    backward day-by-day from `end` so callers get exactly n_bars bars
    regardless of how many trading days that spans.
    """
    bars_per_day = ((NSE_CLOSE[0] * 60 + NSE_CLOSE[1]) - (NSE_OPEN[0] * 60 + NSE_OPEN[1])) // bar_minutes + 1
    timestamps: list[pd.Timestamp] = []
    day = end.tz_convert(IST).normalize() if end.tzinfo else end.tz_localize(IST).normalize()

    while len(timestamps) < n_bars:
        if day.weekday() < 5:  # Mon-Fri
            day_open = day.replace(hour=NSE_OPEN[0], minute=NSE_OPEN[1])
            day_bars = [day_open + timedelta(minutes=bar_minutes * k) for k in range(int(bars_per_day))]
            day_bars = [t for t in day_bars if t.time() <= datetime(2000, 1, 1, *NSE_CLOSE).time()]
            timestamps = day_bars + timestamps
        day = day - timedelta(days=1)

    return pd.DatetimeIndex(timestamps[-n_bars:])

SOURCE_LIVE = "LIVE"
SOURCE_DELAYED = "DELAYED"
SOURCE_SIMULATED = "SIMULATED"
SOURCE_DEMO = "DEMO"


@dataclass
class MarketDataResult:
    symbol: str
    interval: str
    df: pd.DataFrame          # columns: open, high, low, close, volume ; DatetimeIndex
    source_label: str          # one of SOURCE_*
    fetched_at: str


class MarketDataProvider(ABC):
    @abstractmethod
    def get_historical(self, symbol: str, interval: str = "5m", lookback_bars: int = 300) -> MarketDataResult:
        ...

    @abstractmethod
    def get_ltp(self, symbol: str) -> dict:
        """Returns {'symbol', 'ltp', 'source_label', 'timestamp'}."""
        ...


class SimulatedDataProvider(MarketDataProvider):
    """
    Deterministic synthetic OHLCV generator (seeded by symbol name, so the
    same symbol always produces the same series within a session — useful
    for reproducible tests and UI demos without any live data source wired up).
    NOT real market data. Always labeled SIMULATED.
    """

    def __init__(self, base_price: float = 1000.0, annual_vol: float = 0.22):
        self.base_price = base_price
        self.annual_vol = annual_vol

    def _seed_for(self, symbol: str) -> int:
        return abs(hash(symbol)) % (2 ** 31)

    def get_historical(self, symbol: str, interval: str = "5m", lookback_bars: int = 300) -> MarketDataResult:
        rng = np.random.default_rng(self._seed_for(symbol))
        bar_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 375}.get(interval, 5)
        bars_per_year = (252 * 375) / bar_minutes
        sigma = self.annual_vol / math.sqrt(bars_per_year)

        log_returns = rng.normal(loc=0.0, scale=sigma, size=lookback_bars)
        drift = 0.0  # no directional bias — this is a neutral synthetic walk, not a "prediction"
        close = self.base_price * np.exp(np.cumsum(drift + log_returns))

        high = close * (1 + np.abs(rng.normal(0, sigma * 0.6, lookback_bars)))
        low = close * (1 - np.abs(rng.normal(0, sigma * 0.6, lookback_bars)))
        open_ = np.roll(close, 1)
        open_[0] = self.base_price
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        volume = rng.integers(low=1000, high=50000, size=lookback_bars)

        end = pd.Timestamp.now(tz=IST)
        idx = _nse_session_index(end, bar_minutes, lookback_bars)

        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                            "volume": volume}, index=idx)

        return MarketDataResult(symbol=symbol, interval=interval, df=df,
                                 source_label=SOURCE_SIMULATED,
                                 fetched_at=datetime.now(timezone.utc).isoformat())

    def get_ltp(self, symbol: str) -> dict:
        hist = self.get_historical(symbol, interval="1m", lookback_bars=2)
        return {"symbol": symbol, "ltp": float(hist.df["close"].iloc[-1]),
                "source_label": SOURCE_SIMULATED, "timestamp": hist.fetched_at}


class YFinanceDataProvider(MarketDataProvider):
    """
    Real OHLCV via the `yfinance` package (Yahoo Finance). NSE symbols need
    the `.NS` suffix (e.g. "RELIANCE.NS", "^NSEI" for Nifty 50 index).
    Labeled DELAYED, not LIVE — Yahoo's Indian-exchange quotes are not tick
    real-time. For true LIVE data, wire this provider aside a broker feed
    (e.g. Kotak Neo websocket) once broker integration lands.
    """

    _INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}

    def _client(self):
        try:
            import yfinance as yf  # lazy import — optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "yfinance is not installed. Add it to backend/requirements.txt "
                "and `pip install -r requirements.txt`, or use SimulatedDataProvider."
            ) from exc
        return yf

    def get_historical(self, symbol: str, interval: str = "5m", lookback_bars: int = 300) -> MarketDataResult:
        yf = self._client()
        yf_interval = self._INTERVAL_MAP.get(interval, "5m")
        period_days = max(1, math.ceil(lookback_bars * {"1m": 1, "5m": 5, "15m": 15, "60m": 60, "1d": 375}
                                        .get(yf_interval, 5) / 375))
        raw = yf.Ticker(symbol).history(period=f"{min(period_days, 59)}d", interval=yf_interval)
        if raw.empty:
            raise RuntimeError(f"yfinance returned no data for {symbol} ({interval}).")
        raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].tail(lookback_bars)
        return MarketDataResult(symbol=symbol, interval=interval, df=raw,
                                 source_label=SOURCE_DELAYED,
                                 fetched_at=datetime.now(timezone.utc).isoformat())

    def get_ltp(self, symbol: str) -> dict:
        yf = self._client()
        fast = yf.Ticker(symbol).fast_info
        return {"symbol": symbol, "ltp": float(fast["last_price"]), "source_label": SOURCE_DELAYED,
                "timestamp": datetime.now(timezone.utc).isoformat()}


def get_provider(mode: str = "simulated") -> MarketDataProvider:
    if mode == "simulated":
        return SimulatedDataProvider()
    if mode == "yfinance":
        return YFinanceDataProvider()
    raise ValueError(f"Unknown market data provider mode: {mode!r}")
