from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas.webhook import WebhookPayload
from app.models.schema import WebhookSignal, StrategySession, Order, OrderSide, OrderStatus, AuditLog
from app.core.idempotency import generate_idempotency_key
from app.core.position_calculator import PositionCalculator
from app.core.risk_engine import RiskEngine
from app.broker.paper import PaperBrokerAdapter
from app.websocket.manager import manager as ws_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Webhook"])

WEBHOOK_CHANNEL = "webhook:events"


def _validate_secret(provided: str) -> bool:
    """Constant-time comparison — prevents timing attacks."""
    expected = settings.WEBHOOK_SECRET
    if not expected:
        log.error("WEBHOOK_SECRET not configured — rejecting all webhook calls.")
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


@router.post("/tradingview", status_code=status.HTTP_200_OK)
async def tradingview_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):

    # 1. Constant-time secret validation
    if not _validate_secret(payload.secret):
        log.warning("Webhook rejected: bad secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid webhook secret.")

    # 2. Idempotency — deduplication
    key = generate_idempotency_key(payload.symbol, payload.timeframe,
                                    payload.bar_time, payload.event)
    if db.query(WebhookSignal).filter_by(idempotency_key=key).first():
        log.info("Duplicate webhook ignored: key=%s", key)
        return {"status": "SKIPPED", "message": "Duplicate event rejected cleanly."}

    # 3. Persist raw payload for audit
    signal = WebhookSignal(
        idempotency_key=key,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        bar_time=payload.bar_time,
        event=payload.event,
        price=payload.price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        raw_payload=payload.model_dump(mode="json"),
    )
    db.add(signal)
    db.commit()

    log.info("Webhook received: symbol=%s event=%s", payload.symbol, payload.event)

    # 4. Active session check
    session = db.query(StrategySession).filter_by(symbol=payload.symbol).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No active session for symbol {payload.symbol}.")

    # 5. Risk gate
    passed, risk_msg = RiskEngine.evaluate_risk(db, session)
    if not passed:
        await ws_manager.broadcast(WEBHOOK_CHANNEL, {
            "type": "RISK_REJECTION", "symbol": payload.symbol, "reason": risk_msg,
        })
        return {"status": "REJECTED_BY_RISK_ENGINE", "reason": risk_msg}

    # 6. Server-side position sizing — never trust client values
    qty = PositionCalculator.calculate_quantity(
        equity=session.current_equity,
        price=payload.price,
        stop_loss=payload.stop_loss,
        lot_size=payload.lot_size,
    )
    if qty <= 0:
        return {"status": "SKIPPED", "reason": "Calculated position size is 0 units."}

    # 7. Execute via paper broker
    adapter = PaperBrokerAdapter()
    side = OrderSide.BUY if payload.event == "BUY" else OrderSide.SELL
    execution_res = await adapter.place_order(
        symbol=payload.symbol, side=side, quantity=qty,
        price=payload.price, stop_loss=payload.stop_loss, take_profit=payload.take_profit,
    )

    # 8. Persist order only after broker confirmation
    order = Order(
        broker_order_id=execution_res["broker_order_id"],
        symbol=payload.symbol, side=side, quantity=qty,
        price=payload.price, stop_loss=payload.stop_loss, take_profit=payload.take_profit,
        status=execution_res["status"], mode="PAPER",
        raw_response=execution_res,
    )
    session.trades_count += 1
    signal.processed = True
    db.add(order)
    db.commit()

    # 9. Broadcast to WS subscribers
    await ws_manager.broadcast(WEBHOOK_CHANNEL, {
        "type": "ORDER_EXECUTED", "symbol": payload.symbol, "side": payload.event,
        "quantity": qty, "price": payload.price,
        "broker_order_id": execution_res["broker_order_id"],
    })

    log.info("Order executed: %s %s qty=%d @ %.2f", payload.event, payload.symbol, qty, payload.price)
    return {"status": "SUCCESS", "broker_order_id": execution_res["broker_order_id"], "quantity": qty}
