from sqlalchemy.orm import Session
from app.config import settings
from app.models.schema import StrategySession, SessionState, AuditLog


class RiskEngine:

    @staticmethod
    def evaluate_risk(db: Session, session: StrategySession) -> tuple[bool, str]:
        if session.state == SessionState.LOCKED_OUT:
            return False, "System is in LOCKED_OUT state due to previous risk breach."

        if session.state == SessionState.STOPPED:
            return False, "Strategy session is stopped."

        # Daily Loss Check
        max_allowed_loss = session.starting_equity * (settings.MAX_DAILY_LOSS_PCT / 100.0)
        current_loss = session.starting_equity - session.current_equity

        if current_loss >= max_allowed_loss:
            session.state = SessionState.LOCKED_OUT
            db.add(
                AuditLog(
                    event_type="RISK_BREACH_DAILY_LOSS",
                    message=f"Daily loss limit reached ({current_loss:.2f} INR >= {max_allowed_loss:.2f} INR). System locked.",
                )
            )
            db.commit()
            return False, "Daily loss limit reached. Kill switch activated automatically."

        # Daily Trades Count Check
        if session.trades_count >= settings.MAX_DAILY_TRADES:
            return False, f"Maximum daily trade limit ({settings.MAX_DAILY_TRADES}) reached."

        return True, "Risk checks passed."
