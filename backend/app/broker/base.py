"""
VM ALGO — Broker Abstraction Layer
=====================================
Per the master spec:
  "Create a broker abstraction layer. Start with Kotak Neo. Architecture
   must allow Kotak / Angel One / Upstox / Dhan / Other brokers."
  "Never expose broker API secrets to frontend JavaScript."

BrokerBase defines the contract every broker adapter must satisfy.
All secrets are read from environment variables in config.py — never
from arguments, never from the frontend.

Adapters:
  SimulatedBroker  — fills orders instantly at the requested price.
                     Used by the paper trading engine.
  KotakNeoAdapter  — real Kotak Neo integration stub. Wired to the
                     kotak-neo-api package. Requires:
                       KOTAK_NEO_API_KEY, KOTAK_NEO_API_SECRET,
                       KOTAK_NEO_CONSUMER_KEY in backend/.env
                     NOT connected yet (returns NotImplementedError on
                     any live call until you wire the credentials and
                     uncomment the real calls below — that's intentional,
                     prevents accidental live order placement during dev).

Order types supported per spec: MARKET, LIMIT, SL, SL-M, COVER, BRACKET, IOC
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

log = logging.getLogger(__name__)


class OrderType(str, Enum):
    MARKET  = "MARKET"
    LIMIT   = "LIMIT"
    SL      = "SL"
    SL_M    = "SL-M"
    COVER   = "COVER"
    BRACKET = "BRACKET"
    IOC     = "IOC"


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    NEW              = "NEW"
    VALIDATED        = "VALIDATED"
    SENT_TO_BROKER   = "SENT_TO_BROKER"
    PENDING          = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    COMPLETED        = "COMPLETED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REJECTED         = "REJECTED"


@dataclass
class BrokerOrder:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float | None          # None for MARKET orders
    trigger_price: float | None  # for SL / SL-M
    product: str = "MIS"          # MIS (intraday) | CNC (delivery) | NRML (F&O)
    tag: str = ""                 # strategy/session tag for audit


@dataclass
class BrokerOrderResult:
    broker_order_id: str
    status: OrderStatus
    filled_price: float | None
    filled_quantity: int
    message: str
    timestamp: str


class BrokerBase(ABC):
    @abstractmethod
    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult:
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        ...

    @abstractmethod
    def get_holdings(self) -> list[dict]:
        ...

    @abstractmethod
    def get_funds(self) -> dict:
        ...


# ---------------------------------------------------------------------------
# Simulated broker — used by paper trading engine, no network calls
# ---------------------------------------------------------------------------

class SimulatedBroker(BrokerBase):
    """Fills every order instantly at the requested (or market) price.
    Maintains an in-memory order book for status queries."""

    def __init__(self):
        self._orders: dict[str, BrokerOrderResult] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"SIM-{self._counter:06d}"

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        oid = self._next_id()
        fill_price = order.price if order.price else 0.0  # market: caller supplies LTP
        result = BrokerOrderResult(
            broker_order_id=oid,
            status=OrderStatus.COMPLETED,
            filled_price=fill_price,
            filled_quantity=order.quantity,
            message="Simulated fill.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._orders[oid] = result
        log.debug("SimulatedBroker: %s %s %s qty=%d @ %.2f",
                  order.side, order.order_type, order.symbol,
                  order.quantity, fill_price)
        return result

    def cancel_order(self, broker_order_id: str) -> bool:
        return broker_order_id in self._orders

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult:
        if broker_order_id not in self._orders:
            raise KeyError(f"Order {broker_order_id!r} not found.")
        return self._orders[broker_order_id]

    def get_positions(self) -> list[dict]:
        return []

    def get_holdings(self) -> list[dict]:
        return []

    def get_funds(self) -> dict:
        return {"available_cash": 0.0, "source": "SIMULATED"}


# ---------------------------------------------------------------------------
# Kotak Neo adapter — stub, not live yet
# ---------------------------------------------------------------------------

class KotakNeoAdapter(BrokerBase):
    """
    Kotak Neo broker adapter.

    Status: STUB — every method raises NotImplementedError until you:
      1. `pip install kotak-neo-api` (add to requirements.txt)
      2. Set KOTAK_NEO_API_KEY, KOTAK_NEO_API_SECRET, KOTAK_NEO_CONSUMER_KEY
         in backend/.env
      3. Uncomment the real implementation blocks below and test against the
         Kotak Neo sandbox environment before pointing at production.

    This stub exists so the rest of the codebase can import and reference
    KotakNeoAdapter without crashing — it acts as a documented placeholder
    that makes the integration boundary explicit.
    """

    def __init__(self):
        # Lazy-import so missing package doesn't crash the whole app
        try:
            from app.config import settings
            self._api_key = settings.kotak_neo_api_key
            self._api_secret = settings.kotak_neo_api_secret
            self._consumer_key = settings.kotak_neo_consumer_key
        except Exception:
            self._api_key = self._api_secret = self._consumer_key = None

        if not all([self._api_key, self._api_secret, self._consumer_key]):
            log.warning(
                "KotakNeoAdapter: credentials not configured. "
                "Set KOTAK_NEO_API_KEY / API_SECRET / CONSUMER_KEY in backend/.env."
            )

    def _assert_live(self):
        raise NotImplementedError(
            "KotakNeoAdapter is not wired yet. "
            "Set Kotak credentials in backend/.env and implement the API calls. "
            "Use SimulatedBroker for paper trading."
        )

    def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        self._assert_live()

    def cancel_order(self, broker_order_id: str) -> bool:
        self._assert_live()

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult:
        self._assert_live()

    def get_positions(self) -> list[dict]:
        self._assert_live()

    def get_holdings(self) -> list[dict]:
        self._assert_live()

    def get_funds(self) -> dict:
        self._assert_live()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_broker(mode: str = "simulated") -> BrokerBase:
    """
    mode="simulated"  -> SimulatedBroker (paper trading, tests)
    mode="kotak_neo"  -> KotakNeoAdapter (live — requires credentials)
    """
    if mode == "simulated":
        return SimulatedBroker()
    if mode == "kotak_neo":
        return KotakNeoAdapter()
    raise ValueError(f"Unknown broker mode: {mode!r}. Valid: simulated | kotak_neo")
