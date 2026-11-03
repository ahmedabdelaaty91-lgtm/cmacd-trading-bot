import time
import json
import requests
import threading
from datetime import datetime, timezone
import config
from strategy import check_btc_regime, scan_market, scan_market_1d, scan_market_1w, fetch_klines, check_macd_exit
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
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def format_radar_message():
    btc = check_btc_regime()
    if 'error' in btc:
        return f"⚠️ <b>خطأ في الرادار:</b> {btc['error']}"
        
    status_icon = "🟢 <b>مسار صاعد (BULLISH)</b>" if btc['is_bull'] else "🔴 <b>مسار تصحيحي / هابط (BEARISH)</b>"
    banker_icon = "🟢 تدفق سيولة حيتان نشطة" if btc.get('banker_active') else "⚪ سيولة هادئة"
    
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
        msg += "✅ <b>الضوء الأخضر مُفعّل:</b> السوق في مسار إيجابي يسمح باقتناص جميع الصفقات بنسب نجاح تصل إلى 88%."
    else:
        msg += "🛡️ <b>البيتكوين تحت EMA50:</b> ينصح بالتركيز التام على إشارات <b>المستوى الماسي VIP (دقة >80%)</b> مع الالتزام الصارم بتأمين الوقف."
    return msg

def format_strategies_list():
    msg = (
        f"📋 <b>قائمة أقوى الاستراتيجيات المعتمدة في البوت (مرتبة بالأداء والدقة):</b>\n"
        f"────────────────────\n"
        f"👑 <b>1. المستوى الملكي الخارق (الفلتر المزدوج VWAP + دعم 85% - 90.5%):</b>\n"
        f"• 💣 انفجار البولنجر مع الفلتر المزدوج (90.5% | PF 9.21) 🏆\n"
        f"• 👑 تقاطع EMA 9/21 فوق السحابة (88.0% | PF 6.12)\n"
        f"• 🎯 تقاطع EMA 20/100 مع الفلتر المزدوج (88.0% | PF 4.50)\n"
        f"• ☁️ اختراق سحابة إيشيموكو مع الفلتر المزدوج (87.0% | PF 4.88)\n"
        f"• 🌟 التقاطع الذهبي الكلاسيكي EMA 50/200 مع الفلتر المزدوج (85.0% | PF 4.10)\n"
        f"• 📊 تقاطع MACD تحت الصفر مع الفلتر المزدوج (85.0% | PF 5.59)\n\n"
        f"💎 <b>2. المستوى الماسي الممتاز (نسبة نجاح 80% - 84.9%):</b>\n"
        f"• ☁️ اختراق سحابة إيشيموكو بفوليوم (83.9% | PF 4.20)\n"
        f"• 💎 توليفة VIP لـ EMA 9/21 مع الفلتر المزدوج (83.5% | PF 4.32)\n"
        f"• 🎯 تقاطع EMA 50/100 مع الفلتر المزدوج (83.0% | PF 3.50)\n"
        f"• 💣 انفجار البولنجر بهدف خاطف قياسي (82.7% | PF 4.12)\n"
        f"• 🚀 تقاطع EMA 9/21 فوق EMA 50 (82.7% | PF 3.99)\n"
        f"• ⚡ تقاطع EMA 9/21 بطفرة فوليوم (81.6% | PF 3.94)\n"
        f"• 💎 توليفة VIP لـ EMA 20/50 مع الفلتر المزدوج (81.5% | PF 3.10)\n"
        f"• 🏆 تقاطع خط RSI مع الفلتر المزدوج (80.3% | PF 2.93)\n\n"
        f"🥇 <b>3. المستوى الذهبي القياسي (نسبة نجاح 76% - 79.9%):</b>\n"
        f"• ☁️ اختراق سحابة إيشيموكو قياسي (79.3%)\n"
        f"• 🌟 التقاطع الذهبي الكلاسيكي EMA 50/200 القياسي (79.2%)\n"
        f"• 🛡️ تقاطع EMA 9/21 عند الدعم الأفقي (77.1%)\n"
        f"• 📊 تقاطع MACD تحت الصفر عند الدعم (77.0%)\n"
        f"• 🎯 تقاطع EMA 9/21 بهدف خاطف سريع (76.4%)\n"
        f"• 🎯 تقاطع EMA 50/100 بهدف خاطف (76.7%)\n\n"
        f"🏛️ <b>4. استراتيجيات الماكرو الأسبوعية (1W Swings):</b>\n"
        f"• 👑 تقاطع MACD أسبوعي تحت الصفر (87.5% | PF 6.54)\n"
        f"• ☁️ اختراق سحابة إيشيموكو أسبوعي (83.3% | PF 6.04)\n"
        f"• 💣 انفجار البولنجر أسبوعي (80.0% | PF 3.93)\n"
        f"────────────────────\n"
        f"⚡ <i>نظام التتبع الذكي يفحص كل 4 ساعات ويرسل تنبيهاً خاصاً فور اكتمال تأكيد الـ 4H دون تكرار أي صفقة سابقة!</i>"
    )
    return msg

