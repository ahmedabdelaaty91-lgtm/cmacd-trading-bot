import time
import json
import requests
import threading
from datetime import datetime
import config
from strategy import check_btc_regime, scan_market, fetch_klines
import database as db
from binance_client import BinanceClient

client = BinanceClient()

def send_telegram_message(chat_id, text):
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def format_radar_message():
    btc = check_btc_regime()
    if 'error' in btc:
        return f"⚠️ <b>خطأ في الرادار:</b> {btc['error']}"
        
    status_icon = "🟢 <b>مسار صاعد (BULLISH)</b>" if btc['is_bull'] else "🔴 <b>مسار دفاعي / هابط (BEARISH)</b>"
    banker_icon = "🟢 سيولة حيتان نشطة" if btc.get('banker_active') else "⚪ سيولة هادئة"
    
    msg = (
        f"📡 <b>رادار السوق والبيتكوين اللحظي:</b>\n"
        f"────────────────────\n"
        f"• <b>سعر البيتكوين:</b> <code>{btc['price']:,.2f} $</code>\n"
        f"• <b>Daily EMA50:</b> <code>{btc['ema50']:,.2f} $</code>\n"
        f"• <b>الفارق عن المتوسط:</b> <code>{btc['diff_pct']:+.2f}%</code>\n"
        f"• <b>حالة الاتجاه:</b> {status_icon}\n"
        f"• <b>تدفق سيولة المؤسسات:</b> {banker_icon} (مستوى {btc.get('banker_val')})\n"
        f"────────────────────\n"
    )
    if btc['is_bull']:
        msg += "✅ <b>الضوء الأخضر مُفعّل:</b> النظام مستعد لاقتناص فرص العملات البديلة المطابقة للخطة."
    else:
        msg += "🛡️ <b>وضع حماية رأس المال:</b> البيتكوين تحت EMA50، الدخول متوقف لتجنب فخاخ الهبوط."
    return msg

