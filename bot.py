import time
import json
import requests
import threading
import re
from datetime import datetime, timezone
import config
from strategy import (
    check_btc_regime,
    scan_ichimoku_trio,
    format_ichimoku_trio_report
)
from binance_client import BinanceClient

client = BinanceClient()

def clean_telegram_html(text):
    """
    Safely escapes stray <, >, and & characters that are not part of valid Telegram HTML tags
    (<b>, </b>, <code>, </code>, <i>, </i>, <u>, </u>, <s>, </s>, <pre>, </pre>, <a href="...">, </a>).
    Prevents Telegram entity parse errors (HTTP 400).
    """
    tag_pattern = r'(</?(?:b|code|i|u|s|pre|a)(?: [^>]*)?>)'
    parts = re.split(tag_pattern, text)
    cleaned = []
    for p in parts:
        if re.match(tag_pattern, p):
            cleaned.append(p)
        else:
            esc = p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            cleaned.append(esc)
    return ''.join(cleaned)

def send_telegram_message(chat_id, text):
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id or not text:
        return
        
    # Auto-chunk if text exceeds safe limit
    if len(text) > 3800:
        lines = text.split("\n")
        chunks = []
        cur_lines = []
        cur_len = 0
        for l in lines:
            if cur_len + len(l) + 1 > 3600 and cur_lines:
                chunks.append("\n".join(cur_lines))
                cur_lines = [l]
                cur_len = len(l) + 1
            else:
                cur_lines.append(l)
                cur_len += len(l) + 1
        if cur_lines:
            chunks.append("\n".join(cur_lines))
            
        for c in chunks:
            send_telegram_message(chat_id, c)
            time.sleep(1)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    safe_text = clean_telegram_html(text)
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            print(f"Telegram API warning {r.status_code}: {r.text}")
            clean_plain = re.sub(r'<[^>]+>', '', text)
            payload_plain = {
                "chat_id": chat_id,
                "text": clean_plain,
                "disable_web_page_preview": True
            }
            requests.post(url, json=payload_plain, timeout=15)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def format_radar_message():
    btc = check_btc_regime()
    status_icon = "🟢 <b>مسار صاعد فوق EMA50 (BULLISH)</b>" if btc.get('is_bull') else "🔴 <b>مسار تصحيحي تحت EMA50 (BEARISH)</b>"
    
    msg = (
        f"📡 <b>رادار اتجاه البيتكوين (Daily 1D):</b>\n"
        f"────────────────────\n"
        f"• <b>سعر البيتكوين:</b> <code>{btc.get('price', 0):,.1f} $</code>\n"
        f"• <b>Daily EMA50:</b> <code>{btc.get('ema50', 0):,.1f} $</code>\n"
        f"• <b>الفارق عن المتوسط:</b> <code>{btc.get('diff_pct', 0):+.2f}%</code>\n"
        f"• <b>حالة المسار العام:</b> {status_icon}\n"
        f"────────────────────\n"
        f"💡 <i>عند ارتكاز البيتكوين فوق EMA50 تكون موجات الإيشيموكو الصاعدة أكثر قوة وانفجاراً!</i>"
    )
    return msg

