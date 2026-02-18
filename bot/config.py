"""
AH Bot Configuration — After-Hours Extreme Move Fade System.
Shares Alpaca account/API keys with the daytime leveraged ETF bot.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════
# Alpaca API (same account/keys as the day bot)
# ═══════════════════════════════════════════════════
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# ═══════════════════════════════════════════════════
# Schedule (all times Eastern)
#   Bot starts:       3:55 PM  (Task Scheduler)
#   Anchor:           4:00 PM  (store official close)
#   Monitor & Entry:  4:05–7:59 PM  (detect ±7% moves, enter immediately)
#     "4-6" window:   4:05–5:59 PM  (highest AH liquidity, tighter spreads)
#     "6-8" window:   6:00–7:59 PM  (declining liquidity, wider spreads)
#   No new entries:   8:00 PM onward
#   Manage:           8:00 PM–9:30 AM (overnight hold, stop/TP mgmt)
#   Exit window:      9:30–9:40 AM next trading day
# ═══════════════════════════════════════════════════
BOT_START_HOUR = 15
BOT_START_MINUTE = 55

ANCHOR_HOUR = 16              # 4:00 PM — store official close
ANCHOR_MINUTE = 0

MONITOR_START_HOUR = 16       # 4:05 PM — begin monitoring + entries
MONITOR_START_MINUTE = 5

ENTRY_CUTOFF_HOUR = 20        # 8:00 PM — no new entries after this
ENTRY_CUTOFF_MINUTE = 0

# Window boundary for analytics: 4-6 vs 6-8
LATE_WINDOW_HOUR = 18         # 6:00 PM — boundary between "4-6" and "6-8" windows

EXIT_HOUR = 9                 # 9:30 AM next day — exit window
EXIT_MINUTE = 30
EXIT_WINDOW_MINUTES = 10      # 9:30–9:40 AM

MONITOR_INTERVAL_SEC = 60     # check every 60s during 4:05–7:59 PM
OVERNIGHT_INTERVAL_SEC = 300  # check every 5 min overnight (manage only)

# ═══════════════════════════════════════════════════
# Universe — Nasdaq-100 only (v1)
# ~100 symbols — keeps rate limits comfortable
# ═══════════════════════════════════════════════════
WATCHLIST = [
    # ── Mega-caps ──
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "AMZN",   # Amazon
    "NVDA",   # NVIDIA
    "META",   # Meta Platforms
    "GOOGL",  # Alphabet Class A
    "GOOG",   # Alphabet Class C
    "TSLA",   # Tesla
    "AVGO",   # Broadcom
    "COST",   # Costco

    # ── Semis ──
    "AMD",    # Advanced Micro Devices
    "QCOM",   # Qualcomm
    "TXN",    # Texas Instruments
    "MU",     # Micron Technology
    "LRCX",   # Lam Research
    "KLAC",   # KLA Corporation
    "AMAT",   # Applied Materials
    "MCHP",   # Microchip Technology
    "NXPI",   # NXP Semiconductors
    "ON",     # ON Semiconductor
    "MRVL",   # Marvell Technology
    "ARM",    # ARM Holdings
    "ADI",    # Analog Devices
    "INTC",   # Intel

    # ── Software / Cloud ──
    "ADBE",   # Adobe
    "INTU",   # Intuit
    "PANW",   # Palo Alto Networks
    "CRWD",   # CrowdStrike
    "SNOW",   # Snowflake
    "WDAY",   # Workday
    "DDOG",   # Datadog
    "TEAM",   # Atlassian
    "SNPS",   # Synopsys
    "CDNS",   # Cadence Design
    "ZM",     # Zoom Video
    "TTD",    # The Trade Desk
    "PLTR",   # Palantir
    "ADSK",   # Autodesk
    "ANSS",   # ANSYS
    "ZS",     # Zscaler
    "MDB",    # MongoDB
    "CTSH",   # Cognizant
    "CDW",    # CDW Corporation
    "EA",     # Electronic Arts
    "TTWO",   # Take-Two Interactive
    "PAYX",   # Paychex

    # ── Internet / E-commerce ──
    "NFLX",   # Netflix
    "BKNG",   # Booking Holdings
    "ABNB",   # Airbnb
    "PYPL",   # PayPal
    "SQ",     # Block (Square)
    "DASH",   # DoorDash
    "MELI",   # MercadoLibre
    "ROKU",   # Roku
    "COIN",   # Coinbase
    "PDD",    # PDD Holdings (Temu)

    # ── Telecom / Media ──
    "CSCO",   # Cisco
    "CMCSA",  # Comcast
    "CHTR",   # Charter Communications
    "TMUS",   # T-Mobile

    # ── Biotech / Healthcare ──
    "AMGN",   # Amgen
    "GILD",   # Gilead Sciences
    "ISRG",   # Intuitive Surgical
    "REGN",   # Regeneron
    "VRTX",   # Vertex Pharmaceuticals
    "MRNA",   # Moderna
    "BIIB",   # Biogen
    "IDXX",   # IDEXX Laboratories
    "DXCM",   # DexCom
    "GEHC",   # GE HealthCare
    "ILMN",   # Illumina
    "AZN",    # AstraZeneca (ADR)

    # ── Consumer ──
    "PEP",    # PepsiCo
    "SBUX",   # Starbucks
    "MDLZ",   # Mondelez
    "MNST",   # Monster Beverage
    "LULU",   # Lululemon
    "ORLY",   # O'Reilly Automotive
    "CPRT",   # Copart
    "KDP",    # Keurig Dr Pepper
    "KHC",    # Kraft Heinz
    "ROST",   # Ross Stores
    "DLTR",   # Dollar Tree

    # ── Industrials / Utilities ──
    "HON",    # Honeywell
    "ADP",    # ADP
    "CTAS",   # Cintas
    "PCAR",   # PACCAR
    "FAST",   # Fastenal
    "ODFL",   # Old Dominion Freight
    "FTNT",   # Fortinet
    "VRSK",   # Verisk Analytics
    "CEG",    # Constellation Energy
    "LIN",    # Linde
    "BKR",    # Baker Hughes
    "FANG",   # Diamondback Energy
    "EXC",    # Exelon
    "XEL",    # Xcel Energy
    "AEP",    # American Electric Power
    "CSGP",   # CoStar Group
    "MAR",    # Marriott

    # ── High-vol / Speculative (NDX-adjacent, very liquid AH) ──
    "SMCI",   # Super Micro Computer
    "RIVN",   # Rivian
    "LCID",   # Lucid Motors
    "ENPH",   # Enphase Energy
    "CCEP",   # Coca-Cola Europacific
]

# ═══════════════════════════════════════════════════
# Strategy Parameters — Extreme Move Fade
# ═══════════════════════════════════════════════════
EXTREME_MOVE_PCT = 0.07        # 7% threshold for entry signal
HARD_STOP_PCT = 0.05           # -5% hard stop from entry
PROFIT_CEILING_PCT = 0.025     # +2.5% overnight profit target

# Profit ceiling exit conditions
PROFIT_EXIT_MAX_SPREAD_PCT = 0.004   # spread ≤ 0.40% to take profit
PROFIT_EXIT_MIN_VOLUME = 100         # min shares in last 5 min quote

# ═══════════════════════════════════════════════════
# Position Sizing & Risk
# ═══════════════════════════════════════════════════
RISK_PER_TRADE_PCT = 0.02      # 1–2% account risk per trade
MAX_CONCURRENT_POSITIONS = 3   # max 3 positions open at once
ASSUMED_FRICTION_PCT = 0.005   # 0.5% assumed friction for PnL tracking

# ═══════════════════════════════════════════════════
# State & Logging
# ═══════════════════════════════════════════════════
STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state")
STATE_FILE = os.path.join(STATE_DIR, "ah_bot_state.json")
LOG_DIR = os.path.join(STATE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "ah_bot.log")
TRADE_LOG_FILE = os.path.join(LOG_DIR, "ah_trades.log")
METRICS_FILE = os.path.join(LOG_DIR, "trade_metrics.json")
PERFORMANCE_FILE = os.path.join(LOG_DIR, "performance.json")
