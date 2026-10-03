import pytest
from app.core.position_calculator import PositionCalculator
from app.schemas.webhook import WebhookPayload


def test_position_sizing_lot_size_rounding():
    # Equity: 100,000 INR, Risk: 1%, Stop Distance: 10 INR, Lot Size: 25 (NIFTY)
    # Risk Amount = 1,000 INR -> Raw units = 100 -> Lots = 100/25 = 4 -> Qty = 100
    qty = PositionCalculator.calculate_quantity(
        equity=100000.0, price=24000.0, stop_loss=23990.0, lot_size=25, risk_pct=1.0
    )
    assert qty == 100


def test_invalid_stop_loss_rejection():
    with pytest.raises(ValueError):
        WebhookPayload(
            secret="SHARED_WEBHOOK_SECRET_KEY_12345",
            symbol="NIFTY",
            timeframe="5m",
            bar_time="2026-10-02T10:00:00Z",
            event="BUY",
            price=24000.0,
            stop_loss=24100.0,  # Invalid: Long SL higher than entry price
            take_profit=24200.0,
        )
