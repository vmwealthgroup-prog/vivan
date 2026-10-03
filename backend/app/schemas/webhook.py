from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class WebhookPayload(BaseModel):
    secret: str = Field(..., description="Shared secret key")
    symbol: str = Field(..., min_length=2, max_length=32, example="NIFTY")
    timeframe: str = Field(..., min_length=1, max_length=8, example="5m")
    bar_time: datetime = Field(..., description="UTC timestamp of closed bar")
    event: Literal["BUY", "SELL"] = Field(...)
    
    price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    
    lot_size: int = Field(default=25, gt=0)
    tick_size: float = Field(default=0.05, gt=0)

    @field_validator("stop_loss")
    @classmethod
    def validate_sl(cls, v: float, info):
        price = info.data.get("price")
        event = info.data.get("event")
        if price and event == "BUY" and v >= price:
            raise ValueError("Long stop-loss must be strictly below entry price")
        if price and event == "SELL" and v <= price:
            raise ValueError("Short stop-loss must be strictly above entry price")
        return v

    @field_validator("take_profit")
    @classmethod
    def validate_tp(cls, v: float, info):
        price = info.data.get("price")
        event = info.data.get("event")
        if price and event == "BUY" and v <= price:
            raise ValueError("Long take-profit must be strictly above entry price")
        if price and event == "SELL" and v >= price:
            raise ValueError("Short take-profit must be strictly below entry price")
        return v
