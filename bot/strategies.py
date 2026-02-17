"""
AH Bot Strategy Logic — After-Hours Extreme Move Fade System.

All strategy functions are pure: they take data in and return signals out.
No side effects (no orders, no state mutations).

RULES:
  Mon–Thu: Fade moves ≥ +7% (short) or ≤ −7% (long) from 4 PM close
  Friday:  Long only on ≤ −7% (no shorting into weekend)
  Entry:   ~6:00 PM after monitoring 4:05–6:00 PM
  Exit:    Next open 9:30–9:40 AM
  Stop:    −5% hard stop from entry
  TP:      +2.5% profit ceiling (conditional on spread/volume)
"""
import logging
from datetime import datetime

from bot import config

logger = logging.getLogger("ah_bot.strategies")


# ═══════════════════════════════════════════════════
# Entry signal — called at ~6:00 PM
# ═══════════════════════════════════════════════════

def evaluate_entry_signal(symbol, anchor_close, current_price, is_friday, active_positions_count):
    """Determine whether an extreme AH move warrants a fade entry.

    Args:
        symbol:         Ticker symbol
        anchor_close:   Official 4:00 PM close price
        current_price:  Latest AH price (~6:00 PM)
        is_friday:      True if today is Friday
        active_positions_count: Number of currently open AH positions

    Returns:
        (should_enter, direction, reason)
        should_enter: bool
        direction:    "long" | "short" | None
        reason:       string explanation
    """
    if anchor_close <= 0 or current_price <= 0:
        return False, None, "invalid price data"

    if active_positions_count >= config.MAX_CONCURRENT_POSITIONS:
        return False, None, f"max {config.MAX_CONCURRENT_POSITIONS} concurrent positions reached"

    move_pct = (current_price - anchor_close) / anchor_close
    threshold = config.EXTREME_MOVE_PCT

    if is_friday:
        # Friday: long only on big dips — no shorting into weekend
        if move_pct <= -threshold:
            return True, "long", f"Friday dip fade: {move_pct:+.2%} from close"
        return False, None, f"Friday: move {move_pct:+.2%} does not meet -{threshold:.0%} threshold"
    else:
        # Mon–Thu: fade both directions
        if move_pct >= threshold:
            return True, "short", f"fade up: {move_pct:+.2%} from close"
        elif move_pct <= -threshold:
            return True, "long", f"fade down: {move_pct:+.2%} from close"
        return False, None, f"move {move_pct:+.2%} within ±{threshold:.0%} band"


# ═══════════════════════════════════════════════════
# Position sizing — risk-based
# ═══════════════════════════════════════════════════

def compute_position_size(equity, entry_price, direction, available_cash, slots_remaining):
    """Compute share quantity using TWO constraints and taking the smaller.

    Constraint 1 — Risk-based:
        Risk per trade = RISK_PER_TRADE_PCT * equity
        Max loss per share = entry_price * HARD_STOP_PCT
        qty_risk = risk_dollars / max_loss_per_share

    Constraint 2 — Cash allocation (longs only):
        Split available cash evenly across remaining open slots.
        qty_cash = (available_cash / slots_remaining) / entry_price
        Shorts use margin, so this constraint doesn't apply to them.

    Final qty = min(qty_risk, qty_cash)  for longs
    Final qty = qty_risk                 for shorts (margin-backed)

    Args:
        equity:          Account equity in dollars
        entry_price:     Expected fill price
        direction:       "long" or "short"
        available_cash:  Non-margin buying power (cash only)
        slots_remaining: How many of MAX_CONCURRENT_POSITIONS are still open

    Returns:
        qty: number of shares (int, rounded down)
    """
    if entry_price <= 0 or equity <= 0 or slots_remaining <= 0:
        return 0

    # Constraint 1: risk-based sizing
    risk_dollars = equity * config.RISK_PER_TRADE_PCT
    max_loss_per_share = entry_price * config.HARD_STOP_PCT
    if max_loss_per_share <= 0:
        return 0
    qty_risk = risk_dollars / max_loss_per_share

    if direction == "long":
        # Constraint 2: split available cash evenly across remaining slots
        cash_per_slot = available_cash / slots_remaining
        if cash_per_slot <= 0:
            return 0
        qty_cash = cash_per_slot / entry_price
        qty = int(min(qty_risk, qty_cash))
    else:
        # Shorts use margin — only risk-based constraint
        qty = int(qty_risk)

    return max(qty, 0)


# ═══════════════════════════════════════════════════
# Overnight management — stop loss + profit ceiling
# ═══════════════════════════════════════════════════

