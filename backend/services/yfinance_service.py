import yfinance as yf
import pandas as pd

SYMBOL_MAP = {
    "NIFTY_TEST": "^NSEI",
    "BANKNIFTY_TEST": "^NSEBANK",
    "RELIANCE_TEST": "RELIANCE.NS"
}

def get_yfinance_market_data(symbol_key: str, interval: str = "5m"):
    ticker_symbol = SYMBOL_MAP.get(symbol_key, symbol_key)
    ticker = yf.Ticker(ticker_symbol)

    # Valid yfinance intervals: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d
    period = "1d" if interval in ["1m", "2m", "5m"] else "5d"
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"No data returned for ticker {ticker_symbol}")

    latest = df.iloc[-1]
    prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Open"]
    
    # Calculate basic EMA indicator example
    df['ema_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['ema_20'] = df['Close'].ewm(span=20, adjust=False).mean()

    return {
        "symbol": symbol_key,
        "yahoo_ticker": ticker_symbol,
        "latest": {
            "close": float(latest["Close"]),
            "open": float(latest["Open"]),
            "high": float(latest["High"]),
            "low": float(latest["Low"]),
            "volume": int(latest["Volume"]),
            "change": float(latest["Close"] - prev_close),
            "change_pct": float(((latest["Close"] - prev_close) / prev_close) * 100),
            "ema_9": float(df['ema_9'].iloc[-1]),
            "ema_20": float(df['ema_20'].iloc[-1]),
        },
        "source_label": "Yahoo Finance (15m delayed)"
    }
