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
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/webhook", tags=["Webhook"])


@router.post("/tradingview", status_code=status.HTTP_200_OK)
async def tradingview_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    # 1. Security Check: Shared Secret Validation
    if payload.secret != settings.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret key signature.",
        )

    # 2. Idempotency Key Generation & Deduplication Check
    key = generate_idempotency_key(
        payload.symbol, payload.timeframe, payload.bar_time, payload.event
    )
    existing_signal = db.query(WebhookSignal).filter_by(idempotency_key=key).first()
    if existing_signal:
        return {"status": "SKIPPED", "message": "Duplicate event rejected cleanly."}

    # 3. Store Original Payload Audit Signal
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

    # 4. Fetch Strategy Session Context
    session = db.query(StrategySession).filter_by(symbol=payload.symbol).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active session configured for symbol {payload.symbol}.",
        )

    # 5. Evaluate Risk Control Framework
    passed, risk_msg = RiskEngine.evaluate_risk(db, session)
    if not passed:
        await ws_manager.broadcast({
            "type": "RISK_REJECTION",
            "symbol": payload.symbol,
            "reason": risk_msg
        })
        return {"status": "REJECTED_BY_RISK_ENGINE", "reason": risk_msg}

    # 6. Sizing Calculation
    qty = PositionCalculator.calculate_quantity(
        equity=session.current_equity,
        price=payload.price,
        stop_loss=payload.stop_loss,
        lot_size=payload.lot_size,
    )

    if qty <= 0:
        return {"status": "SKIPPED", "reason": "Calculated position size is 0 units."}

    # 7. Execute via Paper Broker
    adapter = PaperBrokerAdapter()
    side = OrderSide.BUY if payload.event == "BUY" else OrderSide.SELL
    
    execution_res = await adapter.place_order(
        symbol=payload.symbol,
        side=side,
        quantity=qty,
        price=payload.price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
    )

    # 8. Persist Executed Order
    order = Order(
        broker_order_id=execution_res["broker_order_id"],
        symbol=payload.symbol,
        side=side,
        quantity=qty,
        price=payload.price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        status=execution_res["status"],
        mode="PAPER",
        raw_response=execution_res,
    )
    
    session.trades_count += 1
    signal.processed = True
    db.add(order)
    db.commit()

    # 9. Real-time Event Streaming
    await ws_manager.broadcast({
        "type": "ORDER_EXECUTED",
        "symbol": payload.symbol,
        "side": payload.event,
        "quantity": qty,
        "price": payload.price,
        "broker_order_id": execution_res["broker_order_id"]
    })

    return {
        "status": "SUCCESS",
        "broker_order_id": execution_res["broker_order_id"],
        "quantity": qty,
    }
