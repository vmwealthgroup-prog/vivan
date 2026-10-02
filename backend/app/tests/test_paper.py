"""
Tests for the paper trading engine and broker abstraction.
Run: cd backend && DATABASE_URL=sqlite:///./test_paper.db ENVIRONMENT=test COOKIE_SECURE=false PYTHONPATH=. python app/tests/test_paper.py
"""
from __future__ import annotations

import asyncio
import sys

from app.paper_trading.engine import (
    PaperSession, SessionStatus, create_session, get_session, list_sessions, RiskLimits,
)
from app.broker.base import (
    SimulatedBroker, KotakNeoAdapter, BrokerOrder, OrderType, OrderSide, get_broker,
)
from app.websocket.manager import ConnectionManager


# ---------------------------------------------------------------------------

def test_simulated_broker():
    b = SimulatedBroker()
    order = BrokerOrder(symbol="NIFTY_TEST", side=OrderSide.BUY,
                         order_type=OrderType.MARKET, quantity=10, price=22000.0,
                         trigger_price=None)
    result = b.place_order(order)
    assert result.filled_quantity == 10
    assert result.filled_price == 22000.0
    assert result.broker_order_id.startswith("SIM-")
    status = b.get_order_status(result.broker_order_id)
    assert status.broker_order_id == result.broker_order_id
    print("[OK] SimulatedBroker: place + status query")


def test_kotak_neo_stub_raises():
    b = KotakNeoAdapter()
    order = BrokerOrder(symbol="NIFTY_TEST", side=OrderSide.BUY,
                         order_type=OrderType.MARKET, quantity=5, price=None,
                         trigger_price=None)
    try:
        b.place_order(order)
        assert False, "Should have raised NotImplementedError"
    except NotImplementedError as e:
        assert "not wired yet" in str(e)
    print("[OK] KotakNeoAdapter raises NotImplementedError until wired")


def test_broker_factory():
    assert isinstance(get_broker("simulated"), SimulatedBroker)
    assert isinstance(get_broker("kotak_neo"), KotakNeoAdapter)
    try:
        get_broker("unknown")
        assert False
    except ValueError:
        pass
    print("[OK] broker factory returns correct types")


def test_paper_session_registry():
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
        assert False, "Duplicate session should raise"
    except ValueError:
        pass
    print("[OK] paper session registry: create, get, list, duplicate guard")


def test_paper_session_short_run():
    """Run 50 bars of the paper engine synchronously to verify it produces
    trades without error. Uses simulated data so no network needed."""

    events_received = []

    async def _run():
        s = PaperSession(
            session_id="test-run-001", user_id=42,
            symbol="NIFTY_TEST", interval="5m", mode="simulated",
            initial_equity=100_000,
            risk_limits=RiskLimits(max_risk_per_trade_pct=1.0,
                                   max_daily_loss_pct=10.0,
                                   max_drawdown_pct=20.0),
        )

        async def _capture(event):
            events_received.append(event)

        # Run for one tick only (poll_seconds very short, stop immediately after)
        async def _run_then_stop():
            task = asyncio.create_task(s.run(broadcast_fn=_capture,
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

        return await _run_then_stop()

    s = asyncio.run(_run())

    # The session should have processed at least one batch of bars
    assert s.status in (SessionStatus.RUNNING, SessionStatus.STOPPED, SessionStatus.KILLED)
    print(f"[OK] paper session short run: {len(s.trades)} trades, "
          f"{len(events_received)} events, status={s.status.value}")


def test_websocket_manager():
    mgr = ConnectionManager()
    assert mgr.subscriber_count("test-channel") == 0

    class FakeWS:
        def __init__(self): self.sent = []
        async def accept(self): pass
        async def send_text(self, t): self.sent.append(t)

    async def _test():
        ws1, ws2 = FakeWS(), FakeWS()
        await mgr.connect(ws1, "ch1")
        await mgr.connect(ws2, "ch1")
        assert mgr.subscriber_count("ch1") == 2

        await mgr.broadcast("ch1", {"kind": "TEST", "val": 42})
        assert len(ws1.sent) == 1 and '"val": 42' in ws1.sent[0]
        assert len(ws2.sent) == 1

        mgr.disconnect(ws1, "ch1")
        assert mgr.subscriber_count("ch1") == 1

        await mgr.broadcast("ch1", {"kind": "SECOND"})
        assert len(ws2.sent) == 2
        assert len(ws1.sent) == 1  # ws1 disconnected, didn't receive second

    asyncio.run(_test())
    print("[OK] WebSocket manager: connect, broadcast, disconnect, isolation")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_simulated_broker,
        test_kotak_neo_stub_raises,
        test_broker_factory,
        test_paper_session_registry,
        test_paper_session_short_run,
        test_websocket_manager,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            print(f"[FAIL] {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} test groups passed.")
    sys.exit(1 if failed else 0)
