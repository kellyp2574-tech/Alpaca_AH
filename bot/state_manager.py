"""
Persistent State Manager — Saves/loads AH bot state to JSON.
Tracks anchors, active positions, overnight P&L extremes, trade history & metrics.
Also maintains running performance totals across all sessions.
"""
import json
import os
from datetime import datetime
from bot.config import STATE_FILE, STATE_DIR, METRICS_FILE, PERFORMANCE_FILE


DEFAULT_STATE = {
    "last_run": None,
    "session_active": False,
    "session_start": None,
    "session_date": None,          # date string "YYYY-MM-DD"

    # 4:00 PM anchor closes: { "AAPL": 150.25, "TSLA": 240.10, ... }
    "anchor_closes": {},

    # Active AH positions:
    # { "AAPL": {
    #     "direction": "long" | "short",
    #     "entry_price": 140.0,
    #     "qty": 14,
    #     "entry_time": "2025-01-15 18:01:02",
    #     "entry_spread_pct": 0.002,
    #     "anchor_close": 150.25,
    #     "max_favorable_pnl": 0.012,   # best P&L seen overnight
    #     "max_adverse_pnl": -0.003,    # worst P&L seen overnight
    # }}
    "positions": {},

    # Trade history (recent entries + exits)
    "trade_history": [],
}


def load_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            saved = json.load(f)
        state = {**DEFAULT_STATE, **saved}
        return state
    return dict(DEFAULT_STATE)


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log_trade(state, action, ticker, qty, price, reason="", direction=None):
    """Append a trade entry to state history."""
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "ticker": ticker,
        "qty": qty,
        "price": price,
        "direction": direction,
        "reason": reason,
    }
    state.setdefault("trade_history", [])
    state["trade_history"].append(entry)
    # Keep last 500 trades
    if len(state["trade_history"]) > 500:
        state["trade_history"] = state["trade_history"][-500:]
    return entry


def update_excursions(position_info, current_pnl_pct):
    """Track max favorable / max adverse excursion for a position."""
    if current_pnl_pct > position_info.get("max_favorable_pnl", 0):
        position_info["max_favorable_pnl"] = current_pnl_pct
    if current_pnl_pct < position_info.get("max_adverse_pnl", 0):
        position_info["max_adverse_pnl"] = current_pnl_pct


