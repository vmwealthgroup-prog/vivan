import math
from app.config import settings


class PositionCalculator:

    @staticmethod
    def calculate_quantity(
        equity: float,
        price: float,
        stop_loss: float,
        lot_size: int = 25,
        risk_pct: float = settings.MAX_RISK_PER_TRADE_PCT,
    ) -> int:
        if equity <= 0 or price <= 0:
            return 0

        risk_amount = equity * (risk_pct / 100.0)
        stop_distance = abs(price - stop_loss)

        if stop_distance <= 0:
            return 0

        raw_units = risk_amount / stop_distance
        
        # Indian Lot Sizing Rules
        lots = math.floor(raw_units / lot_size)
        if lots < 1:
            return 0

        final_quantity = int(lots * lot_size)
        
        # Exposure Cap Safety Check
        total_value = final_quantity * price
        max_allowed_value = equity * (settings.MAX_TOTAL_EXPOSURE_PCT / 100.0)
        
        if total_value > max_allowed_value:
            max_lots = math.floor(max_allowed_value / (price * lot_size))
            final_quantity = int(max_lots * lot_size)

        return final_quantity
