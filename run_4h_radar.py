"""
4-Hour Market Radar & Advisory Scanner.
Executed automatically every 4 hours via GitHub Actions and local scheduler.
Scans all 160+ watchlist coins with 4H MTF de-duplication and sends alerts to Telegram.
"""
import sys
import os
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from bot import execute_scan_cycle

if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    print(f"[{now_utc.strftime('%Y-%m-%d %H:%M UTC')}] GitHub Actions 4-Hour Scan Started...")
    execute_scan_cycle(config.TELEGRAM_CHAT_ID, is_scheduled_4h=True)
    print("4-Hour Scan Finished successfully.")