def save_trade_metrics(metrics_entry):
    """Append a completed trade's metrics to the metrics JSON file."""
    os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)

    metrics_list = []
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE) as f:
                metrics_list = json.load(f)
        except (json.JSONDecodeError, ValueError):
            metrics_list = []

    metrics_entry["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metrics_list.append(metrics_entry)

    with open(METRICS_FILE, "w") as f:
        json.dump(metrics_list, f, indent=2, default=str)


# ═══════════════════════════════════════════════════
# Running Performance Totals
# ═══════════════════════════════════════════════════

DEFAULT_PERFORMANCE = {
    "last_updated": None,

    # Session counts
    "total_sessions": 0,
    "sessions_with_trades": 0,
    "sessions_no_trades": 0,

    # Trade counts
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "breakeven": 0,

    # By direction
    "long_trades": 0,
    "long_wins": 0,
    "short_trades": 0,
    "short_wins": 0,

    # P&L (net of friction)
    "total_net_pnl_pct": 0.0,      # sum of all net_pnl_pct
    "total_net_pnl_dollars": 0.0,   # sum of all dollar P&L
    "best_trade_pnl_pct": 0.0,
    "best_trade_symbol": None,
    "worst_trade_pnl_pct": 0.0,
    "worst_trade_symbol": None,
    "avg_win_pct": 0.0,
    "avg_loss_pct": 0.0,

    # Excursions
    "avg_mfe_pct": 0.0,            # average max favorable excursion
    "avg_mae_pct": 0.0,            # average max adverse excursion

    # Streaks
    "current_streak": 0,           # positive = wins, negative = losses
    "best_streak": 0,
    "worst_streak": 0,

    # Session history (last 30 nights)
    "session_log": [],
}


def load_performance():
    """Load running performance totals."""
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    if os.path.exists(PERFORMANCE_FILE):
        try:
            with open(PERFORMANCE_FILE) as f:
                saved = json.load(f)
            return {**DEFAULT_PERFORMANCE, **saved}
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(DEFAULT_PERFORMANCE)


def save_performance(perf):
    """Save running performance totals."""
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    perf["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(perf, f, indent=2, default=str)


def update_performance_after_session(session_date, session_trades):
    """Update running totals after a session completes.

    Args:
        session_date:   "YYYY-MM-DD" string
        session_trades: list of trade metric dicts from this session
                        (each has: symbol, direction, net_pnl_pct, entry_price,
                         exit_price, max_favorable_excursion, max_adverse_excursion)
    """
    perf = load_performance()

    perf["total_sessions"] += 1

    if not session_trades:
        perf["sessions_no_trades"] += 1
        # Log the empty session
        perf["session_log"].append({
            "date": session_date,
            "trades": 0,
            "net_pnl_pct": 0.0,
            "net_pnl_dollars": 0.0,
        })
        if len(perf["session_log"]) > 30:
            perf["session_log"] = perf["session_log"][-30:]
        save_performance(perf)
        return perf

    perf["sessions_with_trades"] += 1

    session_pnl_pct = 0.0
    session_pnl_dollars = 0.0
    win_pcts = []
    loss_pcts = []

    for trade in session_trades:
        net_pnl = trade.get("net_pnl_pct", 0)
        direction = trade.get("direction", "long")
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        qty = trade.get("qty", 0)
        mfe = trade.get("max_favorable_excursion")
        mae = trade.get("max_adverse_excursion")

        # Dollar P&L
        if direction == "long":
            dollar_pnl = (exit_price - entry_price) * qty
        else:
            dollar_pnl = (entry_price - exit_price) * qty

        perf["total_trades"] += 1
        session_pnl_pct += net_pnl
        session_pnl_dollars += dollar_pnl
        perf["total_net_pnl_pct"] += net_pnl
        perf["total_net_pnl_dollars"] += dollar_pnl

        # Win / loss
        if net_pnl > 0.0001:
            perf["wins"] += 1
            win_pcts.append(net_pnl)
            perf["current_streak"] = max(perf["current_streak"], 0) + 1
        elif net_pnl < -0.0001:
            perf["losses"] += 1
            loss_pcts.append(net_pnl)
            perf["current_streak"] = min(perf["current_streak"], 0) - 1
        else:
            perf["breakeven"] += 1

        # By direction
        if direction == "long":
            perf["long_trades"] += 1
            if net_pnl > 0.0001:
                perf["long_wins"] += 1
        else:
            perf["short_trades"] += 1
            if net_pnl > 0.0001:
                perf["short_wins"] += 1

        # Best / worst
        symbol = trade.get("symbol", "?")
        if net_pnl > perf["best_trade_pnl_pct"]:
            perf["best_trade_pnl_pct"] = net_pnl
            perf["best_trade_symbol"] = symbol
        if net_pnl < perf["worst_trade_pnl_pct"]:
            perf["worst_trade_pnl_pct"] = net_pnl
            perf["worst_trade_symbol"] = symbol

        # Excursions (running average)
        if mfe is not None and perf["total_trades"] > 0:
            old_avg = perf["avg_mfe_pct"]
            perf["avg_mfe_pct"] = old_avg + (mfe - old_avg) / perf["total_trades"]
        if mae is not None and perf["total_trades"] > 0:
            old_avg = perf["avg_mae_pct"]
            perf["avg_mae_pct"] = old_avg + (mae - old_avg) / perf["total_trades"]

    # Streaks
    perf["best_streak"] = max(perf["best_streak"], perf["current_streak"])
    perf["worst_streak"] = min(perf["worst_streak"], perf["current_streak"])

    # Averages — update running sums, then compute from those only
    perf["_win_sum"] = perf.get("_win_sum", 0) + sum(win_pcts)
    perf["_loss_sum"] = perf.get("_loss_sum", 0) + sum(loss_pcts)

    if perf["wins"] > 0:
        perf["avg_win_pct"] = round(perf["_win_sum"] / perf["wins"], 4)
    if perf["losses"] > 0:
        perf["avg_loss_pct"] = round(perf["_loss_sum"] / perf["losses"], 4)

    # Session log entry
    perf["session_log"].append({
        "date": session_date,
        "trades": len(session_trades),
        "net_pnl_pct": round(session_pnl_pct, 4),
        "net_pnl_dollars": round(session_pnl_dollars, 2),
        "symbols": [t.get("symbol", "?") for t in session_trades],
    })
    if len(perf["session_log"]) > 30:
        perf["session_log"] = perf["session_log"][-30:]

    # Round running totals
    perf["total_net_pnl_pct"] = round(perf["total_net_pnl_pct"], 4)
    perf["total_net_pnl_dollars"] = round(perf["total_net_pnl_dollars"], 2)
    perf["avg_mfe_pct"] = round(perf["avg_mfe_pct"], 4)
    perf["avg_mae_pct"] = round(perf["avg_mae_pct"], 4)

    save_performance(perf)
    return perf


def print_performance_summary(perf=None):
    """Print a formatted performance summary to console/log."""
    if perf is None:
        perf = load_performance()

    total = perf["total_trades"]
    wins = perf["wins"]
    losses = perf["losses"]
    win_rate = (wins / total * 100) if total > 0 else 0
    long_wr = (perf["long_wins"] / perf["long_trades"] * 100) if perf["long_trades"] > 0 else 0
    short_wr = (perf["short_wins"] / perf["short_trades"] * 100) if perf["short_trades"] > 0 else 0

    lines = [
        "",
        "═" * 60,
        "  RUNNING PERFORMANCE TOTALS",
        "═" * 60,
        f"  Sessions:     {perf['total_sessions']} total, "
        f"{perf['sessions_with_trades']} with trades, "
        f"{perf['sessions_no_trades']} empty",
        f"  Trades:       {total} total ({wins}W / {losses}L / {perf['breakeven']}BE)",
        f"  Win rate:     {win_rate:.1f}%",
        f"  Long:         {perf['long_trades']} trades, {long_wr:.1f}% win rate",
        f"  Short:        {perf['short_trades']} trades, {short_wr:.1f}% win rate",
        "",
        f"  Net P&L:      {perf['total_net_pnl_pct']:+.2%} "
        f"(${perf['total_net_pnl_dollars']:+,.2f})",
        f"  Avg win:      {perf['avg_win_pct']:+.2%}",
        f"  Avg loss:     {perf['avg_loss_pct']:+.2%}",
        f"  Best trade:   {perf['best_trade_pnl_pct']:+.2%} ({perf['best_trade_symbol']})",
        f"  Worst trade:  {perf['worst_trade_pnl_pct']:+.2%} ({perf['worst_trade_symbol']})",
        "",
        f"  Avg MFE:      {perf['avg_mfe_pct']:+.2%}",
        f"  Avg MAE:      {perf['avg_mae_pct']:+.2%}",
        f"  Streak:       {perf['current_streak']:+d} "
        f"(best: {perf['best_streak']:+d}, worst: {perf['worst_streak']:+d})",
        "",
    ]

    # Last 5 sessions
    recent = perf.get("session_log", [])[-5:]
    if recent:
        lines.append("  LAST 5 SESSIONS")
        for s in recent:
            syms = ", ".join(s.get("symbols", []))
            lines.append(
                f"    {s['date']}  {s['trades']} trades  "
                f"{s['net_pnl_pct']:+.2%}  ${s['net_pnl_dollars']:+,.2f}  [{syms}]"
            )

    lines.append("═" * 60)
    return "\n".join(lines)