def format_advisory_signal_message(sig, btc_status):
    sym = sig['symbol']
    cur_p = sig['current_price']
    vol = sig.get('volume_24h', 0)
    
    if vol >= 1_000_000:
        vol_str = f"{vol / 1_000_000:.1f}M $"
    elif vol >= 1_000:
        vol_str = f"{vol / 1_000:.1f}K $"
    else:
        vol_str = f"{vol:,.0f} $"

    # 1. Weekly Macro Signal
    if sig.get('timeframe') == '1W':
        msg = (
            f"🏛️ <b>تنبيه استثماري أسبوعي ماكرو (Weekly Macro Signal):</b>\n"
            f"────────────────────\n"
            f"🪙 <b>العملة:</b> <code>{sym} / USDT</code> [فريم الأسبوع 1W]\n"
            f"🏆 <b>الاستراتيجية:</b> <b>{sig['strategy_name']}</b>\n"
            f"📊 <b>الرتبة والدقة:</b> <b>{sig['tier_badge']}</b> (معامل ربحية {sig['profit_factor']})\n"
            f"💰 <b>السعر الحالي:</b> <code>{cur_p} $</code>\n"
            f"────────────────────\n"
            f"🎯 <b>خطة السوينغ الأسبوعي المعتمدة:</b>\n"
            f"• 🎯 <b>هدف الربح المقترح (+{sig['tp_pct']}%):</b> <code>{sig['tp_price']} $</code>\n"
            f"• 🛑 <b>وقف الخسارة الأولي (-{sig['sl_pct']}%):</b> <code>{sig['sl_price']} $</code>\n"
            f"• 🛡️ <b>سعر تأمين الوقف (+{sig['be_pct']}%):</b> <code>{sig['be_price']} $</code> (نقل الوقف للدخول)\n"
            f"────────────────────\n"
            f"💡 <i>هذه فرصة دورة صعود استثمارية كبرى على فريم الأسبوع (Macro Swing).</i>\n"
            f"🔗 <a href='{sig['chart_url']}'>فتح الشارت على TradingView</a>"
        )
        return msg

    # 2. Daily Signal with 4H MTF Confirmation
    mtf_icon = "✅" if sig.get('mtf_confirmed') else "⏳"
    dual_filter_icon = "🏆 مكتمل بنجاح (VIP 85%-90.5%) 🟢" if sig.get('is_dual_filter') else "⚪ عادي"
    msg = (
        f"{sig['tier_badge']}\n"
        f"────────────────────\n"
        f"🪙 <b>العملة:</b> <code>{sym} / USDT</code> [فريم اليومي 1D]\n"
        f"💰 <b>السعر اللحظي:</b> <code>{cur_p} $</code>\n"
        f"📊 <b>فوليوم 24 ساعة:</b> <code>{vol_str}</code>\n"
        f"────────────────────\n"
        f"🛡️ <b>الفلتر المزدوج الذهبي (Dual Filter):</b>\n"
        f"• <b>حالة الفلتر:</b> <b>{dual_filter_icon}</b>\n"
        f"• <b>مؤشر VWAP:</b> {sig.get('vwap_desc', '')}\n"
        f"• <b>مؤشر الدعم:</b> {sig.get('support_desc', '')}\n"
        f"────────────────────\n"
        f"⚡ <b>تأكيد فريم الـ 4 ساعات اللحظي (MTF Timing):</b>\n"
        f"• <b>حالة الدخول:</b> {mtf_icon} <b>{sig.get('mtf_badge', '')}</b>\n"
        f"• <b>التفاصيل:</b> {sig.get('mtf_details', '')}\n"
        f"────────────────────\n"
        f"🎯 <b>خطة إدارة الصفقة المقترحة:</b>\n"
        f"• 🎯 <b>هدف الربح (+{sig['tp_pct']}%):</b> <code>{sig['tp_price']} $</code>\n"
        f"• 🛑 <b>وقف الخسارة الأولي (-{sig['sl_pct']}%):</b> <code>{sig['sl_price']} $</code>\n"
        f"• 🛡️ <b>تأمين الصفقة عند (+{sig['be_pct']}%):</b> <code>{sig['be_price']} $</code> (رفع الوقف للدخول)\n"
        f"────────────────────\n"
        f"💡 <b>إعداد الوقف المتحرك على باينانس (Trailing Stop):</b>\n"
        f"• نوع الأمر: <b>Trailing Stop</b>\n"
        f"• سعر التفعيل (Activation Price): <code>{sig['be_price']} $</code>\n"
        f"• معدل التتبع (Trailing Delta): <code>1.5%</code>\n"
        f"────────────────────\n"
        f"🔗 <a href='{sig['chart_url']}'>فتح الشارت على TradingView</a>\n"
        f"⚠️ <i>إشعار استشاري: القرار النهائي للشراء والتنفيذ يدوياً على باينانس يعود لك.</i>"
    )
    return msg

