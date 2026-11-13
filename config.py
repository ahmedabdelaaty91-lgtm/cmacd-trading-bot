import os
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Telegram Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Binance API Credentials
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Operational Mode
# ADVISORY_MODE = True means the bot acts 100% as an Advisory Signal System:
# It scans the market, ranks signals, and sends full reports to Telegram.
# AUTO_TRADE = False guarantees no automatic buys are ever placed on Binance!
ADVISORY_MODE = True
AUTO_TRADE = False
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

# Strategy Rules (Targets & Risk)
TIMEFRAME = "1d"
BTC_EMA_PERIOD = 50
FAST_TARGET_PCT = 0.03    # +3.0% Fast Target
RUNNER_TARGET_PCT = 0.06  # +6.0% Runner Target
STOP_LOSS_PCT = 0.04      # -4.0% Standard SL

# Base Binance API URLs
BINANCE_DATA_URL = "https://data-api.binance.vision"
BINANCE_REST_URL = "https://api.binance.com"

# Load Watchlist
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")
def get_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("BNB", "BNBUSDT"), ("SOL", "SOLUSDT")]

WATCHLIST = get_watchlist()

ALPHA_SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "alpha_symbols.json")
def get_alpha_symbols():
    if os.path.exists(ALPHA_SYMBOLS_FILE):
        try:
            with open(ALPHA_SYMBOLS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

ALPHA_SYMBOLS = get_alpha_symbols()
