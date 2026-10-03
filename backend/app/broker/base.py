from abc import ABC, abstractmethod
from typing import Dict, Any
from app.models.schema import OrderSide, OrderStatus


class BrokerAdapter(ABC):

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> Dict[str, Any]:
        """Places protective stop-loss and take-profit parent/child orders."""
        pass

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Queries broker order book for execution confirmation."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> bool:
        """Kill switch helper to purge open pending orders."""
        pass
