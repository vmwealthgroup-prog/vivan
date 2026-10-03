from fastapi import APIRouter, HTTPException, Query
from services.yfinance_service import get_yfinance_market_data

router = APIRouter(prefix="/api", tags=["Market Data"])

@router.get("/indicators")
async def get_indicators(
    symbol: str = Query("NIFTY_TEST"),
    interval: str = Query("5m"),
    mode: str = Query("simulated")
):
    if mode == "yfinance":
        try:
            return get_yfinance_market_data(symbol, interval)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Fallback to simulated data or other data sources
    return {"status": "simulated", "symbol": symbol}
