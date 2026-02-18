"""
AH Bot Main Orchestrator — After-Hours Extreme Move Fade System.

Launched daily at 3:55 PM ET by Windows Task Scheduler.

PHASES:
  1. ANCHOR          (4:00 PM)         — Store official close for every watchlist symbol
  2. MONITOR & ENTER (4:05–7:59 PM)    — Scan for ≥ ±7% moves, enter immediately
       "4-6" window  (4:05–5:59 PM)    — Highest AH liquidity, tighter spreads
       "6-8" window  (6:00–7:59 PM)    — Declining liquidity, wider spreads
  3. MANAGE          (8:00 PM–9:30 AM) — Overnight hold, hard stop / profit ceiling
  4. EXIT            (9:30–9:40 AM)    — Close all AH positions at market open

Usage:
    python -m bot.main              # Normal session (3:55 PM -> 9:40 AM)
    python -m bot.main --dry-run    # Show signals without trading
    python -m bot.main --status     # Show current state and positions
    python -m bot.main --once       # Run one manage cycle and exit (testing)
"""
import sys
import time
import logging
import os
from datetime import datetime, timedelta

from bot import config
from bot.state_manager import (
    load_state, save_state, log_trade,
    update_excursions, save_trade_metrics,
    update_performance_after_session, print_performance_summary,
)
from bot import alpaca_client as broker
from bot import data
from bot import strategies

# ═══════════════════════════════════════════════════
# Logging setup
# ═══════════════════════════════════════════════════
os.makedirs(config.LOG_DIR, exist_ok=True)

logger = logging.getLogger("ah_bot")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ═══════════════════════════════════════════════════
# Time helpers
# ═══════════════════════════════════════════════════

def now():
    return datetime.now()


def time_reached(hour, minute):
    """True if current time is at or past hour:minute today."""
    n = now()
    return (n.hour > hour) or (n.hour == hour and n.minute >= minute)


def is_past_entry_cutoff():
    """True if past 8:00 PM (no new entries allowed)."""
    return time_reached(config.ENTRY_CUTOFF_HOUR, config.ENTRY_CUTOFF_MINUTE)


def is_weekday():
    """True if today is a weekday (Mon=0 .. Fri=4)."""
    return now().weekday() < 5


def is_exit_time():
    """True if we're in the 9:30–9:40 AM exit window on a weekday morning."""
    n = now()
    if n.hour >= config.BOT_START_HOUR:
        return False  # still in PM session
    if not is_weekday():
        return False  # weekend — not exit time
    exit_start = n.replace(hour=config.EXIT_HOUR, minute=config.EXIT_MINUTE, second=0)
    exit_end = n.replace(
        hour=config.EXIT_HOUR,
        minute=config.EXIT_MINUTE + config.EXIT_WINDOW_MINUTES,
        second=0,
    )
    return exit_start <= n <= exit_end


