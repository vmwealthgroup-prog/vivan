"""
VM ALGO — Risk Management System (RMS)
==========================================
Every order must pass through RiskManager.validate_order() before it is
allowed to reach the OMS. This module has no broker dependency and no
network calls — it is pure position/account-state arithmetic, so it's fully
unit-testable and safe to run in CI.

Supersedes the placeholder in backend/risk_engine.py (which only checked two
raw percentages with no position-sizing, exposure, or kill-switch logic, and
is not imported anywhere else in the app). That file is left in place
untouched; nothing currently depends on it.

NOT implemented here (needs broker integration first — see backend/app/README
in a later phase): live margin validation against actual broker margin API,
and a real NSE holiday calendar (trading_hours_ok() currently checks
weekday + time window only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class RiskDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class RiskLimits:
    max_risk_per_trade_pct: float = 1.0      # % of equity risked per trade
    max_daily_loss_pct: float = 2.0          # % of equity — hit -> kill switch for the day
    max_drawdown_pct: float = 5.0            # % from equity high-water mark -> kill switch
    max_trades_per_day: int = 10
    max_open_positions: int = 5
    max_exposure_pct: float = 50.0           # % of equity deployed at once (sum of position notional)
    max_single_sector_exposure_pct: float = 25.0


@dataclass
class AccountState:
    equity: float
    equity_high_water_mark: float
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    open_positions: list[dict] = field(default_factory=list)  # [{symbol, sector, notional}]
    kill_switch_engaged: bool = False
    kill_switch_reason: str | None = None


@dataclass
class OrderRequest:
    symbol: str
    sector: str
    direction: str          # "LONG" | "SHORT"
    entry: float
    stop_loss: float
    proposed_quantity: int | None = None  # if None, RMS computes it


@dataclass
class RiskResult:
    decision: RiskDecision
    reasons: list[str]
    approved_quantity: int = 0
    risk_amount: float = 0.0


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    # -- position sizing -----------------------------------------------
    def position_size(self, account: AccountState, entry: float, stop_loss: float) -> int:
        """Risk-only sizing (ignores exposure caps). Kept for direct/simple
        callers; validate_order() below uses sized_quantity() instead, which
        additionally respects the exposure and sector caps — see its
        docstring for why that matters."""
        risk_per_share = abs(entry - stop_loss)
        if risk_per_share <= 0:
            return 0
        risk_budget = account.equity * (self.limits.max_risk_per_trade_pct / 100.0)
        qty = int(risk_budget // risk_per_share)
        return max(qty, 0)

    def sized_quantity(self, account: AccountState, order: OrderRequest) -> tuple[int, list[str]]:
        """
        Position size that jointly respects THREE independent constraints —
        risk-per-trade, total exposure, and sector exposure — taking the
        smallest resulting quantity, rather than sizing purely by risk and
        then rejecting the whole order if a different cap is breached.

        This matters concretely for index/derivative-like instruments: a
        tight ATR-based stop relative to price makes pure risk-based sizing
        (risk_budget / risk_per_share) computes a share count whose notional
        can be several multiples of equity — mathematically correct for the
        risk formula alone, but unfinanceable and a leverage/margin problem.
        Capping jointly against exposure limits, as real risk desks do,
        avoids proposing (and then always rejecting) an oversized order.
        """
        notes: list[str] = []
        risk_per_share = abs(order.entry - order.stop_loss)
        if risk_per_share <= 0 or order.entry <= 0:
            return 0, ["Invalid entry/stop — zero or negative risk-per-share."]

        risk_budget = account.equity * (self.limits.max_risk_per_trade_pct / 100.0)
        qty_risk = int(risk_budget // risk_per_share)

        current_exposure = sum(p.get("notional", 0.0) for p in account.open_positions)
        room_exposure = account.equity * (self.limits.max_exposure_pct / 100.0) - current_exposure
        qty_exposure = max(int(room_exposure // order.entry), 0)

        sector_notional = sum(p.get("notional", 0.0) for p in account.open_positions if p.get("sector") == order.sector)
        room_sector = account.equity * (self.limits.max_single_sector_exposure_pct / 100.0) - sector_notional
        qty_sector = max(int(room_sector // order.entry), 0)

        qty = max(min(qty_risk, qty_exposure, qty_sector), 0)

        if qty_exposure < qty_risk:
            notes.append(f"Size capped by total-exposure limit ({qty_exposure} < risk-based {qty_risk}).")
        if qty_sector < qty_risk:
            notes.append(f"Size capped by sector-exposure limit for {order.sector} "
                          f"({qty_sector} < risk-based {qty_risk}).")
        return qty, notes

    # -- circuit breakers -------------------------------------------------
    def check_kill_switch(self, account: AccountState) -> tuple[bool, str | None]:
        if account.kill_switch_engaged:
            return True, account.kill_switch_reason

        if account.equity_high_water_mark > 0:
            drawdown_pct = 100.0 * (account.equity_high_water_mark - account.equity) / account.equity_high_water_mark
            if drawdown_pct >= self.limits.max_drawdown_pct:
                return True, f"Max drawdown breached: {drawdown_pct:.2f}% >= {self.limits.max_drawdown_pct}%"

        if account.equity > 0:
            daily_loss_pct = -100.0 * account.realized_pnl_today / account.equity
            if daily_loss_pct >= self.limits.max_daily_loss_pct:
                return True, f"Max daily loss breached: {daily_loss_pct:.2f}% >= {self.limits.max_daily_loss_pct}%"

        return False, None

    @staticmethod
    def trading_hours_ok(now: datetime, market_open: time = time(9, 15), market_close: time = time(15, 30)) -> bool:
        """NSE cash/derivatives session window (09:15-15:30 IST). Weekday check +
        time window only — does NOT consult an exchange holiday calendar yet.

        `now` may be naive (assumed to already represent IST wall-clock time —
        this is what the backtester passes, using each historical bar's own
        session timestamp) or timezone-aware (converted to IST here). Do not
        pass a naive UTC datetime.now() from a server that isn't in IST —
        that's the bug this docstring exists to prevent."""
        if now.tzinfo is not None:
            now = now.astimezone(IST)
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        return market_open <= now.time() <= market_close

    # -- main entry point ------------------------------------------------
    def validate_order(self, order: OrderRequest, account: AccountState,
                        now: datetime | None = None) -> RiskResult:
        reasons: list[str] = []
        now = now or datetime.now(IST)  # server tz is not guaranteed to be IST — always default to IST explicitly

        engaged, reason = self.check_kill_switch(account)
        if engaged:
            return RiskResult(RiskDecision.REJECTED, [f"Kill switch active: {reason}"])

        if not self.trading_hours_ok(now):
            return RiskResult(RiskDecision.REJECTED, ["Outside trading hours (or weekend)."])

        if account.trades_today >= self.limits.max_trades_per_day:
            reasons.append(f"Max trades/day reached ({account.trades_today}/{self.limits.max_trades_per_day}).")

        if len(account.open_positions) >= self.limits.max_open_positions:
            reasons.append(f"Max open positions reached ({len(account.open_positions)}/{self.limits.max_open_positions}).")

        if order.proposed_quantity is not None:
            # Manual/override quantity — check it against caps rather than resizing it.
            qty = order.proposed_quantity
            notional = qty * order.entry
            current_exposure = sum(p.get("notional", 0.0) for p in account.open_positions)
            if account.equity and 100.0 * (current_exposure + notional) / account.equity > self.limits.max_exposure_pct:
                reasons.append("Proposed quantity would breach max total exposure.")
            sector_notional = sum(p.get("notional", 0.0) for p in account.open_positions if p.get("sector") == order.sector)
            if account.equity and 100.0 * (sector_notional + notional) / account.equity > self.limits.max_single_sector_exposure_pct:
                reasons.append(f"Proposed quantity would breach max sector exposure for {order.sector}.")
            sizing_notes = []
        else:
            qty, sizing_notes = self.sized_quantity(account, order)

        if qty <= 0:
            reasons.append("Computed position size is zero (stop too close relative to equity/risk budget, "
                            "or no exposure room left under current caps).")

        if reasons:
            return RiskResult(RiskDecision.REJECTED, reasons, approved_quantity=0)

        risk_amount = qty * abs(order.entry - order.stop_loss)
        return RiskResult(RiskDecision.APPROVED, ["All risk checks passed."] + sizing_notes,
                           approved_quantity=qty, risk_amount=risk_amount)
