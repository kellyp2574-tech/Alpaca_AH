# Alpaca After-Hours Extreme Move Fade Bot

Automated after-hours trading system that fades extreme moves (≥ ±7% from close) on Nasdaq-100 stocks. Shares the same Alpaca account and API keys as the daytime Leveraged ETF bot.

## Strategy Overview

**Core idea:** When a stock moves ≥ 7% after hours, fade the move (bet on reversion) and exit at next market open.

### Entry Rules

| Day | Move ≥ +7% | Move ≤ -7% |
|-----|-----------|-----------|
| Mon–Thu | **Short** (fade up) | **Long** (fade down) |
| Friday | No short (weekend risk) | **Long only** (weekend reversion) |

### Risk Controls

- **Hard stop:** -5% from entry
- **Profit ceiling:** +2.5% (exits only if spread ≤ 0.40% and active volume)
- **Position sizing:** 1-2% account risk per trade
- **Max concurrent:** 3 positions
- **No entries after 6:00 PM**

## Session Timeline

| Time (ET) | Phase | Action |
|-----------|-------|--------|
| 3:55 PM | **Boot** | Task Scheduler launches bot |
| 4:00 PM | **Anchor** | Store official close for all watchlist symbols |
| 4:05–6:00 PM | **Monitor** | Track AH moves, flag ≥ ±7% extremes |
| ~6:00 PM | **Entry** | Place fade trades (limit orders, extended hours) |
| 6:00 PM–9:30 AM | **Manage** | Overnight hold, hard stop / profit ceiling checks every 5 min |
| 9:30–9:40 AM | **Exit** | Close all AH positions at market open |

## Universe

~85 Nasdaq-100 focused liquid stocks across mega-caps, semis, software, internet, biotech, consumer, and industrials. See `bot/config.py` for the full list.

## Project Structure

```
Alpaca_AH_Bot/
├── bot/
│   ├── config.py           # Schedule, watchlist, strategy params, risk controls
│   ├── alpaca_client.py    # Alpaca API (long, short, extended-hours limit orders)
│   ├── data.py             # Market data (Alpaca primary, Yahoo fallback)
│   ├── strategies.py       # Pure signal logic (entry, stop, TP, sizing, metrics)
│   ├── state_manager.py    # JSON state + trade metrics persistence
│   └── main.py             # 5-phase session orchestrator
├── state/                  # Runtime state, logs, metrics (gitignored)
├── .env.example            # API key template
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys (same as your day bot)
cp .env.example .env
# Edit .env with your Alpaca API key and secret
```

## Usage

```bash
# Check current state and positions
python -m bot.main --status

# Run one manage cycle (testing)
python -m bot.main --once --dry-run

# Dry run — full session, signals only, no orders
python -m bot.main --dry-run

# Normal run — full overnight session
python -m bot.main
```

## Windows Task Scheduler Setup

Create a scheduled task to run Mon–Fri at 3:55 PM:

1. Open Task Scheduler → Create Task
2. **Trigger:** Weekly, Mon–Fri at 3:55 PM
3. **Action:** Start a program
   - Program: `python` (or full path to python.exe)
   - Arguments: `-m bot.main`
   - Start in: `C:\Users\kelly\Alpaca_AH_Bot`
4. **Conditions:** Uncheck "Start only if on AC power"
5. **Settings:** Check "Run whether user is logged on or not"

## Per-Trade Metrics Tracked

Each completed trade logs to `state/logs/trade_metrics.json`:

- % move from 4 PM close to entry
- Entry & exit prices
- Spread at entry/exit
- Max favorable excursion (MFE)
- Max adverse excursion (MAE)
- Net P&L after 0.5% assumed friction

## Extended Hours Notes

- Alpaca **only allows limit orders** during extended hours
- Bot uses `extended_hours=True` on `LimitOrderRequest` for all AH entries/exits
- At 9:30 AM open, `close_position()` handles both long and short exits
- AH trading window: 4:00 PM – 8:00 PM | Pre-market: 4:00 AM – 9:30 AM

## Coordination with Day Bot

Shares the same Alpaca account as `Alpaca_bot`. Separate state files (`ah_bot_state.json` vs `bot_state.json`). The AH bot closes all positions by 9:40 AM before the day bot's first check at 10:30 AM.