def is_session_over():
    """True if past the exit window end (9:40 AM) on a weekday."""
    n = now()
    if n.hour >= config.BOT_START_HOUR:
        return False
    if not is_weekday():
        return False  # weekend — session not over yet
    end_minute = config.EXIT_MINUTE + config.EXIT_WINDOW_MINUTES
    end_hour = config.EXIT_HOUR + (end_minute // 60)
    end_minute = end_minute % 60
    return time_reached(end_hour, end_minute)


def is_friday():
    """True if today is Friday (weekday 4)."""
    return now().weekday() == 4


def _next_weekday_target(hour, minute):
    """Get a datetime for the next occurrence of hour:minute on a weekday.
    If today is a weekday and that time hasn't passed, returns today.
    Otherwise advances to next weekday (skips Sat/Sun)."""
    target = now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    # If already past that time today, move to tomorrow
    if target <= now():
        target += timedelta(days=1)
    # Skip weekend
    while target.weekday() >= 5:  # 5=Sat, 6=Sun
        target += timedelta(days=1)
    return target


def sleep_until(hour, minute):
    """Sleep until the specified time today. Returns immediately if already past."""
    target = now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (target - now()).total_seconds()
    if delta > 0:
        logger.info(f"Waiting until {hour}:{minute:02d} ({delta:.0f}s)...")
        time.sleep(delta)


def sleep_until_next_weekday(hour, minute):
    """Sleep until hour:minute on the next weekday.
    On Friday night this will sleep through the entire weekend until Monday."""
    target = _next_weekday_target(hour, minute)
    delta = (target - now()).total_seconds()
    if delta > 0:
        hours_away = delta / 3600
        logger.info(f"Waiting until {target.strftime('%A %I:%M %p')} "
                    f"({hours_away:.1f} hours / {delta:.0f}s)...")
        time.sleep(delta)


# ═══════════════════════════════════════════════════
# PHASE 1: ANCHOR — Store 4:00 PM close prices
# ═══════════════════════════════════════════════════

def phase_anchor(state):
    """Wait for 4:00 PM, then store official close for all watchlist symbols."""
    logger.info("═" * 60)
    logger.info("PHASE 1: ANCHOR — waiting for 4:00 PM close")

    sleep_until(config.ANCHOR_HOUR, config.ANCHOR_MINUTE)

    # Small delay to let close prices settle
    time.sleep(10)

    logger.info("Fetching 4:00 PM close prices...")
    prices = data.fetch_live_prices(config.WATCHLIST)

    anchor_closes = {}
    for symbol in config.WATCHLIST:
        price = prices.get(symbol)
        if price and price > 0:
            anchor_closes[symbol] = price
        else:
            logger.warning(f"No close price for {symbol} — will skip")

    state["anchor_closes"] = anchor_closes
    logger.info(f"Anchored {len(anchor_closes)}/{len(config.WATCHLIST)} symbols")

    # Log a few examples
    for sym in list(anchor_closes.keys())[:5]:
        logger.info(f"  {sym}: ${anchor_closes[sym]:.2f}")
    if len(anchor_closes) > 5:
        logger.info(f"  ... and {len(anchor_closes) - 5} more")

    save_state(state)


# ═══════════════════════════════════════════════════
# PHASE 2: MONITOR & ENTER — 4:05–7:59 PM
#   Continuously scan for ±7% moves and enter immediately.
#   Tracks trigger_window ("4-6" or "6-8") per trade.
# ═══════════════════════════════════════════════════

def _get_trigger_window():
    """Return '4-6' or '6-8' based on current time."""
    return "4-6" if now().hour < config.LATE_WINDOW_HOUR else "6-8"


def phase_monitor_and_enter(state, dry_run=False):
    """Continuous monitor + immediate entry from 4:05 PM to 8:00 PM.

    Every 60 seconds:
      1. Scan all watchlist symbols for ±7% moves from 4 PM anchor
      2. If an extreme move is found AND we have open slots → enter immediately
      3. Log trigger_window ('4-6' or '6-8') for later analytics

    Microstructure difference:
      4–6 PM: Highest AH liquidity, tighter spreads, fast earnings reaction
      6–8 PM: Declining liquidity, wider spreads, slower drift
    """
    logger.info("═" * 60)
    logger.info("PHASE 2: MONITOR & ENTER — scanning for extreme moves (4:05–7:59 PM)"
                + (" [DRY RUN]" if dry_run else ""))

    sleep_until(config.MONITOR_START_HOUR, config.MONITOR_START_MINUTE)

    anchor_closes = state.get("anchor_closes", {})
    if not anchor_closes:
        logger.error("No anchor closes stored — cannot monitor. Aborting.")
        return

    positions = state.get("positions", {})
    friday = is_friday()

    # Fetch account info once; update available_cash as entries are placed
    try:
        equity = broker.get_equity()
        available_cash = broker.get_cash()
    except Exception as e:
        logger.error(f"Could not fetch account data: {e}")
        return

    # Track which symbols we've already seen as extreme (avoid repeated log spam)
    seen_extreme = set()
    scan_count = 0

    while not is_past_entry_cutoff():
        scan_count += 1
        active_count = len(positions)
        slots_remaining = config.MAX_CONCURRENT_POSITIONS - active_count
        window = _get_trigger_window()

        if scan_count % 10 == 1:  # Log status every ~10 minutes
            logger.info(f"── Scan {scan_count} [{window} window] "
                        f"@ {now().strftime('%I:%M:%S %p')} "
                        f"| {active_count} positions, {slots_remaining} slots ──")

        try:
            symbols_to_check = list(anchor_closes.keys())
            prices = data.fetch_live_prices(symbols_to_check)

            for symbol in symbols_to_check:
                price = prices.get(symbol)
                if not price:
                    continue

                # Already holding this symbol
                if symbol in positions:
                    continue

                anchor = anchor_closes[symbol]
                move_pct = (price - anchor) / anchor

                # Not an extreme move
                if abs(move_pct) < config.EXTREME_MOVE_PCT:
                    if symbol in seen_extreme:
                        logger.info(f"  {symbol} reverted to {move_pct:+.2%} — no longer extreme")
                        seen_extreme.discard(symbol)
                    continue

                # Log first detection
                if symbol not in seen_extreme:
                    logger.info(f"*** EXTREME MOVE [{window}]: {symbol} {move_pct:+.2%} "
                                f"(${anchor:.2f} -> ${price:.2f})")
                    seen_extreme.add(symbol)

                # No slots available — just log and continue monitoring
                if slots_remaining <= 0:
                    continue

                # ── Attempt entry ──
                should_enter, direction, reason = strategies.evaluate_entry_signal(
                    symbol, anchor, price, friday, active_count
                )

                if not should_enter:
                    logger.debug(f"SKIP {symbol}: {reason}")
                    continue

                qty = strategies.compute_position_size(
                    equity, price, direction, available_cash, slots_remaining
                )
                if qty <= 0:
                    logger.info(f"SKIP {symbol}: computed qty=0 "
                                f"(equity=${equity:,.2f} cash=${available_cash:,.2f})")
                    continue

                notional = qty * price
                logger.info(f"ENTRY [{window}]: {direction.upper()} {symbol} "
                            f"qty={qty} @ ${price:.2f} (~${notional:,.0f}) — {reason}")

                if not dry_run:
                    if direction == "long":
                        order = broker.buy_limit_extended(symbol, qty, price)
                    else:
                        order = broker.sell_short_limit_extended(symbol, qty, price)

                    if order:
                        positions[symbol] = {
                            "direction": direction,
                            "entry_price": price,
                            "qty": qty,
                            "entry_time": now().strftime("%Y-%m-%d %H:%M:%S"),
                            "trigger_window": window,
                            "entry_spread_pct": 0,  # TODO: fetch bid-ask if available
                            "anchor_close": anchor,
                            "max_favorable_pnl": 0.0,
                            "max_adverse_pnl": 0.0,
                        }
                        log_trade(state, "ENTRY", symbol, qty, price,
                                  f"[{window}] {reason}", direction)
                        active_count += 1
                        slots_remaining -= 1
                        if direction == "long":
                            available_cash -= notional
                            available_cash = max(available_cash, 0)
                else:
                    logger.info(f"  [DRY RUN] Would {direction} {qty} shares "
                                f"of {symbol} @ ${price:.2f}")
                    active_count += 1
                    slots_remaining -= 1
                    if direction == "long":
                        available_cash -= notional
                        available_cash = max(available_cash, 0)

        except Exception as e:
            logger.error(f"Monitor/entry error: {e}", exc_info=True)

        state["positions"] = positions
        save_state(state)
        time.sleep(config.MONITOR_INTERVAL_SEC)

    # Final summary
    logger.info(f"Monitor & entry window closed (8:00 PM) — "
                f"{len(positions)} active positions")
    for sym, pos in positions.items():
        logger.info(f"  {sym}: {pos['direction']} [{pos.get('trigger_window', '?')}] "
                    f"@ ${pos['entry_price']:.2f}")


# ═══════════════════════════════════════════════════
# PHASE 3: MANAGE — Overnight hold (8:00 PM–9:30 AM)
# ═══════════════════════════════════════════════════

def run_manage_cycle(state, dry_run=False):
    """Single management cycle: check stops and profit ceilings."""
    positions = state.get("positions", {})
    if not positions:
        return

    symbols = list(positions.keys())

    # Use snapshots for real spread/volume data (bid/ask + daily volume)
    snapshots = data.fetch_snapshots(symbols)

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        snap = snapshots.get(symbol, {})
        price = snap.get("price")
        if not price:
            logger.debug(f"No price for {symbol} — skipping manage")
            continue

        entry_price = pos["entry_price"]
        direction = pos["direction"]
        spread_pct = snap.get("spread_pct")
        recent_volume = snap.get("recent_volume")

        # Update excursion tracking
        if direction == "long":
            pnl_pct = (price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - price) / entry_price
        update_excursions(pos, pnl_pct)

        # Check stop + profit ceiling
        should_exit, pnl, reason = strategies.evaluate_overnight_management(
            entry_price, price, direction,
            spread_pct=spread_pct,
            recent_volume=recent_volume,
        )

        if should_exit:
            logger.info(f"MANAGE EXIT: {symbol} {direction} @ ${price:.2f} — {reason}")
            if not dry_run:
                if direction == "long":
                    broker.sell_limit_extended(symbol, pos["qty"], price)
                else:
                    broker.buy_limit_extended(symbol, pos["qty"], price)

                # Log metrics
                metrics = strategies.compute_trade_metrics(
                    entry_price, price, direction, pos.get("anchor_close", 0),
                    entry_spread_pct=pos.get("entry_spread_pct", 0),
                    max_favorable=pos.get("max_favorable_pnl"),
                    max_adverse=pos.get("max_adverse_pnl"),
                )
                metrics["symbol"] = symbol
                metrics["qty"] = pos["qty"]
                metrics["trigger_window"] = pos.get("trigger_window", "unknown")
                metrics["exit_reason"] = reason
                save_trade_metrics(metrics)

                log_trade(state, "EXIT", symbol, pos["qty"], price, reason, direction)
                del positions[symbol]
            else:
                logger.info(f"  [DRY RUN] Would exit {symbol}")
        else:
            logger.debug(f"HOLD {symbol} {direction}: {reason}")

    state["positions"] = positions


def phase_manage(state, dry_run=False):
    """Overnight management loop: 8:00 PM to 9:30 AM.
    On Friday sessions, sleeps through the weekend until Monday morning."""
    logger.info("═" * 60)
    logger.info("PHASE 3: MANAGE — overnight hold" + (" [DRY RUN]" if dry_run else ""))

    positions = state.get("positions", {})

    # If it's a weekend (Friday entries), skip straight to Monday morning
    if not is_weekday() or (is_friday() and time_reached(20, 0)):
        if positions:
            logger.info(f"Weekend detected — holding {len(positions)} positions until Monday")
            logger.info("Sleeping through weekend...")
        sleep_until_next_weekday(config.EXIT_HOUR, config.EXIT_MINUTE - 5)
        return

    loop_count = 0
    while not is_session_over():
        # Check for exit window
        if is_exit_time():
            break

        # If we crossed into the weekend (shouldn't happen Mon-Thu, but safety)
        if not is_weekday():
            logger.info("Weekend reached — sleeping until Monday")
            sleep_until_next_weekday(config.EXIT_HOUR, config.EXIT_MINUTE - 5)
            return

        positions = state.get("positions", {})
        if not positions:
            logger.info("No positions to manage — sleeping until exit time")
            time.sleep(config.OVERNIGHT_INTERVAL_SEC)
            continue

        loop_count += 1
        logger.info(f"── Manage loop {loop_count} @ {now().strftime('%I:%M:%S %p %A')} "
                     f"({len(positions)} positions) ──")

        try:
            run_manage_cycle(state, dry_run=dry_run)
        except Exception as e:
            logger.error(f"Manage error: {e}", exc_info=True)

        save_state(state)
        time.sleep(config.OVERNIGHT_INTERVAL_SEC)


# ═══════════════════════════════════════════════════
# PHASE 4: EXIT — Close all at 9:30–9:40 AM
# ═══════════════════════════════════════════════════

def phase_exit(state, dry_run=False):
    """Morning exit: close all AH positions at market open."""
    logger.info("═" * 60)
    logger.info("PHASE 4: EXIT — morning close-out" + (" [DRY RUN]" if dry_run else ""))

    positions = state.get("positions", {})
    if not positions:
        logger.info("No positions to close")
        return

    # Wait for market open (skips weekend if Friday session)
    logger.info("Waiting for next market open (9:30 AM weekday)...")
    sleep_until_next_weekday(config.EXIT_HOUR, config.EXIT_MINUTE)

    # Small delay to let opening prints settle
    time.sleep(5)

    symbols = list(positions.keys())
    prices = data.fetch_live_prices(symbols)

    for symbol in symbols:
        pos = positions[symbol]
        price = prices.get(symbol, 0)
        entry_price = pos["entry_price"]
        direction = pos["direction"]

        action, pnl_pct, reason = strategies.evaluate_morning_exit(
            entry_price, price, direction
        )

        logger.info(f"MORNING {symbol} {direction}: {reason} "
                     f"(entry=${entry_price:.2f} exit=${price:.2f})")

        if action == "close" and not dry_run:
            # Use close_position which works for both long and short
            broker.close_position(symbol)

            # Log metrics
            metrics = strategies.compute_trade_metrics(
                entry_price, price, direction, pos.get("anchor_close", 0),
                entry_spread_pct=pos.get("entry_spread_pct", 0),
                max_favorable=pos.get("max_favorable_pnl"),
                max_adverse=pos.get("max_adverse_pnl"),
            )
            metrics["symbol"] = symbol
            metrics["qty"] = pos["qty"]
            metrics["trigger_window"] = pos.get("trigger_window", "unknown")
            metrics["exit_reason"] = "morning_closeout"
            save_trade_metrics(metrics)

            log_trade(state, "EXIT", symbol, pos["qty"], price,
                      f"morning closeout: {reason}", direction)
            del positions[symbol]
        elif not dry_run:
            logger.warning(f"Unexpected action '{action}' for {symbol} — forcing close")
            broker.close_position(symbol)
            del positions[symbol]
        else:
            logger.info(f"  [DRY RUN] Would close {symbol} ({direction})")

    state["positions"] = positions
    save_state(state)


# ═══════════════════════════════════════════════════
# Status display
# ═══════════════════════════════════════════════════

def _collect_session_trades(session_date):
    """Read trade_metrics.json and return entries closed during this session."""
    import json
    metrics_list = []
    if os.path.exists(config.METRICS_FILE):
        try:
            with open(config.METRICS_FILE) as f:
                metrics_list = json.load(f)
        except (json.JSONDecodeError, ValueError):
            metrics_list = []
    # Filter to trades closed today (session_date)
    return [m for m in metrics_list if m.get("closed_at", "").startswith(session_date)]


def show_status():
    """Display current AH bot state and Alpaca positions."""
    state = load_state()
    print("\n" + "=" * 60)
    print("  AH BOT — EXTREME MOVE FADE SYSTEM")
    print("=" * 60)
    print(f"  Last run:        {state.get('last_run', 'never')}")
    print(f"  Session active:  {state.get('session_active', False)}")
    print(f"  Session date:    {state.get('session_date', 'N/A')}")

    # Anchors
    anchors = state.get("anchor_closes", {})
    if anchors:
        print(f"\n  ANCHORED CLOSES ({len(anchors)} symbols)")
        for sym in list(anchors.keys())[:10]:
            print(f"    {sym:<6} ${anchors[sym]:.2f}")
        if len(anchors) > 10:
            print(f"    ... +{len(anchors) - 10} more")

    # AH positions
    positions = state.get("positions", {})
    if positions:
        print(f"\n  ACTIVE AH POSITIONS")
        for sym, info in positions.items():
            d = info.get("direction", "?")
            ep = info.get("entry_price", 0)
            q = info.get("qty", 0)
            mfe = info.get("max_favorable_pnl", 0)
            mae = info.get("max_adverse_pnl", 0)
            print(f"    {sym:<6} {d:<5} qty={q} entry=${ep:.2f} "
                  f"MFE={mfe:+.2%} MAE={mae:+.2%}")
    else:
        print(f"\n  No active AH positions")

    # Alpaca account
    try:
        account = broker.get_account()
        print(f"\n  ALPACA ACCOUNT")
        print(f"  Equity:        ${float(account.equity):,.2f}")
        print(f"  Cash:          ${float(account.cash):,.2f}")
        print(f"  Buying power:  ${float(account.buying_power):,.2f}")

        all_pos = broker.get_all_positions()
        if all_pos:
            print(f"\n  ALL POSITIONS (account-wide)")
            for pos in all_pos:
                pnl = float(pos.unrealized_pl)
                pnl_pct = float(pos.unrealized_plpc) * 100
                print(f"    {pos.symbol:<6} {float(pos.qty):>10.4f} shares  "
                      f"${float(pos.market_value):>10,.2f}  "
                      f"P&L: {pnl:>+8,.2f} ({pnl_pct:>+5.1f}%)")
    except Exception as e:
        print(f"\n  Could not fetch Alpaca data: {e}")

    # Recent trades
    history = state.get("trade_history", [])
    if history:
        print(f"\n  RECENT AH TRADES (last 10)")
        for t in history[-10:]:
            d = t.get("direction", "")
            print(f"    {t['timestamp']}  {t['action']:<6} {d:<5} {t['ticker']:<6} "
                  f"qty={t.get('qty', '?')} @ ${t.get('price', 0):.2f}  "
                  f"{t.get('reason', '')}")

    print("=" * 60)

    # Running performance totals
    summary = print_performance_summary()
    print(summary)


# ═══════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════

def run_session(dry_run=False):
    """Full session: anchor -> monitor -> entry -> manage -> exit."""
    state = load_state()
    today = now().strftime("%Y-%m-%d")

    logger.info("═" * 60)
    logger.info("AH BOT SESSION START" + (" [DRY RUN]" if dry_run else ""))
    logger.info(f"Date: {today} ({'Friday' if is_friday() else now().strftime('%A')})")
    logger.info(f"Watchlist: {len(config.WATCHLIST)} symbols")
    logger.info(f"Threshold: ±{config.EXTREME_MOVE_PCT:.0%} | "
                f"Stop: -{config.HARD_STOP_PCT:.0%} | "
                f"TP: +{config.PROFIT_CEILING_PCT:.1%}")
    logger.info(f"Max positions: {config.MAX_CONCURRENT_POSITIONS} | "
                f"Risk/trade: {config.RISK_PER_TRADE_PCT:.0%}")

    # Log account info
    try:
        equity = broker.get_equity()
        cash = broker.get_cash()
        logger.info(f"Account: equity=${equity:,.2f} cash=${cash:,.2f}")
    except Exception as e:
        logger.error(f"Could not fetch account info: {e}")

    state["session_active"] = True
    state["session_start"] = now().strftime("%Y-%m-%d %H:%M:%S")
    state["session_date"] = today
    state["positions"] = {}
    state["anchor_closes"] = {}
    save_state(state)

    try:
        # Phase 1: Anchor at 4:00 PM
        phase_anchor(state)

        # Phase 2: Monitor & Enter 4:05–7:59 PM (immediate entry on ±7% moves)
        phase_monitor_and_enter(state, dry_run=dry_run)

        # Phase 3: Manage overnight 8:00 PM–9:30 AM
        phase_manage(state, dry_run=dry_run)

        # Phase 4: Exit at 9:30 AM
        phase_exit(state, dry_run=dry_run)

    except KeyboardInterrupt:
        logger.info("Session interrupted by user")
    except Exception as e:
        logger.error(f"Unhandled error in session: {e}", exc_info=True)
    finally:
        state["session_active"] = False
        save_state(state)

    # ── Session performance update ──
    try:
        session_trades = _collect_session_trades(today)
        perf = update_performance_after_session(today, session_trades)
        summary = print_performance_summary(perf)
        logger.info(summary)
        print(summary)
    except Exception as e:
        logger.error(f"Could not update performance: {e}", exc_info=True)

    logger.info("AH BOT SESSION COMPLETE")
    logger.info("═" * 60)


def run_once(dry_run=False):
    """Run a single manage cycle — useful for testing overnight management."""
    state = load_state()
    logger.info("═" * 60)
    logger.info("AH BOT SINGLE MANAGE CYCLE" + (" [DRY RUN]" if dry_run else ""))

    try:
        equity = broker.get_equity()
        cash = broker.get_cash()
        logger.info(f"Account: equity=${equity:,.2f} cash=${cash:,.2f}")
    except Exception as e:
        logger.error(f"Could not fetch account info: {e}")

    run_manage_cycle(state, dry_run=dry_run)
    save_state(state)

    logger.info("SINGLE CYCLE COMPLETE")
    logger.info("═" * 60)


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    elif "--once" in sys.argv:
        run_once(dry_run="--dry-run" in sys.argv)
    elif "--dry-run" in sys.argv:
        run_session(dry_run=True)
    else:
        run_session(dry_run=False)
