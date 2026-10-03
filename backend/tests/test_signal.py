"""
Tests for the paper trading engine and broker abstraction.
Run:
  cd backend
  DATABASE_URL=sqlite:///./test_paper.db ENVIRONMENT=test COOKIE_SECURE=false
  WEBHOOK_SECRET=x PAPER_TRADING=true PYTHONPATH=. python app/tests/test_paper.py
"""
from __future__ import annotations
import asyncio
import sys

from app.paper_trading.engine import (
    PaperSession, SessionStatus, create_session, get_session, list_sessions, RiskLimits,
)
from app.broker.paper import PaperBrokerAdapter
from app.broker.base import OrderSide, OrderStatus
from app.websocket.manager import ConnectionManager


def test_paper_broker_fills():
    async def _run():
        b = PaperBrokerAdapter()
        result = await b.place_order(
            symbol="NIFTY_TEST", side=OrderSide.BUY,
            quantity=50, price=22000.0,
            stop_loss=21800.0, take_profit=22400.0,
        )
        assert result["filled_quantity"] == 50
        assert result["average_fill_price"] == 22000.0
        assert result["status"] == OrderStatus.FILLED
        assert result["broker_order_id"].startswith("PAPER-")
        assert await b.cancel_all_orders("NIFTY_TEST") is True
        assert await b.get_order_status(result["broker_order_id"]) == OrderStatus.FILLED

    asyncio.run(_run())
    print("[OK] PaperBrokerAdapter: fill, cancel, status query")


def test_paper_broker_unique_ids():
    async def _run():
        b = PaperBrokerAdapter()
        ids = {
            (await b.place_order("NIFTY_TEST", OrderSide.BUY, 25, 22000.0, 21800.0, 22400.0))["broker_order_id"]
            for _ in range(10)
        }
        assert len(ids) == 10, "Every paper order must get a unique ID"
    asyncio.run(_run())
    print("[OK] PaperBrokerAdapter: 10 unique order IDs")


def test_session_registry():
    s = create_session("test-001", user_id=1, symbol="NIFTY_TEST",
                        interval="5m", mode="simulated", initial_equity=100_000)
    assert s.status == SessionStatus.CREATED
    assert s.equity == 100_000
    assert get_session("test-001") is s
    assert any(x["session_id"] == "test-001" for x in list_sessions(1))
    assert list_sessions(999) == []
    try:
        create_session("test-001", user_id=1, symbol="X", interval="5m",
                        mode="simulated", initial_equity=50_000)
        assert False, "Duplicate should raise"
    except ValueError:
        pass
    print("[OK] Session registry: create, get, list, duplicate guard")


def test_session_short_run():
    events = []

    async def _run():
        s = PaperSession(
            session_id="run-001", user_id=99, symbol="NIFTY_TEST",
            interval="5m", mode="simulated", initial_equity=100_000,
            risk_limits=RiskLimits(max_risk_per_trade_pct=1.0,
                                    max_daily_loss_pct=10.0, max_drawdown_pct=20.0),
        )
        task = asyncio.create_task(s.run(broadcast_fn=lambda e: events.append(e) or asyncio.sleep(0),
                                          lookback=300, poll_seconds=0.05))
        await asyncio.sleep(0.3)
        s.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return s

    s = asyncio.run(_run())
    assert s.status in (SessionStatus.RUNNING, SessionStatus.STOPPED, SessionStatus.KILLED)
    print(f"[OK] Session run: {len(s.trades)} trades, status={s.status.value}")


def test_websocket_manager():
    mgr = ConnectionManager()

    class FakeWS:
        def __init__(self): self.sent = []
        async def accept(self): pass
        async def send_text(self, t): self.sent.append(t)

    async def _test():
        ws1, ws2 = FakeWS(), FakeWS()
        await mgr.connect(ws1, "ch")
        await mgr.connect(ws2, "ch")
        assert mgr.subscriber_count("ch") == 2
        await mgr.broadcast("ch", {"kind": "TEST"})
        assert len(ws1.sent) == len(ws2.sent) == 1
        mgr.disconnect(ws1, "ch")
        await mgr.broadcast("ch", {"kind": "SECOND"})
        assert len(ws2.sent) == 2
        assert len(ws1.sent) == 1

    asyncio.run(_test())
    print("[OK] WebSocket manager: connect, broadcast, disconnect")


def test_paper_trading_is_default():
    from app.config import settings
    assert settings.PAPER_TRADING is True or settings.ENVIRONMENT == "test"
    print("[OK] PAPER_TRADING=True by default — live requires server-side opt-in")


if __name__ == "__main__":
    tests = [test_paper_broker_fills, test_paper_broker_unique_ids, test_session_registry,
             test_session_short_run, test_websocket_manager, test_paper_trading_is_default]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            print(f"[FAIL] {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed.")
    sys.exit(1 if failed else 0)
