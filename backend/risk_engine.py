def risk_check(daily_loss_pct, drawdown_pct):
    if daily_loss_pct > 2:
        return False
    if drawdown_pct > 5:
        return False
    return True
