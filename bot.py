import time
import json
import requests
import threading
import re
import os
from datetime import datetime, timezone, timedelta
import config
import database
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


def get_now_time_str():
    """Returns local Cairo time along with UTC for crystal-clear clarity."""
    utc_now = datetime.now(timezone.utc)
    egypt_now = utc_now + timedelta(hours=2)
    ap = 'ص' if egypt_now.hour < 12 else 'م'
    return f"{egypt_now.strftime('%I:%M')} {ap} بتوقيت مصر ({utc_now.strftime('%H:%M')} UTC)"


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


def manage_open_trades(chat_id=None):
    """
    Monitors all open positions on Binance Spot:
    - Checks live ticker price.
    - If TP1 (+3%) reached: sells 50% of position and moves Stop-Loss to Break-Even (entry price).
    - If TP2 (+6%) reached: sells remaining 50% and closes trade with full profit.
    - If SL hit (either initial -4% SL or Break-Even entry price): sells 100% and closes trade.
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID

    open_trades = database.get_open_trades()
    if not open_trades:
        return

    print(f"[{datetime.now()}] Monitoring {len(open_trades)} active positions...")
    for t in open_trades:
        pair = t['pair']
        symbol = t['symbol']
        entry_price = t['entry_price']
        status = t['status']
        remaining_qty = t['remaining_quantity']
        tp1_price = t['tp1_price']
        tp2_price = t['tp2_price']
        sl_price = t['sl_price']

        cur_price = client.get_ticker_price(pair)
        if not cur_price:
            continue

        database.update_trade_current_price(t['id'], cur_price)
        gain_pct = ((cur_price - entry_price) / entry_price) * 100

        # 1. Target 2 Reached (+6% or higher)
        if cur_price >= tp2_price:
            sell_res, sell_msg = client.place_market_sell(pair, quantity=None)
            if sell_res:
                database.close_trade(t['id'], cur_price, 'TP2_HIT', round(gain_pct, 2))
                msg = (
                    f"🚀 <b>تحقيق الهدف الثاني (+6%) بنجاح وإغلاق الصفقة بالكامل!</b> 🏆\n"
                    f"────────────────────\n"
                    f"• العملة: <b>#{symbol}</b> | <code>{pair}</code>\n"
                    f"• سعر الدخول: <code>{format_price(entry_price)} $</code>\n"
                    f"• سعر البيع: <code>{format_price(cur_price)} $</code>\n"
                    f"• 💰 <b>نسبة الربح المحققة:</b> <b>+{gain_pct:.2f}%</b>\n"
                    f"• حالة الخروج: تم بيع كامل الكمية المتبقية وجني الأرباح بالكامل ✅\n"
                    f"────────────────────"
                )
                send_telegram_message(chat_id, msg)
            else:
                print(f"Failed to sell TP2 for {pair}: {sell_msg}")
            continue

        # 2. Target 1 Reached (+3% or higher)
        if status == 'OPEN' and cur_price >= tp1_price:
            half_qty = remaining_qty / 2.0
            sell_res, sell_msg = client.place_market_sell(pair, quantity=half_qty)
            if sell_res:
                sold_qty = float(sell_res.get('executedQty', half_qty))
                new_remaining = max(0.0, remaining_qty - sold_qty)
                
                if new_remaining <= 0.0001:
                    database.close_trade(t['id'], cur_price, 'TP1_FULL_DUST', round(gain_pct, 2))
                    msg = (
                        f"🎯 <b>تحقيق الهدف الأول (+3%) وتم بيع كامل الصفقة!</b> 💰\n"
                        f"────────────────────\n"
                        f"• العملة: <b>#{symbol}</b> | <code>{pair}</code>\n"
                        f"• سعر الدخول: <code>{format_price(entry_price)} $</code>\n"
                        f"• سعر البيع: <code>{format_price(cur_price)} $</code> (+{gain_pct:.2f}%)\n"
                        f"• الإجراء: تم بيع 100% من العملة لحمايتها من التفتيت (Dust Protection) وجني الأرباح كاملاً!\n"
                        f"────────────────────"
                    )
                else:
                    database.update_trade_tp1_hit(t['id'], new_remaining, entry_price)
                    msg = (
                        f"🎯 <b>تحقيق الهدف الأول (+3%) بنجاح!</b> 💰\n"
                        f"────────────────────\n"
                        f"• العملة: <b>#{symbol}</b> | <code>{pair}</code>\n"
                        f"• سعر الدخول: <code>{format_price(entry_price)} $</code>\n"
                        f"• سعر البيع: <code>{format_price(cur_price)} $</code> (+{gain_pct:.2f}%)\n"
                        f"• الإجراء: تم بيع 50% من الكمية بنجاح 💵\n"
                        f"• 🛡️ <b>تأمين الصفقة:</b> تم نقل وقف الخسارة إلى نقطة الدخول (Break-Even <code>{format_price(entry_price)} $</code>) للاستمرار نحو الهدف الثاني (+6%) بدون أي مخاطرة!\n"
                        f"────────────────────"
                    )
                send_telegram_message(chat_id, msg)
            else:
                print(f"Failed to sell TP1 for {pair}: {sell_msg}")
            continue

        # 3. Stop Loss Hit
        if cur_price <= sl_price:
            sell_res, sell_msg = client.place_market_sell(pair, quantity=None)
            if sell_res:
                is_be = (status == 'TP1_HIT')
                reason = "BREAK_EVEN" if is_be else "STOP_LOSS"
                database.close_trade(t['id'], cur_price, reason, round(gain_pct, 2))
                
                if is_be:
                    msg = (
                        f"🛡️ <b>الخروج على نقطة الدخول (Break-Even) بدون أي خسارة</b>\n"
                        f"────────────────────\n"
                        f"• العملة: <b>#{symbol}</b> | <code>{pair}</code>\n"
                        f"• سعر الدخول: <code>{format_price(entry_price)} $</code>\n"
                        f"• سعر الخروج: <code>{format_price(cur_price)} $</code> ({gain_pct:+.2f}%)\n"
                        f"• الحالة: خرجت الصفقة على نقطة الدخول بعد جني أرباح الهدف الأول مسبقاً بنجاح.\n"
                        f"────────────────────"
                    )
                else:
                    msg = (
                        f"🛑 <b>تفعيل وقف الخسارة الآمن لحماية المحفظة</b>\n"
                        f"────────────────────\n"
                        f"• العملة: <b>#{symbol}</b> | <code>{pair}</code>\n"
                        f"• سعر الدخول: <code>{format_price(entry_price)} $</code>\n"
                        f"• سعر الخروج: <code>{format_price(cur_price)} $</code> ({gain_pct:+.2f}%)\n"
                        f"• تم إغلاق الصفقة التزاماً بنظام إدارة المخاطر الصارم.\n"
                        f"────────────────────"
                    )
                send_telegram_message(chat_id, msg)
            else:
                print(f"Failed to sell SL for {pair}: {sell_msg}")


def format_trades_summary(chat_id):
    """Formats and sends active open positions summary to Telegram."""
    open_trades = database.get_open_trades()
    usdt_bal = client.get_usdt_balance()
    now_str = get_now_time_str()

    if not open_trades:
        msg = (
            f"💼 <b>تقرير محفظة الصفقات المفتوحة (Spot)</b>\n"
            f"────────────────────\n"
            f"⏰ <b>التوقيت:</b> <code>{now_str}</code>\n"
            f"💰 <b>رصيد USDT المتاح:</b> <code>{usdt_bal:.2f} USDT</code>\n"
            f"📭 <b>لا توجد صفقات مفتوحة حالياً.</b>\n"
            f"────────────────────\n"
            f"🤖 <i>البوت في وضع الاستعداد لاقتناص أي فرصة جديدة فور ظهورها!</i>"
        )
        send_telegram_message(chat_id, msg)
        return

    lines = [
        f"💼 <b>تقرير صفقاتك النشطة على باينانس ({len(open_trades)}/{config.MAX_OPEN_POSITIONS})</b>\n"
        f"────────────────────\n"
        f"⏰ <b>التوقيت:</b> <code>{now_str}</code>\n"
        f"💰 <b>رصيد USDT المتاح:</b> <code>{usdt_bal:.2f} USDT</code>\n"
        f"────────────────────"
    ]

    for idx, t in enumerate(open_trades, 1):
        pair = t['pair']
        symbol = t['symbol']
        entry_p = t['entry_price']
        cur_p = client.get_ticker_price(pair) or t.get('current_price', entry_p)
        gain_pct = ((cur_p - entry_p) / entry_p) * 100
        gain_icon = "🟢" if gain_pct >= 0 else "🔴"
        status_badge = "🛡️ مؤمنة (TP1 تحقق)" if t['status'] == 'TP1_HIT' else "⏳ جارية"

        lines.append(
            f"{idx}️⃣ <b>#{symbol}</b> | <code>{pair}</code> ({status_badge})\n"
            f"• سعر الدخول: <code>{format_price(entry_p)} $</code>\n"
            f"• السعر الحالي: <code>{format_price(cur_p)} $</code> ({gain_icon} <b>{gain_pct:+.2f}%</b>)\n"
            f"• الكمية المتبقية: <code>{t['remaining_quantity']}</code>\n"
            f"• 🎯 الهدف 1 (+3%): <code>{format_price(t['tp1_price'])} $</code>\n"
            f"• 🚀 الهدف 2 (+6%): <code>{format_price(t['tp2_price'])} $</code>\n"
            f"• 🛑 الوقف الحالي: <code>{format_price(t['sl_price'])} $</code>\n"
            f"────────────────────"
        )

    send_telegram_message(chat_id, "\n".join(lines))


def execute_hourly_scan(chat_id=None):
    """
    Executes scan across all Binance USDT coins:
    1. Monitors and manages active open positions (TP1 +3% / TP2 +6% / SL -4% / Break-Even).
    2. Consolidates multiple strategies into a single trade per coin (No duplicates!).
    3. Inspects 1H candles to detect if an opportunity already ignited hours ago.
    4. Categorizes into:
       - Fresh Entries (🟢 في نطاق الشراء المثالي الآن).
       - Already-Running Trades (⚠️ انطلقت سابقاً ولم تُرسل في أولها وهي شغالة حالياً - لا تدخل الآن).
    5. Deduplicates against today's cache.
    6. If AUTO_TRADE is enabled: automatically places MARKET BUY orders on Binance for fresh signals.
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    # 0. Always manage existing open positions first!
    try:
        manage_open_trades(chat_id)
    except Exception as e:
        print(f"Error managing open trades: {e}")

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
    now_str = get_now_time_str()

    if not unalerted:
        print(f"[{datetime.now()}] Scan complete: No unalerted opportunities. Notifying Telegram...")
        total_tracked = len(all_signals)
        open_trades = database.get_open_trades()
        trades_count_str = f"\n📦 <b>الصفقات النشطة قيد الإدارة:</b> <b>{len(open_trades)}</b> صفقات" if open_trades else ""
        no_new_msg = (
            f"⏱️ <b>تقرير الرادار الدوري (رصد كل 20 دقيقة)</b>\n"
            f"────────────────────\n"
            f"⏰ <b>توقيت الفحص:</b> <code>{now_str}</code>\n"
            f"📊 <b>وضع البيتكوين:</b> {btc_icon} <b>{btc.get('status_text', '')}</b>\n"
            f"🔍 <b>النتيجة:</b> <b>لا توجد أي فرص جديدة طازجة دخلتها السيولة هذه الدورة.</b>\n"
            f"💡 <i>(السوق هادئ حالياً ولا توجد أي انفجارات سيولة جديدة).</i>\n"
            f"────────────────────\n"
            f"📌 <b>إجمالي الفرص النشطة القائمة:</b> <b>{total_tracked}</b> فرصة{trades_count_str}\n"
            f"👉 أرسل <b>فحص</b> أو <code>/scan</code> لعرض كامل تفاصيل الفرص، أو <b>صفقات</b> لعرض صفقاتك النشطة."
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
    print(f"[{datetime.now()}] Scan detected {new_total} coins ({len(fresh_signals)} fresh, {len(running_signals)} running). Dispatching...")

    messages = []
    header = (
        f"🚨 <b>رادار الصيد اللحظي (فحص كل 20 دقيقة)</b>\n"
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

    # 3. Auto-Trade Execution on Binance Spot for Fresh Signals
    if config.AUTO_TRADE and fresh_signals:
        for s in fresh_signals:
            open_trades = database.get_open_trades()
            if len(open_trades) >= config.MAX_OPEN_POSITIONS:
                print(f"Max positions limit ({config.MAX_OPEN_POSITIONS}) reached. Skipping buy for {s['symbol']}.")
                break
            if database.is_pair_open(s['pair']):
                print(f"Pair {s['pair']} already open in database. Skipping duplicate buy.")
                continue

            usdt_bal = client.get_usdt_balance()
            if usdt_bal < config.TRADE_AMOUNT_USDT:
                warn_msg = (
                    f"⚠️ <b>تنبيه رصيد غير كافٍ لفتح صفقة تلقائية:</b>\n"
                    f"• العملة: <b>#{s['symbol']}</b> (<code>{s['pair']}</code>)\n"
                    f"• الرصيد المتاح: <code>{usdt_bal:.2f} USDT</code>\n"
                    f"• المطلوب لكل صفقة: <code>{config.TRADE_AMOUNT_USDT:.2f} USDT</code>"
                )
                send_telegram_message(chat_id, warn_msg)
                break

            print(f"Auto-buying {s['pair']} with {config.TRADE_AMOUNT_USDT} USDT on Binance Spot...")
            buy_order, buy_msg = client.place_market_buy(s['pair'], config.TRADE_AMOUNT_USDT)
            if buy_order:
                fill_price = buy_order.get('avg_price', s['price'])
                fill_qty = buy_order.get('executed_qty', round(config.TRADE_AMOUNT_USDT / fill_price, 6))
                tp1 = round(fill_price * (1 + config.FAST_TARGET_PCT), 6)
                tp2 = round(fill_price * (1 + config.RUNNER_TARGET_PCT), 6)
                sl = round(fill_price * (1 - config.STOP_LOSS_PCT), 6)

                database.insert_new_trade(s['symbol'], s['pair'], fill_price, fill_qty, tp1, tp2, sl)
                trade_alert = (
                    f"⚡ <b>تم فتح صفقة شراء جديدة تلقائياً على باينانس!</b> 🟢\n"
                    f"────────────────────\n"
                    f"• العملة: <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                    f"• 💵 <b>سعر الشراء الفعلي:</b> <code>{format_price(fill_price)} $</code>\n"
                    f"• 📦 <b>الكمية المشتراة:</b> <code>{fill_qty}</code>\n"
                    f"• 💰 <b>قيمة الصفقة:</b> <code>{config.TRADE_AMOUNT_USDT:.2f} USDT</code>\n"
                    f"• 🎯 <b>الهدف الأول (+3%):</b> <code>{format_price(tp1)} $</code> (بيع 50% وتأمين الدخول)\n"
                    f"• 🚀 <b>الهدف الثاني (+6%):</b> <code>{format_price(tp2)} $</code> (بيع كامل الكمية المتبقية)\n"
                    f"• 🛑 <b>وقف الخسارة (-4%):</b> <code>{format_price(sl)} $</code>\n"
                    f"────────────────────\n"
                    f"🤖 <i>البوت يتابع الصفقة تلقائياً على مدار الساعة وينفذ أوامر البيع عند الأهداف بدقة!</i>"
                )
                send_telegram_message(chat_id, trade_alert)
            else:
                fail_msg = (
                    f"❌ <b>تعذر فتح صفقة #{s['symbol']} على باينانس:</b>\n"
                    f"<code>{buy_msg}</code>"
                )
                send_telegram_message(chat_id, fail_msg)


def hourly_scheduler_loop():
    """Runs market check in background every 20 minutes."""
    print("Squeeze & Momentum Scanner Thread Started (Interval: 20 minutes)...")
    time.sleep(10)
    while True:
        try:
            print(f"[{datetime.now()}] Running automatic 20-min scan...")
            execute_hourly_scan(config.TELEGRAM_CHAT_ID)
        except Exception as e:
            print(f"Error in scheduler: {e}")
        time.sleep(1200) # 20 minutes


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
                        trade_mode_desc = "مُفعّل (شراء وبيع آلي على باينانس) 🟢" if config.AUTO_TRADE else "استشاري وتنبيهات فقط (Advisory) ⚪"
                        welcome = (
                            f"👋 <b>أهلاً بك في رادار النخبة الرقمي للتداول الآلي (Elite Auto-Trade Bot)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n"
                            f"• <b>وضع التداول الآلي:</b> {trade_mode_desc}\n"
                            f"• <b>حجم كل صفقة:</b> <code>{config.TRADE_AMOUNT_USDT:.2f} USDT</code>\n"
                            f"• <b>الحد الأقصى للصفقات المتزامنة:</b> <code>{config.MAX_OPEN_POSITIONS}</code> صفقات\n\n"
                            f"⚡ <b>النماذج المعتمدة (قوة علمية رصينة):</b>\n"
                            f"1️⃣ <b>SuperTrend Flip:</b> دقة 82% أول يومين (+3% هدف سريع) | 96% إجمالي.\n"
                            f"2️⃣ <b>ATR Expansion:</b> دقة 74% أول يومين | 95.5% إجمالي | أرباح +115.4%.\n"
                            f"3️⃣ <b>Ehlers Fisher:</b> أرباح قياسية صافية +188.6% (TP 6% / SL 4%).\n"
                            f"4️⃣ <b>Elder's Force Index:</b> أرباح صافية +156.7%.\n"
                            f"5️⃣ <b>TTM Squeeze:</b> أرباح صافية +98.2%.\n\n"
                            f"────────────────────\n"
                            f"📌 <b>الأوامر المتاحة:</b>\n"
                            f"• أرسل <b>صفقات</b> أو <code>/trades</code>: لعرض محفظتك وصفقاتك النشطة حالياً على باينانس ونسبة الربح اللحظية.\n"
                            f"• أرسل <b>حالة</b> أو <code>/status</code>: لعرض إعدادات البوت، وضع التداول، ورصيدك المتاح.\n"
                            f"• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص السوق وإرسال كامل الفرص القائمة مرتبة.\n"
                            f"• أرسل <b>ساعة</b> أو <code>/hourly</code>: لتشغيل فحص الصيد اللحظي للفرص الجديدة.\n"
                            f"• أرسل <b>بيع [رمز العملة]</b> مثل <code>بيع PHA</code>: للخروج اليدوي الفوري من أي صفقة.\n"
                            f"• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع البيتكوين بالنسبة لـ EMA50.\n"
                            f"• أرسل <code>/ping</code>: لاختبار الاتصال المباشر مع باينانس.\n\n"
                            f"💡 <i>ملاحظة: البوت يفحص السوق تلقائياً كل 20 دقيقة ويقتنص الفرص فور اشتعالها!</i>"
                        )
                        send_telegram_message(chat_id, welcome)

                    elif text_lower in ["صفقات", "صفقاتي", "/trades", "trades"]:
                        format_trades_summary(chat_id)

                    elif text_lower in ["حالة", "الوضع", "/status", "status"]:
                        bal = client.get_usdt_balance()
                        open_c = len(database.get_open_trades())
                        mode_str = "🟢 <b>تداول آلي مباشر على باينانس (Auto-Trade ON)</b>" if config.AUTO_TRADE else "⚪ <b>وضع استشاري وتنبيهات فقط (Advisory Mode)</b>"
                        status_msg = (
                            f"⚙️ <b>حالة نظام التداول ورادار النخبة:</b>\n"
                            f"────────────────────\n"
                            f"• <b>نظام التداول:</b> {mode_str}\n"
                            f"• <b>رصيد USDT المتاح:</b> <code>{bal:.2f} USDT</code>\n"
                            f"• <b>الصفقات النشطة الآن:</b> <code>{open_c} / {config.MAX_OPEN_POSITIONS}</code>\n"
                            f"• <b>حجم كل صفقة:</b> <code>{config.TRADE_AMOUNT_USDT:.2f} USDT</code>\n"
                            f"• 🎯 <b>الهدف الأول (TP1):</b> <code>+{config.FAST_TARGET_PCT * 100:.1f}%</code> (بيع 50% وتأمين)\n"
                            f"• 🚀 <b>الهدف الثاني (TP2):</b> <code>+{config.RUNNER_TARGET_PCT * 100:.1f}%</code> (بيع 50%)\n"
                            f"• 🛑 <b>وقف الخسارة (SL):</b> <code>-{config.STOP_LOSS_PCT * 100:.1f}%</code>\n"
                            f"• ⏱️ <b>دورة الفحص:</b> كل 20 دقيقة\n"
                            f"────────────────────"
                        )
                        send_telegram_message(chat_id, status_msg)

                    elif text_lower.startswith("بيع ") or text_lower.startswith("/sell ") or text_lower.startswith("/close "):
                        parts = text.split()
                        if len(parts) >= 2:
                            coin = parts[1].upper().replace("#", "").replace("USDT", "")
                            pair = f"{coin}USDT"
                            sell_res, sell_msg = client.place_market_sell(pair, quantity=None)
                            if sell_res:
                                # Close in DB if tracked
                                open_ts = [t for t in database.get_open_trades() if t['pair'] == pair]
                                cur_p = client.get_ticker_price(pair) or 0.0
                                for t in open_ts:
                                    gain = ((cur_p - t['entry_price']) / t['entry_price']) * 100 if t['entry_price'] > 0 else 0.0
                                    database.close_trade(t['id'], cur_p, 'MANUAL_EXIT', round(gain, 2))
                                send_telegram_message(chat_id, f"✅ <b>تم تنفيذ أمر بيع فوري لعملة #{coin} على باينانس:</b>\n<code>{sell_msg}</code>")
                            else:
                                send_telegram_message(chat_id, f"❌ <b>فشل أمر البيع لعملة #{coin}:</b>\n<code>{sell_msg}</code>")
                        else:
                            send_telegram_message(chat_id, "⚠️ يرجى تحديد رمز العملة، مثال: <code>بيع PHA</code>")
                        
                    elif text_lower in ["رادار", "/radar", "radar", "بيتكوين", "btc"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["ساعة", "ساعه", "/hourly", "hourly", "لحظي", "فحص ساعي", "فحص كل ساعة", "فحص 20"]:
                        threading.Thread(target=execute_hourly_scan, args=(chat_id,), daemon=True).start()

                    elif text_lower in ["فحص", "مسح", "/scan", "scan", "فرص", "الفرص"]:
                        threading.Thread(target=execute_scan, args=(chat_id, False), daemon=True).start()
                        
                    else:
                        reply = (
                            "❓ <b>الأوامر المتاحة:</b>\n"
                            "• أرسل <b>صفقات</b> أو <code>/trades</code>: لمتابعة صفقاتك النشطة ونسبة الربح اللحظية.\n"
                            "• أرسل <b>حالة</b> أو <code>/status</code>: لعرض رصيدك وإعدادات التداول.\n"
                            "• أرسل <b>فحص</b> أو <code>/scan</code>: لفحص شامل لكافة الفرص.\n"
                            "• أرسل <b>ساعة</b> أو <code>/hourly</code>: لفحص لحظي للفرص الجديدة.\n"
                            "• أرسل <b>بيع [رمز]</b> مثل <code>بيع PHA</code>: لبيع أي عملة فوراً.\n"
                            "• أرسل <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع البيتكوين العام."
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
