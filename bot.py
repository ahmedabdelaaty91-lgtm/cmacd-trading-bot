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
    format_price,
    inspect_intraday_status,
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
    Executes scan across all Binance USDT coins for the 5 Elite Proven Models,
    sorted strictly from strongest to weakest within:
    1. الهدف السريع الخاطف (+3% في 24-48 ساعة): SuperTrend Flip ثم ATR 15% Expansion
    2. تعظيم الأرباح التراكمية (TP 6% / SL 4%): Ehlers Fisher ثم Force Index ثم TTM Squeeze
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID

    is_scheduled_call = is_scheduled or kwargs.get('is_scheduled_4h', False) or kwargs.get('is_scheduled_daily', False)

    if not is_scheduled_call and chat_id:
        send_telegram_message(
            chat_id,
            "⚡ <b>جاري فحص السوق للنماذج النخبوية الخمسة المعتمدة...</b>\n\n"
            "• 🎯 <b>الهدف السريع (+3%):</b> 1️⃣ SuperTrend Flip ثم 2️⃣ ATR 15% Expansion\n"
            "• 🚀 <b>تعظيم الأرباح (TP 6%):</b> 1️⃣ Ehlers Fisher ثم 2️⃣ Force Index ثم 3️⃣ TTM Squeeze\n\n"
            "⏱️ <i>لحظات وسيصلك التقرير المباشر مرتباً من الأقوى للأضعف علمياً...</i>"
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

ALERT_CACHE_FILE = os.path.join(os.path.dirname(__file__), "alerts_sent_cache.json")


def load_alert_cache():
    """Loads alert deduplication cache for the current UTC day."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if os.path.exists(ALERT_CACHE_FILE):
        try:
            with open(ALERT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                keys = set()
                for k in data.get("sent_keys", []):
                    keys.add(k)
                    if "_" in k:
                        keys.add(k.split("_")[0])
                return keys
        except Exception:
            pass
    return set()


def save_alert_cache(sent_keys):
    """Persists alert deduplication cache to disk."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(ALERT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": today_str, "sent_keys": list(sent_keys)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving alert cache: {e}")


def execute_hourly_scan(chat_id=None):
    """
    Executes hourly scan across all Binance USDT coins.
    1. Consolidates multiple strategies into a single trade per coin (No duplicates!).
    2. Inspects 1H candles to detect if an opportunity already ignited hours ago.
    3. Categorizes into:
       - Fresh Entries (🟢 في نطاق الشراء المثالي الآن).
       - Already-Running Trades (⚠️ انطلقت سابقاً ولم تُرسل في أولها وهي شغالة حالياً - لا تدخل الآن).
    4. Deduplicates against today's cache.
    5. Sends a peaceful report if no unalerted opportunities exist.
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    sent_keys = load_alert_cache()
    scan_res = scan_authorized_strategies()
    all_signals = scan_res.get('scalp', []) + scan_res.get('swing', [])

    # Filter out coins already alerted today
    unalerted = []
    for s in all_signals:
        key = s['symbol'] # Single unique symbol key
        if key not in sent_keys:
            unalerted.append(s)

    btc = check_btc_regime()
    btc_icon = "🟢" if btc.get('is_bull') else "🔴"
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if not unalerted:
        print(f"[{datetime.now()}] Hourly Scan complete: No unalerted opportunities. Notifying Telegram...")
        total_tracked = len(all_signals)
        no_new_msg = (
            f"⏱️ <b>تقرير الفحص الساعي (رصد كل 60 دقيقة)</b>\n"
            f"────────────────────\n"
            f"⏰ <b>توقيت الفحص:</b> <code>{now_str}</code>\n"
            f"📊 <b>وضع البيتكوين:</b> {btc_icon} <b>{btc.get('status_text', '')}</b>\n"
            f"🔍 <b>النتيجة:</b> <b>لا توجد أي فرص جديدة طازجة دخلتها السيولة هذه الساعة.</b>\n"
            f"💡 <i>(السوق هادئ حالياً ولا توجد أي انفجارات سيولة جديدة).</i>\n"
            f"────────────────────\n"
            f"📌 <b>إجمالي الفرص النشطة القائمة:</b> <b>{total_tracked}</b> فرصة\n"
            f"👉 أرسل <b>فحص</b> أو <code>/scan</code> لعرض كامل تفاصيل الفرص القائمة وأهدافها."
        )
        send_telegram_message(chat_id, no_new_msg)
        return

    # Check 1H intraday timing & price drift for unalerted coins
    fresh_signals = []
    running_signals = []

    for s in unalerted:
        intra = inspect_intraday_status(s['symbol'], s['pair'], s['price'])
        s['intraday_status'] = intra
        if intra['is_running']:
            running_signals.append(s)
        else:
            fresh_signals.append(s)
        sent_keys.add(s['symbol'])

    save_alert_cache(sent_keys)
    new_total = len(fresh_signals) + len(running_signals)
    print(f"[{datetime.now()}] Hourly Scan detected {new_total} coins ({len(fresh_signals)} fresh, {len(running_signals)} running). Dispatching...")

    messages = []
    header = (
        f"🚨 <b>رادار الصيد اللحظي (الفحص الساعي)</b>\n"
        f"────────────────────\n"
        f"⏰ <b>توقيت الرصد:</b> <code>{now_str}</code>\n"
        f"📊 <b>وضع البيتكوين:</b> {btc_icon} <b>{btc.get('status_text', '')}</b>\n"
        f"⚡ <b>الفرص الطازجة للدخول الآن:</b> <b>{len(fresh_signals)}</b>\n"
        f"⚠️ <b>صفقات جارية انطلقت مسبقاً:</b> <b>{len(running_signals)}</b>\n"
        f"────────────────────"
    )
    messages.append(header)

    # 1. Fresh Entries (سعرها ممتاز وما زالت في نطاق الشراء)
    if fresh_signals:
        lines = [
            f"🟢 <b>صفقات جديدة طازجة (في نطاق الدخول الآمن الآن)</b>\n"
            f"────────────────────"
        ]
        for s in fresh_signals:
            if s.get('is_confluent'):
                models_block = (
                    f"🌟 <b>توافق استراتيجي مضاعف ({s['confluence_count']} نماذج متزامنة!):</b>\n" +
                    "\n".join([f"  • {m}" for m in s['matched_models']])
                )
            else:
                models_block = f"• <b>النموذج:</b> {s['model_name']}"

            lines.append(
                f"{s['model_badge']}\n"
                f"🔥 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"{models_block}\n"
                f"• <b>سعر الدخول:</b> <code>{format_price(s['price'])} $</code>\n"
                f"• <b>📍 حالة الدعم:</b> <b>{s['support_desc']}</b>\n"
                f"• <b>السيولة الحجمية:</b> <code>{s['vol_ratio']}x</code> فوليوم أعلى من المعدل\n"
                f"• 📊 <b>إحصائية النموذج:</b> <i>{s['win_rate_desc']}</i>\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{format_price(s['target_1'])} $</code>\n"
                f"• 🚀 <b>هدف الموجه (+6%):</b> <code>{format_price(s['target_2'])} $</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{format_price(s['stop_loss'])} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 2. Running Trades (انطلقت سابقاً ولم تُرسل في أولها وهي شغالة حالياً)
    if running_signals:
        lines = [
            f"⚠️ <b>صفقات قيد التشغيل حالياً (انطلقت سابقاً ولم تُرسل في بدايتها)</b>\n"
            f"<i>(هذه الصفقات بدأت حركتها قبل ساعات وصعدت بالفعل - لا تدخل الآن تجنباً للشراء عند القمة، تُذكر للمتابعة فقط)</i>\n"
            f"────────────────────"
        ]
        for s in running_signals:
            intra = s['intraday_status']
            if s.get('is_confluent'):
                models_block = f"• <b>النماذج:</b> " + " + ".join(s['matched_models'])
            else:
                models_block = f"• <b>النموذج:</b> {s['model_name']}"

            ign_p = intra.get('ignition_price', s.get('price', 0))
            cur_p_now = intra.get('cur_price', s.get('price', 0))
            gain_p = intra.get('gain_pct', 0.0)
            max_gain_p = intra.get('max_gain_pct', 0.0)
            high_p = intra.get('today_high', s.get('price', 0))
            ign_t = intra.get('ignition_time', 'اليوم')

            lines.append(
                f"💎 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"{models_block}\n"
                f"• ⏰ <b>وقت الانطلاق التقريبي:</b> الساعة <code>{ign_t}</code>\n"
                f"• 💵 <b>سعر الانطلاق المفترض:</b> <code>{format_price(ign_p)} $</code>\n"
                f"• 🚀 <b>السعر الحالي الآن:</b> <code>{format_price(cur_p_now)} $</code> (صعدت بالفعل <b>+{gain_p}%</b>)\n"
                f"• 🎯 <b>أعلى قمة وصلتها اليوم:</b> <code>{format_price(high_p)} $</code> (أقصى صعود <b>+{max_gain_p}%</b>)\n"
                f"• 📍 <b>حالة الدعم:</b> {s['support_desc']}\n"
                f"🛑 <b>تنبيه هام:</b> الصفقة جارية وحققت معظم الهدف اللحظي مسبقاً - <b>لا تدخل الآن</b> تجنباً للشراء عند القمة!\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    for m in messages:
        send_telegram_message(chat_id, m)
        time.sleep(1)


def hourly_scheduler_loop():
    """Runs hourly market check in background every 60 minutes."""
    print("Hourly Squeeze & Momentum Scanner Thread Started (Interval: 1 hour)...")
    # Wait 10 seconds on initial boot, then loop every 3600s
    time.sleep(10)
    while True:
        try:
            print(f"[{datetime.now()}] Running automatic hourly scan...")
            execute_hourly_scan(config.TELEGRAM_CHAT_ID)
        except Exception as e:
            print(f"Error in hourly scheduler: {e}")
        time.sleep(3600)


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
                            f"👋 <b>أهلاً بك في رادار النخبة الرقمي (Elite Crypto Radar 1D)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"⚡ <b>القسم الأول: صفقات الهدف الخاطف السريع (+3% في 24-48 ساعة):</b>\n"
                            f"1️⃣ 🚀 <b>SuperTrend Flip:</b> دقة 82% في أول يومين (80% في اليوم الأول) | 96% إجمالي | فشل 4% فقط.\n"
                            f"2️⃣ 👑 <b>ATR 15% Expansion:</b> دقة 74% في أول يومين | 95.5% إجمالي | فشل 4.5% | أرباح +115.4%.\n\n"
                            f"🚀 <b>القسم الثاني: تعظيم الأرباح والموجات (TP 6% / SL 4%):</b>\n"
                            f"1️⃣ 💰 <b>Ehlers Fisher Transform:</b> أرباح قياسية صافية +188.6% | معامل ربحية PF 1.58.\n"
                            f"2️⃣ ⚡ <b>Elder's Force Index (EFI):</b> أرباح صافية +156.7% | معامل ربحية PF 1.50.\n"
                            f"3️⃣ 💎 <b>TTM Squeeze Breakout:</b> أرباح صافية +98.2% | معامل ربحية PF 1.58.\n\n"
                            f"────────────────────\n"
                            f"📌 <b>الأوامر المتاحة:</b>\n"
                            f"• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص السوق الشامل وإرسال كافة الفرص الحالية مرتبة من الأقوى للأضعف.\n"
                            f"• أرسل <b>ساعة</b> أو <code>/hourly</code>: لتشغيل فحص الصيد اللحظي للفرص الجديدة التي دخلتها السيولة حديثاً.\n"
                            f"• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع البيتكوين بالنسبة لـ Daily EMA50.\n"
                            f"• أرسل <code>/ping</code>: لاختبار الاتصال مع باينانس.\n\n"
                            f"💡 <i>ملاحظة: البوت يفحص السوق تلقائياً كل 60 دقيقة في الخلفية، ويرسل لك تنبيهاً فورياً فقط عند اكتشاف انفجار سيولة جديد!</i>"
                        )
                        send_telegram_message(chat_id, welcome)
                        
                    elif text_lower in ["رادار", "/radar", "radar", "بيتكوين", "btc"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["ساعة", "ساعه", "/hourly", "hourly", "لحظي", "فحص ساعي", "فحص كل ساعة"]:
                        threading.Thread(target=execute_hourly_scan, args=(chat_id,), daemon=True).start()

                    elif text_lower in ["فحص", "مسح", "/scan", "scan", "فرص", "الفرص", "صفقات", "tmo", "hull", "supertrend", "atr", "fisher"]:
                        threading.Thread(target=execute_scan, args=(chat_id, False), daemon=True).start()
                        
                    else:
                        reply = (
                            "❓ <b>الأوامر المتاحة:</b>\n"
                            "• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص شامل لكافة الفرص مرتبة من الأقوى للأضعف.\n"
                            "• أرسل <b>ساعة</b> أو <code>/hourly</code>: لفحص لحظي للفرص الجديدة التي اشتعلت سيولتها الآن.\n"
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
    print("Elite Crypto Trading Bot starting (with Hourly Real-Time Scanner)...")
    
    # Start Health Server
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start Hourly Scanner Background Thread (Runs every 1 hour)
    hourly_thread = threading.Thread(target=hourly_scheduler_loop, daemon=True)
    hourly_thread.start()
    print("Hourly Scanner thread launched successfully.")

    # Start Telegram Listener
    handle_telegram_updates()
