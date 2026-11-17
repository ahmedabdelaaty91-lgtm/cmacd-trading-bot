import os
import json

# Load environment variables from .env if present
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

# Telegram Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Binance API Credentials
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Operational Mode (Auto-Trade on Binance Spot)
AUTO_TRADE = os.getenv("AUTO_TRADE", "True").lower() in ("true", "1", "yes")
ADVISORY_MODE = not AUTO_TRADE
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

# Position & Sizing Management
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "15.0"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))

# Strategy Rules (Targets & Risk)
TIMEFRAME = "1d"
BTC_EMA_PERIOD = 50
FAST_TARGET_PCT = float(os.getenv("FAST_TARGET_PCT", "0.03"))    # +3.0% Fast Target (TP1)
RUNNER_TARGET_PCT = float(os.getenv("RUNNER_TARGET_PCT", "0.06"))  # +6.0% Runner Target (TP2)
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.04"))      # -4.0% Standard SL

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