def check_hard_stop(entry_price, current_price, direction):
    """Check if the hard stop has been hit.

    Args:
        entry_price:   Price at entry
        current_price: Current AH price
        direction:     "long" or "short"

    Returns:
        (stopped, pnl_pct, reason)
    """
    if entry_price <= 0:
        return False, 0.0, "no entry price"

    if direction == "long":
        pnl_pct = (current_price - entry_price) / entry_price
    else:  # short
        pnl_pct = (entry_price - current_price) / entry_price

    if pnl_pct <= -config.HARD_STOP_PCT:
        return True, pnl_pct, f"HARD STOP: {pnl_pct:+.2%} (limit: -{config.HARD_STOP_PCT:.0%})"

    return False, pnl_pct, f"P&L: {pnl_pct:+.2%}"


def check_profit_ceiling(entry_price, current_price, direction,
                         spread_pct=None, recent_volume=None):
    """Check if the profit ceiling has been reached AND conditions allow exit.

    Profit ceiling exit only fires if:
      - P&L ≥ +2.5%
      - Spread ≤ 0.40%
      - Active volume in last 5 minutes (≥ PROFIT_EXIT_MIN_VOLUME)
      - Not a stale quote

    If conditions not met, returns take_profit=False so we wait for open exit.

    Args:
        entry_price:    Price at entry
        current_price:  Current AH price
        direction:      "long" or "short"
        spread_pct:     Current bid-ask spread as fraction (e.g. 0.003 = 0.3%)
        recent_volume:  Share volume in last ~5 minutes (None if unknown)

    Returns:
        (take_profit, pnl_pct, reason)
    """
    if entry_price <= 0:
        return False, 0.0, "no entry price"

    if direction == "long":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    if pnl_pct < config.PROFIT_CEILING_PCT:
        return False, pnl_pct, f"P&L {pnl_pct:+.2%} below +{config.PROFIT_CEILING_PCT:.1%} ceiling"

    # Profit target reached — check exit conditions
    if spread_pct is not None and spread_pct > config.PROFIT_EXIT_MAX_SPREAD_PCT:
        return False, pnl_pct, (f"TP reached ({pnl_pct:+.2%}) but spread {spread_pct:.2%} > "
                                f"{config.PROFIT_EXIT_MAX_SPREAD_PCT:.2%} — wait for open")

    if recent_volume is not None and recent_volume < config.PROFIT_EXIT_MIN_VOLUME:
        return False, pnl_pct, (f"TP reached ({pnl_pct:+.2%}) but volume {recent_volume} < "
                                f"{config.PROFIT_EXIT_MIN_VOLUME} — wait for open")

    return True, pnl_pct, f"PROFIT CEILING: {pnl_pct:+.2%} — conditions met for exit"


def evaluate_overnight_management(entry_price, current_price, direction,
                                  spread_pct=None, recent_volume=None):
    """Combined overnight check: hard stop first, then profit ceiling.

    Returns:
        (should_exit, pnl_pct, reason)
    """
    # Hard stop takes priority
    stopped, pnl_pct, reason = check_hard_stop(entry_price, current_price, direction)
    if stopped:
        return True, pnl_pct, reason

    # Profit ceiling (conditional)
    take_profit, pnl_pct, reason = check_profit_ceiling(
        entry_price, current_price, direction, spread_pct, recent_volume
    )
    if take_profit:
        return True, pnl_pct, reason

    return False, pnl_pct, reason


# ═══════════════════════════════════════════════════
# Morning exit — always close at open
# ═══════════════════════════════════════════════════

def evaluate_morning_exit(entry_price, current_price, direction):
    """At 9:30 AM: always exit. Compute final P&L.

    Returns:
        (action, pnl_pct, reason)
        action: "close" always for AH positions
    """
    if entry_price <= 0:
        return "none", 0.0, "no position"

    if direction == "long":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    return "close", pnl_pct, f"session end exit: {pnl_pct:+.2%}"


# ═══════════════════════════════════════════════════
# Metrics computation
# ═══════════════════════════════════════════════════

def compute_trade_metrics(entry_price, exit_price, direction, anchor_close,
                          entry_spread_pct=0, exit_spread_pct=0,
                          max_favorable=None, max_adverse=None):
    """Compute per-trade metrics for logging.

    Returns dict with all metrics fields.
    """
    if direction == "long":
        raw_pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0
    else:
        raw_pnl_pct = (entry_price - exit_price) / entry_price if entry_price else 0

    move_4_to_6 = (entry_price - anchor_close) / anchor_close if anchor_close else 0
    net_pnl_pct = raw_pnl_pct - config.ASSUMED_FRICTION_PCT

    return {
        "anchor_close": round(anchor_close, 2),
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "direction": direction,
        "move_4pm_to_entry_pct": round(move_4_to_6, 4),
        "raw_pnl_pct": round(raw_pnl_pct, 4),
        "assumed_friction_pct": config.ASSUMED_FRICTION_PCT,
        "net_pnl_pct": round(net_pnl_pct, 4),
        "entry_spread_pct": round(entry_spread_pct, 4),
        "exit_spread_pct": round(exit_spread_pct, 4),
        "max_favorable_excursion": round(max_favorable, 4) if max_favorable is not None else None,
        "max_adverse_excursion": round(max_adverse, 4) if max_adverse is not None else None,
    }
