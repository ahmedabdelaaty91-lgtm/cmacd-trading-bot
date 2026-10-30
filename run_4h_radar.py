"""
4-Hour Market Radar & Advisory Scanner.
Executed automatically every 4 hours via GitHub Actions and local scheduler.
Scans all 161 watchlist coins and sends a comprehensive market radar to Telegram.
"""
import sys
import os
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

import config
from strategy import check_btc_regime, scan_market
from bot import send_telegram_message, format_advisory_signal_message
import database as db

def run_4h_market_radar():
    now_utc = datetime.now(timezone.utc)
    # Cairo Time = UTC + 3
    cairo_hour = (now_utc.hour + 3) % 24
    time_str = now_utc.strftime("%Y-%m-%d %H:%M UTC") + f" ({cairo_hour:02d}:{now_utc.minute:02d} بتوقيت مصر)"
    
    print(f"[{time_str}] Starting 4-Hour Market Radar Scan...")
    
    # 1. Fetch BTC Regime
    btc = check_btc_regime()
    if 'error' in btc:
        print(f"BTC Error: {btc['error']}")
        return
        
    btc_p = btc.get('price', 0)
    ema50 = btc.get('ema50', 0)
    diff_pct = btc.get('diff_pct', 0)
    is_bull = btc.get('is_bull', False)
    banker_active = btc.get('banker_active', False)
    banker_val = btc.get('banker_val', 0)
    
    btc_status_icon = "🟢 <b>مسار صاعد (BULLISH فوق EMA50)</b>" if is_bull else "🔴 <b>مسار تصحيحي / هابط (تحت EMA50)</b>"
    banker_icon = "🟢 سيولة حيتان نشطة" if banker_active else "⚪ سيولة هادئة"
    
    # 2. Scan Market (161 coins)
    scan_res = scan_market()
    signals = scan_res.get('signals', [])
    scanned_count = scan_res.get('all_scanned_count', len(config.get_watchlist()))
    
    tier1_signals = [s for s in signals if s.get('tier') == 1]
    tier2_signals = [s for s in signals if s.get('tier') == 2]
    
    # 3. Build 4-Hour Market Radar Summary Message
    radar_msg = (
        f"📡 <b>رادار السوق اللحظي (كل 4 ساعات):</b>\n"
        f"⏱️ <i>{time_str}</i>\n"
        f"────────────────────\n"
        f"🪙 <b>سعر البيتكوين:</b> <code>{btc_p:,.1f} $</code>\n"
        f"📈 <b>Daily EMA50:</b> <code>{ema50:,.1f} $</code> ({diff_pct:+.2f}%)\n"
        f"🧭 <b>حالة الاتجاه العام:</b> {btc_status_icon}\n"
        f"🏦 <b>سيولة الحيتان بالمؤشر:</b> {banker_icon} (مستوى <code>{banker_val}</code>)\n"
        f"────────────────────\n"
        f"🔍 <b>نتيجة فحص السوق ({scanned_count} عملة):</b>\n"
        f"• 🌟 <b>إشارات VIP الذهبية (5/5 كاملة):</b> {len(tier1_signals)} عملة.\n"
        f"• 🟢 <b>إشارات القياسية المعتمدة (4/4):</b> {len(tier2_signals)} عملة.\n"
    )
    
    if not signals:
        radar_msg += (
            f"────────────────────\n"
            f"🛡️ <b>حالة الرادار:</b> لا توجد عملات محققة لكامل الشروط الخمسة اليوم حتى الآن.\n"
            f"ℹ️ <i>البوت في وضع المراقبة الدائمة لحماية رأس المال، ولن يرسل أي تنبيه إلا للفرص المكتملة ذات الدقة العالية (71%).</i>"
        )
        send_telegram_message(config.TELEGRAM_CHAT_ID, radar_msg)
        print("4-Hour Radar sent (No signals).")
        return
        
    radar_msg += (
        f"────────────────────\n"
        f"🎯 <b>تم رصد {len(signals)} فرصة محققة للشروط! التفاصيل بالرسائل التالية:</b>"
    )
    send_telegram_message(config.TELEGRAM_CHAT_ID, radar_msg)
    time.sleep(1)
    
    today_str = now_utc.strftime("%Y-%m-%d")
    for sig in signals:
        sym = sig['symbol']
        sig_msg = format_advisory_signal_message(sig, btc)
        send_telegram_message(config.TELEGRAM_CHAT_ID, sig_msg)
        db.record_alert(sym, sig['pair'], today_str, sig.get('tier', 1), sig['current_price'], sig['tier_badge'])
        time.sleep(1)
        
    print(f"4-Hour Radar sent ({len(signals)} signals).")

if __name__ == "__main__":
    run_4h_market_radar()
