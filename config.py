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
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Operational Mode
# DRY_RUN = True means it will track and simulate trades with live prices without risking real money
# Set DRY_RUN = False when Binance API keys with spot trading permissions are added!
DRY_RUN = os.getenv("DRY_RUN", "True").lower() in ("true", "1", "yes")

# Strategy Rules (Plan 2)
TIMEFRAME = "1d"
BTC_EMA_PERIOD = 50
POSITION_SIZE_PCT = 0.25 # 25% of portfolio per trade
MAX_POSITIONS = 4        # Max 4 concurrent open trades
INITIAL_SL_PCT = 0.06    # -6% Stop Loss
TP1_PCT = 0.10           # +10% First Take Profit
TP1_SELL_RATIO = 0.50    # Sell 50% of position at TP1
SL_AFTER_TP1_PCT = 0.01  # Move SL to Entry + 1% after TP1

# Base Binance API URLs (binance.vision is geo-unrestricted for Cloud/GitHub Actions)
BINANCE_DATA_URL = "https://data-api.binance.vision"
BINANCE_REST_URL = "https://api.binance.com"

# Load Watchlist
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")
if os.path.exists(WATCHLIST_FILE):
    with open(WATCHLIST_FILE, "r") as f:
        WATCHLIST = json.load(f)
else:
    WATCHLIST = [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("BNB", "BNBUSDT"), ("SOL", "SOLUSDT")]