def format_mtf_now_confirmed_message(sig):
    """Special high-priority alert when a coin was waiting for 4H and just got fully confirmed!"""
    sym = sig['symbol']
    cur_p = sig['current_price']
    dual_filter_icon = "🏆 مكتمل بنجاح (VIP 85%-90.5%) 🟢" if sig.get('is_dual_filter') else "⚪ عادي"
    return (
        f"🟢⚡ <b>تأكيد دخول عاجل: صفقة تأكدت الآن على فريم 4 ساعات (الضوء الأخضر كامل - ادخل الآن)!</b>\n"
        f"────────────────────\n"
        f"🪙 <b>العملة:</b> <code>{sym} / USDT</code> [1D + 4H Confirmed ✅]\n"
        f"🏆 <b>الاستراتيجية:</b> <b>{sig['strategy_name']}</b> ({sig['tier_badge']})\n"
        f"💰 <b>سعر الدخول الحالي:</b> <code>{cur_p} $</code>\n"
        f"────────────────────\n"
        f"🛡️ <b>الفلتر المزدوج:</b> <b>{dual_filter_icon}</b>\n"
        f"• <b>مؤشر VWAP:</b> {sig.get('vwap_desc', '')}\n"
        f"• <b>مؤشر الدعم:</b> {sig.get('support_desc', '')}\n"
        f"────────────────────\n"
        f"✅ <b>تحديث فريم الـ 4 ساعات:</b>\n"
        f"الصفقة دي كانت ظهرت على اليومي وبانتظار تأكيد 4H، <b>والآن شمعة الـ 4 ساعات أغلقت وتأكدت بالكامل!</b>\n"
        f"• <b>التفاصيل:</b> {sig.get('mtf_details', '')}\n"
        f"────────────────────\n"
        f"🎯 <b>خطة التنفيذ الفوري للصفقة:</b>\n"
        f"• 🎯 <b>هدف الربح (+{sig['tp_pct']}%):</b> <code>{sig['tp_price']} $</code>\n"
        f"• 🛑 <b>وقف الخسارة الأولي (-{sig['sl_pct']}%):</b> <code>{sig['sl_price']} $</code>\n"
        f"• 🛡️ <b>سعر تأمين الوقف (+{sig['be_pct']}%):</b> <code>{sig['be_price']} $</code> (نقل الوقف لسعر الدخول فوراً)\n"
        f"────────────────────\n"
        f"💡 <b>إعداد الوقف المتحرك على باينانس (Trailing Stop):</b>\n"
        f"• نوع الأمر: <b>Trailing Stop</b>\n"
        f"• سعر التفعيل (Activation Price): <code>{sig['be_price']} $</code>\n"
        f"• معدل التتبع (Trailing Delta): <code>1.5%</code>\n"
        f"────────────────────\n"
        f"👉 <b>الآن الدخول آمن ومكتمل الشروط بالكامل!</b>\n"
        f"🔗 <a href='{sig['chart_url']}'>فتح الشارت على TradingView</a>"
    )

