"""
Dedicated runner for Hourly Market Scan via GitHub Actions, Cron, or Local Scheduler.
Executes once every hour, scans for newly ignited opportunities with volume spikes,
and dispatches Telegram alerts ONLY for new coins (with anti-duplication filter).
"""
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from bot import execute_hourly_scan

if __name__ == "__main__":
    print("Executing Hourly Elite Market Scan with Anti-Spam Deduplication...")
    execute_hourly_scan(config.TELEGRAM_CHAT_ID)
    print("Hourly scan execution finished.")
