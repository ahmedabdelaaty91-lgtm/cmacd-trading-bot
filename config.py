import os
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Telegram Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8909689391:AAHFmjfhzVJXumN3lWBzrFtpne3SJ9tC6-Q")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7760401819")

# Binance API Credentials
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "PPkG8M8twsNEXEZonYHWOxsikxV3RV5R4SfvLVXNyulMCuWIZlOJciKgQu0F7ZeF")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "WVIDdEr3XMs6XVYQa4MEuXfBAqmhjfOf5vZj7FV6ID9qm0ulC0Qmgn8M2MhmA9TI")

# Operational Mode
# ADVISORY_MODE = True means the bot acts 100% as an Advisory Signal System:
# It analyzes all 4 indicators + Volume, ranks signals, and sends full reports to Telegram.
# AUTO_TRADE = False guarantees no automatic buys are ever placed on Binance!
ADVISORY_MODE = True
AUTO_TRADE = False
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

# Strategy Rules (Plan 3: 3-Stage Ladder Exit + Wave Rider)
TIMEFRAME = "1d"
BTC_EMA_PERIOD = 50
POSITION_SIZE_PCT = 0.25 # 25% of total portfolio per trade
MAX_POSITIONS = 4        # Max 4 concurrent open trades

# Risk & Exit Settings
INITIAL_SL_PCT = 0.06    # -6% Stop Loss (cut loss immediately or on early MACD cross down)
TP1_PCT = 0.04           # +4% Target 1
TP1_SELL_RATIO = 0.25    # Sell 25% of position at TP1
SL_AFTER_TP1_PCT = 0.01  # Move SL to Entry + 1% (Risk-free profit lock)

TP2_PCT = 0.08           # +8% Target 2
TP2_SELL_RATIO = 0.25    # Sell 25% of position at TP2
SL_AFTER_TP2_PCT = 0.04  # Move SL to Entry + 4%

# The remaining 50% rides the multi-day wave until Daily MACD crosses down!

# Base Binance API URLs
BINANCE_DATA_URL = "https://data-api.binance.vision"
BINANCE_REST_URL = "https://api.binance.com"

# Load Watchlist
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")
def get_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("BNB", "BNBUSDT"), ("SOL", "SOLUSDT")]

WATCHLIST = get_watchlist()

