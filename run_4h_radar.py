"""
4-Hour Market Radar & Advisory Scanner.
Executed automatically every 4 hours or via GitHub Actions.
Scans all 300+ watchlist coins for the authorized TMO & Hull Suite models,
and sends alerts to Telegram with Bitcoin regime status.
"""
import sys
import os
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from bot import execute_scan

if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    print(f"[{now_utc.strftime('%Y-%m-%d %H:%M UTC')}] 4-Hour Scan Started...")
    execute_scan(config.TELEGRAM_CHAT_ID, is_scheduled=True)
    print("4-Hour Scan Finished successfully.")