def execute_scan_cycle(chat_id=None, is_scheduled_4h=False):
    """
    Unified scanner executed manually or every 4 hours automatically.
    Prevents repeating signals and specifically notifies when a pending 4H trade gets confirmed!
    """
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
        
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    db.clean_old_signal_states(today_str)
    
    # If manual scan, notify user that scan started
    if not is_scheduled_4h:
        current_wl = config.get_watchlist()
        send_telegram_message(
            chat_id, 
            f"🔍 <b>بدء المسح الشامل المزدوج (فريم اليومي 1D وفريم الأسبوعي 1W)...</b>\n"
            f"⏱️ <i>يتم فحص {len(current_wl)} عملة بديلة مع التأكيد اللحظي على فريم الـ 4 ساعات (MTF)...</i>"
        )
        
    scan_res = scan_market()
    btc = scan_res['btc_status']
    signals_1d = scan_res['signals_1d']
    signals_1w = scan_res['signals_1w']
    scanned_count = scan_res.get('all_scanned_count', len(config.get_watchlist()))
    
    new_confirmed_transitions = []
    brand_new_signals = []
    
    # Process 1D Signals with smart de-duplication and 4H transition detection
    for sig in signals_1d:
        pair = sig['pair']
        sym = sig['symbol']
        is_mtf = bool(sig.get('mtf_confirmed'))
        old_state = db.get_signal_state(pair, today_str)
        
        if old_state is None:
            # 1. Brand new signal detected for the first time today
            brand_new_signals.append(sig)
            db.save_or_update_signal_state(pair, sym, today_str, sig, mtf_notified=1 if is_mtf else 0)
        else:
            # 2. Coin was already found today! Check if it was waiting and is NOW CONFIRMED!
            was_confirmed = bool(old_state.get('mtf_confirmed'))
            was_notified = bool(old_state.get('mtf_notified'))
            
            if not was_confirmed and is_mtf and not was_notified:
                # The exact condition user asked for: Was waiting, now confirmed -> GO ENTER!
                new_confirmed_transitions.append(sig)
                db.mark_mtf_notified(pair, today_str)
            else:
                # Already notified or still waiting, DO NOT SPAM!
                pass

    # 1. Send High-Priority "NOW CONFIRMED! GO ENTER!" Alerts
    for sig in new_confirmed_transitions:
        msg = format_mtf_now_confirmed_message(sig)
        send_telegram_message(chat_id, msg)
        time.sleep(1)

    # 2. If it's a scheduled 4H check:
    if is_scheduled_4h:
        # If there are brand new signals or transitions, send only the new ones!
        for sig in brand_new_signals:
            msg = format_advisory_signal_message(sig, btc)
            send_telegram_message(chat_id, msg)
            time.sleep(1)
            
        # Send Weekly signals only if newly detected and not alerted today
        for sig in signals_1w:
            if not db.was_alerted_today(sig['symbol'], today_str):
                msg = format_advisory_signal_message(sig, btc)
                send_telegram_message(chat_id, msg)
                db.record_alert(sig['symbol'], sig['pair'], today_str, 0, sig['current_price'], "Weekly Macro")
                time.sleep(1)
                
        print(f"[{now_utc.strftime('%H:%M UTC')}] 4H Scheduled Scan completed: {len(new_confirmed_transitions)} transitions, {len(brand_new_signals)} new signals.")
        return

    # 3. If it's a Manual / Daily Scan, send comprehensive overview:
    total_signals = len(signals_1d) + len(signals_1w)
    if total_signals == 0:
        msg = (
            f"📊 <b>تقرير فحص السوق الكامل ({scanned_count} عملة):</b>\n"
            f"────────────────────\n"
            f"• <b>سعر البيتكوين:</b> <code>{btc['price']:,.1f} $</code> ({'فوق EMA50 🟢' if btc.get('is_bull') else 'تحت EMA50 🔴'})\n"
            f"• <b>الفرص المؤكدة اليوم:</b> 0 فرصة.\n"
            f"ℹ️ تم فحص كامل القائمة بدقة. لا توجد فرص متسرعة، البوت يلتزم فقط بالفرص المكتملة الشروط بنسب فوز تفوق 74%."
        )
        send_telegram_message(chat_id, msg)
        return
        
    mtf_confirmed_count = len([s for s in signals_1d if s.get('mtf_confirmed')])
    dual_filter_count = len([s for s in signals_1d if s.get('is_dual_filter')])
    header_msg = (
        f"🎯 <b>تقرير رصد الفرص الذهبية المؤكدة:</b>\n"
        f"────────────────────\n"
        f"• <b>العملات المفحوصة:</b> {scanned_count} عملة.\n"
        f"• <b>إشارات فريم اليومي (1D):</b> {len(signals_1d)} فرصة.\n"
        f"• 👑 <b>فرص مكتملة الفلتر المزدوج (VWAP + دعم 85%-90.5%):</b> {dual_filter_count} فرصة.\n"
        f"• ⚡ <b>إشارات مؤكدة بالكامل على فريم 4H (جاهزة للدخول):</b> {mtf_confirmed_count} عملة.\n"
        f"• 🏛️ <b>إشارات الماكرو الأسبوعية (1W):</b> {len(signals_1w)} فرصة استثمارية.\n"
        f"────────────────────\n"
        f"👇 <i>تفاصيل كل فرصة موضحة في الرسائل التالية:</i>"
    )
    send_telegram_message(chat_id, header_msg)
    time.sleep(1)
    
    # Send Weekly Macro Signals first
    for sig in signals_1w:
        msg = format_advisory_signal_message(sig, btc)
        send_telegram_message(chat_id, msg)
        time.sleep(1)
        
    # Send Daily Signals (MTF confirmed first)
    for sig in signals_1d:
        msg = format_advisory_signal_message(sig, btc)
        send_telegram_message(chat_id, msg)
        time.sleep(1)

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
                            f"👋 <b>أهلاً بك في بوت التحليل الاستشاري المزدوج (1D + 1W MTF Radar)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"🎯 <b>نظام الفحص والتتبع الذكي:</b>\n"
                            f"• ⏱️ <b>فحص تلقائي كل 4 ساعات:</b> يبحث عن الفرص الجديدة دون تكرار أي إشارة سابقة.\n"
                            f"• ⚡ <b>تنبيه تأكيد الـ 4 ساعات:</b> إذا كانت هناك صفقة تنتظر تأكيد 4H واكتملت الآن، سيرسل لك تنبيهاً فورياً (خش الآن 🟢)!\n"
                            f"• 🏛️ <b>فريم الأسبوعي (1W):</b> رصد دورات القيعان والبول رن الاستثماري الكبرى.\n\n"
                            f"الأوامر المتاحة:\n"
                            f"• اكتب <b>فحص</b> أو <code>/scan</code>: لتشغيل مسح فوري شامل الآن.\n"
                            f"• اكتب <b>استراتيجيات</b> أو <code>/strategies</code>: لعرض قائمة الاستراتيجيات الذهبية.\n"
                            f"• اكتب <b>رادار</b> أو <code>/radar</code>: لمعرفة وضع البيتكوين.\n"
                            f"• اكتب <b>اتصال</b> أو <code>/ping</code>: لاختبار الاتصال بباينانس."
                        )
                        send_telegram_message(chat_id, welcome)
                        
                    elif text_lower in ["استراتيجيات", "/strategies", "strategies"]:
                        send_telegram_message(chat_id, format_strategies_list())
                        
                    elif text_lower in ["رادار", "/radar", "radar"]:
                        send_telegram_message(chat_id, format_radar_message())
                        
                    elif text_lower in ["اتصال", "باينانس", "/ping", "ping"]:
                        res = client.check_connection()
                        send_telegram_message(chat_id, res['message'])
                        
                    elif text_lower in ["فحص", "مسح", "/scan", "scan", "يومي", "/scan1d", "اسبوعي", "/scan1w"]:
                        threading.Thread(target=execute_scan_cycle, args=(chat_id, False), daemon=True).start()
                        
                    else:
                        reply = "❓ أمر غير معروف. اكتب <b>فحص</b> أو <b>استراتيجيات</b> أو <b>رادار</b>."
                        send_telegram_message(chat_id, reply)
        except Exception as e:
            time.sleep(3)

def four_hour_scheduler_loop():
    """
    Automatically triggers execute_scan_cycle every 4 hours:
    At 00:02, 04:02, 08:02, 12:02, 16:02, 20:02 UTC.
    Checks for new confirmed 4H setups and notifies without duplicating past alerts!
    """
    print("4-Hour Automatic MTF Scanner Thread Started.")
    last_slot = None
    
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if now_utc.hour % 4 == 0 and now_utc.minute >= 2:
                slot_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour}"
                if last_slot != slot_id:
                    print(f"Triggering Scheduled 4-Hour Scan for slot {slot_id}...")
                    execute_scan_cycle(config.TELEGRAM_CHAT_ID, is_scheduled_4h=True)
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
                "service": "CMACD MTF Binance Trading Bot",
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
    print("CMACD MTF Trading Bot Daemon starting...")
    
    # Start Health Server
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start 4-Hour Automatic MTF Scheduler
    scheduler_4h_thread = threading.Thread(target=four_hour_scheduler_loop, daemon=True)
    scheduler_4h_thread.start()
    
    # Start Telegram Listener
    handle_telegram_updates()
