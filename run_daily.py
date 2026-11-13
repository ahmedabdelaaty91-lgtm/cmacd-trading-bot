"""
Dedicated runner for GitHub Actions & Daily Cron.
Executes once at Daily Close (00:05 UTC), scans market for the authorized TMO & Hull Suite models,
and sends the Telegram report.
"""
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from bot import execute_scan

if __name__ == "__main__":
    print("Running Scheduled Daily Scan via GitHub Actions...")
    execute_scan(config.TELEGRAM_CHAT_ID, is_scheduled=True)
    print("Daily scan complete.")
