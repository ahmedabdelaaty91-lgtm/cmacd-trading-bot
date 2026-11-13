"""
Dedicated runner for GitHub Actions.
Executes once at Daily Close (00:05 UTC), scans market for Ichimoku Master Trio strategies, and sends Telegram report.
"""
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from bot import execute_ichimoku_trio_scan

if __name__ == "__main__":
    print("Running Scheduled Daily Scan via GitHub Actions...")
    execute_ichimoku_trio_scan(config.TELEGRAM_CHAT_ID, is_scheduled=True)
    print("Daily scan complete.")