def format_report_message():
    balance = client.get_usdt_balance()
    open_trades = db.get_open_trades()
    mode_str = "تجريبي (Dry Run 🧪)" if client.dry_run else "حقيقي (Live Trading 🔴)"
    
    msg = (
        f"📊 <b>تقرير المحفظة والصفقات الحالية:</b>\n"
        f"────────────────────\n"
        f"• <b>وضع الحساب:</b> {mode_str}\n"
        f"• <b>الرصيد المتاح:</b> <code>{balance:,.2f} USDT</code>\n"
        f"• <b>عدد الصفقات المفتوحة:</b> {len(open_trades)} / {config.MAX_POSITIONS}\n"
        f"────────────────────\n"
    )
    
    if not open_trades:
        msg += "ℹ️ لا توجد صفقات مفتوحة حالياً. الكاش جاهز بنسبة 100% للفرص القادمة."
    else:
        msg += "📈 <b>تفاصيل الصفقات المفتوحة:</b>\n\n"
        for t in open_trades:
            cur_p = client.get_ticker_price(t['pair']) or t['current_price']
            pnl_pct = ((cur_p - t['entry_price']) / t['entry_price']) * 100.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            status_text = "🎯 تم تحقيق الهدف الأول (مؤمنة +1%)" if t['status'] == 'TP1_HIT' else "⏳ بانتظار الهدف الأول (+10%)"
            
            msg += (
                f"🪙 <b>{t['symbol']} / USDT</b>\n"
                f"  • سعر الدخول: <code>{t['entry_price']} $</code>\n"
                f"  • السعر الحالي: <code>{cur_p} $</code>\n"
                f"  • الربح اللحظي: {pnl_icon} <b>{pnl_pct:+.2f}%</b>\n"
                f"  • الهدف الأول (10%): <code>{t['tp1_price']} $</code>\n"
                f"  • وقف الخسارة الحالي: <code>{t['sl_price']} $</code>\n"
                f"  • الحالة: {status_text}\n"
                f"  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            )
            
    closed = db.get_closed_trades(limit=5)
    if closed:
        msg += "\n📋 <b>آخر الصفقات المغلقة:</b>\n"
        for c in closed:
            c_icon = "✅" if c['pnl_pct'] >= 0 else "❌"
            msg += f"• {c['symbol']}: {c_icon} {c['pnl_pct']:+.2f}% ({c['exit_reason']})\n"
            
    return msg

def execute_daily_scan(chat_id=None):
    send_telegram_message(chat_id, "🔍 <b>جاري فحص جميع عملات القائمة (160 عملة) على فريم اليوم...</b>")
    scan_res = scan_market()
    btc = scan_res['btc_status']
    signals = scan_res['signals']
    
    if not btc['is_bull']:
        msg = (
            f"ℹ️ <b>تقرير المسح اليومي:</b>\n"
            f"────────────────────\n"
            f"❌ <b>لا توجد صفقات شراء اليوم.</b>\n"
            f"<b>السبب:</b> البيتكوين ({btc['price']:,.1f} $) تحت متوسط Daily EMA50 ({btc['ema50']:,.1f} $).\n"
            f"🛡️ تم تعليق الدخول لحماية المحفظة من تقلبات السوق."
        )
        send_telegram_message(chat_id, msg)
        return
        
    if not signals:
        msg = (
            f"ℹ️ <b>تقرير المسح اليومي:</b>\n"
            f"────────────────────\n"
            f"• البيتكوين في وضع إيجابي فوق EMA50.\n"
            f"• تم فحص {scan_res.get('all_scanned_count', 160)} عملة بالكامل.\n"
            f"ℹ️ {scan_res['reason']}"
        )
        send_telegram_message(chat_id, msg)
        return
        
    # We have buy signals!
    open_trades = db.get_open_trades()
    available_slots = config.MAX_POSITIONS - len(open_trades)
    
    if available_slots <= 0:
        msg = (
            f"🎯 <b>تم رصد {len(signals)} صفقة جديدة!</b>\n"
            f"⚠️ ولكن المحفظة ممتلئة بالكامل ({config.MAX_POSITIONS} صفقات مفتوحة).\n"
            f"سيتم الانتظار حتى تحقيق هدف لتفريغ كاش."
        )
        send_telegram_message(chat_id, msg)
        return
        
    # Execute top signals up to available slots
    signals_to_take = signals[:available_slots]
    balance = client.get_usdt_balance()
    pos_amount_usdt = balance * config.POSITION_SIZE_PCT
    
    for sig in signals_to_take:
        sym = sig['symbol']
        pair = sig['pair']
        entry_p = sig['current_price']
        sl_p = sig['sl_price']
        tp1_p = sig['tp1_price']
        
        # Place Buy Order on Binance
        order, status_msg = client.place_market_buy(pair, pos_amount_usdt)
        if order:
            qty = float(order.get('executedQty', pos_amount_usdt / entry_p))
            db.add_trade(sym, pair, entry_p, qty, tp1_p, sl_p)
            
            # Place Native OCO Order directly on Binance for 50% of the position!
            oco_order, oco_msg = client.place_native_oco_order(pair, qty * config.TP1_SELL_RATIO, tp1_p, sl_p)
            
            trade_msg = (
                f"🚀 <b>تم فتح صفقة شراء جديدة: {sym} / USDT</b>\n"
                f"────────────────────\n"
                f"• <b>سعر الدخول:</b> <code>{entry_p} $</code>\n"
                f"• <b>حجم الصفقة:</b> 25% (~ <code>{pos_amount_usdt:,.1f} USDT</code>)\n"
                f"• <b>النموذج المكتشف:</b> {', '.join(sig['patterns'])}\n"
                f"• <b>الهدف الأول (+10%):</b> <code>{tp1_p} $</code> (بيع 50%)\n"
                f"• <b>وقف الخسارة الأولي (-6%):</b> <code>{sl_p} $</code>\n"
                f"────────────────────\n"
                f"🛡️ <b>الحماية التلقائية:</b> {oco_msg}\n"
                f"ℹ️ أمر البيع ووقف الخسارة مسجلين داخل سيستم باينانس مباشرة واللاب توب مغلق تماماً!"
            )
            send_telegram_message(chat_id, trade_msg)
        else:
            send_telegram_message(chat_id, f"❌ فشل فتح صفقة {sym}: {status_msg}")

def monitor_open_positions():
    """Background loop that checks active positions every 15 minutes"""
    while True:
        try:
            open_trades = db.get_open_trades()
            for t in open_trades:
                pair = t['pair']
                sym = t['symbol']
                t_id = t['id']
                cur_p = client.get_ticker_price(pair)
                if not cur_p:
                    continue
                    
                entry_p = t['entry_price']
                tp1_p = t['tp1_price']
                sl_p = t['sl_price']
                qty = t['quantity']
                
                # 1. Check if Target 1 (+10%) is hit
                if t['status'] == 'OPEN' and cur_p >= tp1_p:
                    # Sell 50%
                    sell_qty = qty * config.TP1_SELL_RATIO
                    client.place_market_sell(pair, sell_qty)
                    # Move SL to Entry + 1%
                    new_sl = entry_p * (1.0 + config.SL_AFTER_TP1_PCT)
                    db.update_tp1_hit(t_id, new_sl)
                    
                    msg = (
                        f"🎉 <b>تم تحقيق الهدف الأول بنجاح: {sym} / USDT</b>\n"
                        f"────────────────────\n"
                        f"• <b>سعر البيع:</b> <code>{cur_p} $</code> (+10.0%)\n"
                        f"• <b>الكمية المباعة:</b> 50% من الصفقة\n"
                        f"• <b>تأمين الصفقة:</b> تم رفع وقف الخسارة إلى <code>{new_sl:.6f} $</code> (+1.0%)\n"
                        f"🛡️ الصفقة الآن خالية من أي مخاطرة ومضمونة الربح بالكامل!"
                    )
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
                    
                # 2. Check if Stop Loss is hit
                elif cur_p <= sl_p:
                    # Sell remaining quantity
                    remaining_qty = (qty * 0.5) if t['status'] == 'TP1_HIT' else qty
                    client.place_market_sell(pair, remaining_qty)
                    
                    pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0
                    reason = "وقف الربح المؤمن (+1%)" if t['status'] == 'TP1_HIT' else "وقف الخسارة الأولي (-6%)"
                    db.close_trade(t_id, cur_p, pnl_pct, reason)
                    
                    icon = "✅" if pnl_pct >= 0 else "🛑"
                    msg = (
                        f"{icon} <b>إغلاق صفقة {sym} / USDT:</b>\n"
                        f"────────────────────\n"
                        f"• <b>سعر الخروج:</b> <code>{cur_p} $</code>\n"
                        f"• <b>النتيجة الصافية:</b> <b>{pnl_pct:+.2f}%</b>\n"
                        f"• <b>سبب الإغلاق:</b> {reason}"
                    )
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
        except Exception as e:
            print(f"Error in monitor loop: {e}")
            
        time.sleep(300) # Check every 5 minutes

def handle_telegram_updates():
    """Telegram Long-Polling listener"""
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
                        
                    # Save user's chat_id if not saved
                    if not config.TELEGRAM_CHAT_ID:
                        config.TELEGRAM_CHAT_ID = str(chat_id)
                        print(f"Captured Chat ID: {chat_id}")
                        
                    text_lower = text.lower()
                    
                    if text_lower in ["/start", "start", "مرحبا"]:
                        welcome = (
                            f"👋 <b>أهلاً بك في بوت التداول الآلي (CM MACD & Banker Flow)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"الأوامر المتاحة:\n"
                            f"• اكتب <b>تقرير</b>: لعرض الصفقات المفتوحة ورصيد المحفظة.\n"
                            f"• اكتب <b>رادار</b>: لمعرفة وضع البيتكوين وسيولة الحيتان.\n"
                            f"• اكتب <b>اتصال</b>: للتأكد من حالة الاتصال بحسابك في باينانس.\n"
                            f"• اكتب <b>فحص</b>: لتشغيل مسح فوري لـ 160 عملة الآن."
                        )
                        send_telegram_message(chat_id, welcome)
                        
                    elif text_lower in ["تقرير", "التقرير", "/report", "report"]:
                        send_telegram_message(chat_id, format_report_message())
                        
                    elif text_lower in ["رادار", "الرادار", "/radar", "radar"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "بينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["فحص", "مسح", "/scan", "scan"]:
                        execute_daily_scan(chat_id)
                        
                    else:
                        reply = "❓ أمر غير معروف. اكتب <b>تقرير</b> أو <b>رادار</b> أو <b>فحص</b>."
                        send_telegram_message(chat_id, reply)
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    # Start background monitor thread
    monitor_thread = threading.Thread(target=monitor_open_positions, daemon=True)
    monitor_thread.start()
    
    # Start Telegram polling
    handle_telegram_updates()
