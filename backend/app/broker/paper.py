import uuid
from typing import Dict, Any
from app.broker.base import BrokerAdapter
from app.models.schema import OrderSide, OrderStatus


class PaperBrokerAdapter(BrokerAdapter):

    def __init__(self, execution_delay_ms: int = 10):
        self.execution_delay_ms = execution_delay_ms

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> Dict[str, Any]:
        # Simulated Paper Execution with Instant Settlement
        order_id = f"PAPER-{uuid.uuid4().hex[:12].upper()}"
        return {
            "broker_order_id": order_id,
            "status": OrderStatus.FILLED,
            "symbol": symbol,
            "side": side.value,
            "filled_quantity": quantity,
            "average_fill_price": price,
            "message": "Paper trade simulated and filled cleanly.",
        }

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return OrderStatus.FILLED

    async def cancel_all_orders(self, symbol: str) -> bool:
        return True
