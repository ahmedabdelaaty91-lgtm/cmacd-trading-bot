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

def _get_float_env(key, default):
    val = os.getenv(key, "")
    if val is not None and str(val).strip():
        try:
            return float(str(val).strip())
        except Exception:
            pass
    return default

def _get_int_env(key, default):
    val = os.getenv(key, "")
    if val is not None and str(val).strip():
        try:
            return int(str(val).strip())
        except Exception:
            pass
    return default

def _get_bool_env(key, default):
    val = os.getenv(key, "")
    if val is not None and str(val).strip():
        return str(val).strip().lower() in ("true", "1", "yes")
    return default

# Operational Mode (Auto-Trade on Binance Spot)
AUTO_TRADE = _get_bool_env("AUTO_TRADE", True)
ADVISORY_MODE = not AUTO_TRADE
DRY_RUN = _get_bool_env("DRY_RUN", False)

# Position & Sizing Management
# MAX_OPEN_POSITIONS: الحد الأقصى للصفقات المتزامنة (مثلاً 6 صفقات، أو 0 لفتح أي فرصة طالما يتوفر رصيد USDT)
TRADE_AMOUNT_USDT = _get_float_env("TRADE_AMOUNT_USDT", 15.0)
MAX_OPEN_POSITIONS = _get_int_env("MAX_OPEN_POSITIONS", 6)

# Strategy Rules (Targets & Risk)
TIMEFRAME = "1d"
BTC_EMA_PERIOD = 50
FAST_TARGET_PCT = _get_float_env("FAST_TARGET_PCT", 0.03)    # +3.0% Fast Target (TP1)
RUNNER_TARGET_PCT = _get_float_env("RUNNER_TARGET_PCT", 0.06)  # +6.0% Runner Target (TP2)
STOP_LOSS_PCT = _get_float_env("STOP_LOSS_PCT", 0.04)      # -4.0% Standard SL

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
