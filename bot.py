import time
import json
import requests
import threading
import re
import os
from datetime import datetime, timezone
import config
from strategy import (
    check_btc_regime,
    scan_authorized_strategies,
    format_authorized_report,
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
    is_bull = btc.get('is_bull', False)
    status_icon = "🟢 <b>مسار صاعد فوق Daily EMA50 (BULLISH)</b>" if is_bull else "🔴 <b>مسار تصحيحي أسفل Daily EMA50 (BEARISH)</b>"
    diff_sign = "+" if btc.get('diff_pct', 0) >= 0 else ""
    
    msg = (
        f"📡 <b>رادار اتجاه البيتكوين العام (BTC Daily 1D):</b>\n"
        f"────────────────────\n"
        f"• <b>سعر البيتكوين:</b> <code>{btc.get('price', 0):,.1f} $</code>\n"
        f"• <b>متوسط Daily EMA50:</b> <code>{btc.get('ema50', 0):,.1f} $</code>\n"
        f"• <b>الفارق عن المتوسط:</b> <code>{diff_sign}{btc.get('diff_pct', 0):.2f}%</code>\n"
        f"• <b>حالة السوق:</b> {status_icon}\n"
        f"────────────────────\n"
        f"💡 <b>قواعد إدارة المخاطر المبنية على الباكتيست:</b>\n"
        f"• <b>عندما يكون البيتكوين صاعداً (BTC &gt; EMA50):</b>\n"
        f"  ترتفع دقة النموذج الأقوى إلى <b>73.8%</b> في أول يومين (إجمالي نجاح 91.1% ومعامل ربح PF 1.34).\n"
        f"• <b>عندما يكون البيتكوين هابطاً (BTC &lt; EMA50):</b>\n"
        f"  تداول بحذر شديد مع جني ربح سريع عند <b>+3.0%</b> فور تحققه."
    )
    return msg


def execute_scan(chat_id=None, is_scheduled=False, **kwargs):
    """
    Executes scan across all Binance USDT coins exclusively for the 2 authorized models:
    1. النموذج الأساسي (تقاطع TMO + خط Hull Suite أخضر + عند الدعم)
    2. النموذج الأقوى 🔥 (عند دعم + خط Hull أخضر + شمعة خضراء + فوليوم ≥ 1.15x)
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID

    is_scheduled_call = is_scheduled or kwargs.get('is_scheduled_4h', False) or kwargs.get('is_scheduled_daily', False)

    if not is_scheduled_call and chat_id:
        send_telegram_message(
            chat_id,
            "⚡ <b>جاري فحص السوق للنماذج المعتمدة (TMO + Hull Suite)...</b>\n\n"
            "• 🌟 <b>النموذج الأقوى 🔥:</b> دعم + Hull أخضر + شمعة خضراء + فوليوم ≥ 1.15x (دقة 70.7%)\n"
            "• ⚡ <b>النموذج الأساسي:</b> تقاطع TMO + خط Hull أخضر + عند الدعم (دقة 63.5%)\n\n"
            "⏱️ <i>لحظات وسيصلك التقرير المباشر مع تقييم وضع البيتكوين...</i>"
        )
        
    scan_res = scan_authorized_strategies()
    reports = format_authorized_report(scan_res)
    
    if isinstance(reports, list):
        for rep in reports:
            send_telegram_message(chat_id, rep)
            time.sleep(1)
    else:
        send_telegram_message(chat_id, reports)

execute_scan_cycle = execute_scan
execute_daily_scan = execute_scan
execute_ichimoku_trio_scan = execute_scan


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
                            f"👋 <b>أهلاً بك في بوت رادار الصفقات المعتمدة (TMO + Hull Suite)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"🎯 <b>النماذج المعتمدة حصرياً (الهدف السريع +3.0%):</b>\n\n"
                            f"1️⃣ 🌟 <b>النموذج الأقوى 🔥:</b>\n"
                            f"• الشروط: ارتكاز عند دعم + خط Hull Suite أخضر + شمعة دافعة خضراء + سيولة فوليوم ≥ 1.15x.\n"
                            f"• نسبة النجاح: <b>70.7%</b> في أول يومين (ترتفع لـ <b>73.8%</b> مع صعود BTC) | إجمالي تحقيق الهدف: <b>90.9%</b>.\n\n"
                            f"2️⃣ ⚡ <b>النموذج الأساسي:</b>\n"
                            f"• الشروط: تقاطع TMO إيجابي + خط Hull Suite أخضر + ارتكاز عند دعم.\n"
                            f"• نسبة النجاح: <b>63.5%</b> في أول يومين (ترتفع لـ <b>65.5%</b> مع صعود BTC) | إجمالي تحقيق الهدف: <b>86.3%</b>.\n\n"
                            f"────────────────────\n"
                            f"📌 <b>الأوامر المتاحة:</b>\n"
                            f"• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص السوق فورياً وإرسال الصفقات المطابقة وتحديد نوع النموذج وحالة البيتكوين.\n"
                            f"• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع البيتكوين بالنسبة لـ Daily EMA50.\n"
                            f"• أرسل <code>/ping</code>: لاختبار الاتصال مع باينانس."
                        )
                        send_telegram_message(chat_id, welcome)
                        
                    elif text_lower in ["رادار", "/radar", "radar", "بيتكوين", "btc"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["فحص", "مسح", "/scan", "scan", "فرص", "الفرص", "صفقات", "tmo", "hull"]:
                        threading.Thread(target=execute_scan, args=(chat_id, False), daemon=True).start()
                        
                    else:
                        reply = (
                            "❓ <b>الأوامر المتاحة:</b>\n"
                            "• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص السوق للنموذجين المعتمدين.\n"
                            "• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة حالة البيتكوين العامة."
                        )
                        send_telegram_message(chat_id, reply)
        except Exception as e:
            time.sleep(3)


def start_health_server():
    """Lightweight HTTP server for cloud hosting health-checks (Render, Railway, etc.)"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    port = int(os.getenv("PORT", 10000))
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                "status": "online",
                "service": "TMO Scalper & Hull Suite Trading Bot",
                "models": [
                    "1. Golden Model (Support + Hull Green + Green Candle + Volume >= 1.15x)",
                    "2. Base Model (TMO Cross + Hull Green + Support)"
                ],
                "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print("TMO Scalper & Hull Suite Trading Bot starting...")
    
    # Start Health Server
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start Telegram Listener
    handle_telegram_updates()