def execute_ichimoku_trio_scan(chat_id, is_scheduled=False):
    """
    Executes the 3 Authorized Master Ichimoku Strategies across 301 coins:
    1. The Supreme Combo (PF 6.65)
    2. Cloud Breakout at Support
    3. Cloud Pullback & Retest Bounce
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID

    if not is_scheduled:
        send_telegram_message(
            chat_id,
            "⚡ <b>جاري فحص 301 عملة لاستراتيجيات الإيشيموكو الثلاثة المعتمدة...</b>\n\n"
            "1. 🏆 <b>المعادلة الفائقة:</b> تقاطع Tenkan/Kijun صاعد فوق السحابة + قرب الكيجين &lt;= 4% (معامل ربح 6.65).\n"
            "2. ☁️ <b>اختراق السحابة عند الدعم:</b> صعود فوق السحابة مستنداً على دعم قوي.\n"
            "3. 🔄 <b>إعادة اختبار السحابة:</b> الارتداد الصاعد من سقف السحابة.\n\n"
            "⏱️ <i>لحظات وسيصلك التقرير المباشر...</i>"
        )
        
    scan_res = scan_ichimoku_trio()
    reports = format_ichimoku_trio_report(scan_res)
    
    if isinstance(reports, list):
        for rep in reports:
            send_telegram_message(chat_id, rep)
            time.sleep(1)
    else:
        send_telegram_message(chat_id, reports)

def handle_telegram_updates():
    """Telegram Long-Polling listener with multi-command support"""
    offset = None
    print("Telegram Bot Listener Started...")
    
    while True:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 30}
        if offset:
            params["offset"] = offset
            
        try:
            r = requests.get(url, params=params, timeout=40)
            if r.status_code == 200:
                data = r.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()
                    
                    if not chat_id:
                        continue
                        
                    if not config.TELEGRAM_CHAT_ID:
                        config.TELEGRAM_CHAT_ID = str(chat_id)
                        print(f"Captured Chat ID: {chat_id}")
                        
                    text_lower = text.lower()
                    
                    if text_lower in ["/start", "start", "مرحبا"]:
                        welcome = (
                            f"👋 <b>أهلاً بك في رادار استراتيجيات الإيشيموكو الذهبية الثلاثة!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"🎯 <b>تم اعتماد الاستراتيجيات الثلاثة الفائقة فقط:</b>\n"
                            f"• 🏆 <b>1. المعادلة الفائقة (The Supreme Combo - PF 6.65):</b>\n"
                            f"   تقاطع Tenkan/Kijun صاعد فوق السحابة + قرب السعر من الكيجين سن &lt;= 4% + سحابة مستقبلية خضراء + RSI صحي.\n\n"
                            f"• ☁️ <b>2. اختراق سحابة الإيشيموكو عند الدعم:</b>\n"
                            f"   اختراق سقف السحابة صعوداً بالارتكاز على قاع أو دعم قوي.\n\n"
                            f"• 🔄 <b>3. إعادة اختبار السحابة والارتداد (Kumo Retest):</b>\n"
                            f"   رصد العملات التي صححت واختبرت سقف السحابة كدعم وبدأت بالصعود مجدداً.\n\n"
                            f"📌 <b>الأوامر السريعة:</b>\n"
                            f"• أرسل <b>سحابة</b> أو <code>/scan</code>: لتشغيل الفحص الفوري للثلاث استراتيجيات.\n"
                            f"• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع اتجاه البيتكوين.\n"
                            f"• أرسل <code>/ping</code>: لاختبار الاتصال المباشر بباينانس."
                        )
                        send_telegram_message(chat_id, welcome)
                        
                    elif text_lower in ["رادار", "/radar", "radar"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["فحص", "مسح", "/scan", "scan", "سحابة", "السحابة", "ايشيموكو", "الايشيموكو", "ذهبي", "الذهبي", "/golden", "golden", "/ichimoku", "ichimoku", "/kumo", "kumo"]:
                        threading.Thread(target=execute_ichimoku_trio_scan, args=(chat_id, False), daemon=True).start()
                        
                    else:
                        reply = (
                            "❓ <b>الأوامر المتاحة:</b>\n"
                            "• أرسل <b>سحابة</b> أو <code>/scan</code>: لفحص الاستراتيجيات الثلاثة للإيشيموكو (المعادلة الفائقة + الاختراق عند الدعم + إعادة اختبار السحابة).\n"
                            "• أرسل <b>رادار</b> أو <code>/radar</code>: لحالة البيتكوين العامة."
                        )
                        send_telegram_message(chat_id, reply)
        except Exception as e:
            time.sleep(3)

def four_hour_scheduler_loop():
    """
    Automatically triggers execute_ichimoku_trio_scan every 4 hours:
    At 00:02, 04:02, 08:02, 12:02, 16:02, 20:02 UTC.
    Sends the single consolidated Ichimoku Trio digest!
    """
    print("4-Hour Automatic Ichimoku Trio Scanner Thread Started.")
    last_slot = None
    
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if now_utc.hour % 4 == 0 and now_utc.minute >= 2:
                slot_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour}"
                if last_slot != slot_id:
                    print(f"Triggering Scheduled 4-Hour Ichimoku Scan for slot {slot_id}...")
                    execute_ichimoku_trio_scan(config.TELEGRAM_CHAT_ID, is_scheduled=True)
                    last_slot = slot_id
        except Exception as e:
            print(f"Error in 4-hour scheduler loop: {e}")
            
        time.sleep(30)

def start_health_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import os
    port = int(os.getenv("PORT", 10000))
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                "status": "online",
                "service": "Ichimoku Master Trio Radar Bot",
                "strategies": [
                    "1. The Supreme Combo (Strong TK Cross Above Cloud + Kijun <= 4% - PF 6.65)",
                    "2. Kumo Breakout at Support",
                    "3. Kumo Retest & Bounce"
                ],
                "time_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.wfile.write(json.dumps(data).encode('utf-8'))
            
        def log_message(self, format, *args):
            return
            
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        print(f"Health check HTTP server listening on port {port}...")
        server.serve_forever()
    except Exception as e:
        print(f"HTTP Server warning: {e}")

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("Ichimoku Master Trio Radar Bot starting...")
    
    # Start Health Server
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start 4-Hour Automatic Support Scheduler
    scheduler_4h_thread = threading.Thread(target=four_hour_scheduler_loop, daemon=True)
    scheduler_4h_thread.start()
    
    # Start Telegram Listener
    handle_telegram_updates()
