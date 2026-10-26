"""
Dedicated runner for GitHub Actions.
Executes once at Daily Close (00:05 UTC), scans market, updates orders, sends Telegram report, and exits.
"""
import sys
import config
from bot import execute_daily_scan, monitor_open_positions

if __name__ == "__main__":
    print("Running Scheduled Daily Scan via GitHub Actions...")
    execute_daily_scan(config.TELEGRAM_CHAT_ID)
    print("Daily scan complete.")
