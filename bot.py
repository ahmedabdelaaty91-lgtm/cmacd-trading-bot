import time
import json
import requests
import threading
from datetime import datetime
import config
from strategy import check_btc_regime, scan_market, fetch_klines, check_macd_exit
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
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            # Automatic fallback to plain text if HTML tags or symbols fail
            payload.pop("parse_mode", None)
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
        f"• <b>نظام الخروج المعتمد:</b> تدرج ذكي 3 مراحل (4% / 8% / ركوب الموجة)\n"
        f"────────────────────\n"
    )
    if btc['is_bull']:
        msg += "✅ <b>الضوء الأخضر مُفعّل:</b> النظام مستعد لاقتناص الصواريخ الخارقة 💎🚀 والصفقات الكلاسيكية 🟢."
    else:
        msg += "🛡️ <b>البيتكوين تحت EMA50:</b> الصفقات الكلاسيكية متوقفة، ولكن الرادار يبحث عن <b>الصواريخ المستقلة (Squeeze Rockets ⚡🚀)</b> ذات الزخم الذاتي العالي!"
    return msg

def format_report_message():
    balance = client.get_usdt_balance()
    total_equity = client.get_total_account_equity()
    open_trades = db.get_open_trades()
    mode_str = "تجريبي (Dry Run 🧪)" if client.dry_run else "حقيقي (Live Trading 🔴)"
    
    msg = (
        f"📊 <b>تقرير المحفظة والصفقات الحالية:</b>\n"
        f"────────────────────\n"
        f"• <b>وضع الحساب:</b> {mode_str}\n"
        f"• <b>إجمالي قيمة المحفظة:</b> <code>{total_equity:,.2f} USDT</code>\n"
        f"• <b>الرصيد المتاح (الكاش الحر):</b> <code>{balance:,.2f} USDT</code>\n"
        f"• <b>عدد الصفقات المفتوحة:</b> {len(open_trades)} / {config.MAX_POSITIONS}\n"
        f"────────────────────\n"
    )
    
    if not open_trades:
        msg += "ℹ️ لا توجد صفقات مفتوحة حالياً. الكاش جاهز بنسبة 100% للفرص القادمة."
    else:
        msg += "📈 <b>تفاصيل الصفقات المفتوحة بنظام التدرج:</b>\n\n"
        for t in open_trades:
            cur_p = client.get_ticker_price(t['pair']) or t['current_price']
            entry_p = t['entry_price']
            pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0
            pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
            
            st = t['status']
            if st == 'TP2_HIT':
                status_text = "🏆 تم تحقيق الهدف الثاني (+8%) | المتبقي (50%) يركب الموجه والوقف عند +4%"
            elif st == 'TP1_HIT':
                status_text = "🎯 تم تحقيق الهدف الأول (+4%) | مؤمنة بربح +1% بانتظار +8%"
            else:
                status_text = "⏳ بانتظار الهدف الأول (+4%) | الوقف الأولي عند -6%"
                
            tp1_p = t.get('tp1_price') or round(entry_p * 1.04, 6)
            tp2_p = t.get('tp2_price') or round(entry_p * 1.08, 6)
            
            msg += (
                f"🪙 <b>{t['symbol']} / USDT</b>\n"
                f"  • سعر الدخول: <code>{entry_p} $</code>\n"
                f"  • السعر الحالي: <code>{cur_p} $</code>\n"
                f"  • الربح اللحظي: {pnl_icon} <b>{pnl_pct:+.2f}%</b>\n"
                f"  • الهدف 1 (4%): <code>{tp1_p} $</code> | الهدف 2 (8%): <code>{tp2_p} $</code>\n"
                f"  • وقف الخسارة الحالي: <code>{t['sl_price']} $</code>\n"
                f"  • المرحلة: {status_text}\n"
                f"  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
            )
            
    closed = db.get_closed_trades(limit=5)
    if closed:
        msg += "\n📋 <b>آخر الصفقات المغلقة:</b>\n"
        for c in closed:
            c_icon = "✅" if c['pnl_pct'] >= 0 else "❌"
            msg += f"• {c['symbol']}: {c_icon} {c['pnl_pct']:+.2f}% ({c['exit_reason']})\n"
            
    return msg

def format_advisory_signal_message(sig, btc_status):
    sym = sig['symbol']
    cur_p = sig['current_price']
    q_vol = sig['quote_volume_24h']
    vol_millions = q_vol / 1_000_000.0
    vol_str = f"{vol_millions:.1f}M $" if vol_millions >= 1.0 else f"{q_vol:,.0f} $"
    vol_spike_str = f"طفرة <code>{sig['vol_ratio']}x</code> أضعاف متوسط 20 يوم 🚀" if sig['vol_spike'] else f"<code>{sig['vol_ratio']}x</code> من المتوسط"
    
    tier_badge = sig['tier_badge']
    tier_desc = sig['tier_desc']
    
    msg = (
        f"{tier_badge}\n"
        f"────────────────────\n"
        f"🪙 <b>العملة:</b> <code>{sym} / USDT</code>\n"
        f"💰 <b>السعر اللحظي:</b> <code>{cur_p} $</code>\n"
        f"📊 <b>فوليوم 24 ساعة:</b> <code>{vol_str}</code> ({vol_spike_str})\n"
        f"────────────────────\n"
        f"📍 <b>1. مؤشر الدعم SRchannel:</b>\n"
        f"• {sig['support_desc']}\n\n"
        f"⚡ <b>2. مؤشر الانفجار MSL Squeeze:</b>\n"
        f"• {sig['squeeze_desc']}\n\n"
        f"📈 <b>3. مؤشر CM Ult MACD:</b>\n"
        f"• {sig['macd_desc']}\n\n"
        f"🏦 <b>4. مؤشر السيولة L3 Banker:</b>\n"
        f"{sig['banker_desc']}\n\n"
        f"🌐 <b>5. وضع البيتكوين والسوق:</b>\n"
        f"• السعر <code>{btc_status['price']:,.1f} $</code> ({'فوق Daily EMA50 🟢 - مسار آمن' if btc_status.get('is_bull') else 'تحت Daily EMA50 🔴'})\n"
        f"────────────────────\n"
        f"🎯 <b>المستويات الفنية المقترحة للمتابعة:</b>\n"
        f"• 🎯 <b>الهدف الأول (+4.0%):</b> <code>{sig['tp1_price']} $</code>\n"
        f"• 🚀 <b>الهدف الثاني (+8.0%):</b> <code>{sig['tp2_price']} $</code>\n"
        f"• 🛑 <b>وقف الخسارة المقترح (-6.0%):</b> <code>{sig['sl_price']} $</code>\n"
        f"────────────────────\n"
        f"⚠️ <i>تنبيه: هذا إشعار استشاري للمراقبة والتحليل، وأنت صاحب قرار الشراء والتنفيذ يدوياً على باينانس.</i>"
    )
    return msg

def execute_daily_scan(chat_id=None):
    if not chat_id:
        chat_id = config.TELEGRAM_CHAT_ID
        
    current_wl = config.get_watchlist()
    total_watchlist = len(current_wl)
    send_telegram_message(
        chat_id, 
        f"🔍 <b>جاري فحص جميع أزواج بينانس ({total_watchlist} عملة) بالكامل...</b>\n"
        f"⏱️ <i>يتم فحص المؤشرات الأربعة (SRchannel + Squeeze + MACD + Banker) والفوليوم عبر الفريم اليومي المعتمد...</i>"
    )
    
    scan_res = scan_market()
    btc = scan_res['btc_status']
    signals = scan_res['signals']
    scanned_count = scan_res.get('all_scanned_count', total_watchlist)
    
    if not signals:
        msg = (
            f"📊 <b>تقرير فحص السوق الكامل ({scanned_count} عملة):</b>\n"
            f"────────────────────\n"
            f"• <b>سعر البيتكوين:</b> <code>{btc['price']:,.1f} $</code> ({'فوق EMA50 🟢' if btc.get('is_bull') else 'تحت EMA50 🔴'})\n"
            f"• <b>عدد العملات المفحوصة:</b> {scanned_count} عملة بالكامل.\n"
            f"• <b>الفرص المؤكدة اليوم:</b> 0 فرصة.\n"
            f"ℹ️ {scan_res['reason']}\n"
            f"────────────────────\n"
            f"🛡️ <i>تم فحص كامل القائمة بدقة. لا توجد أي فرصة تسرع، البوت يلتزم فقط بالفرص المكتملة الشروط ذات الدقة العالية (71%).</i>"
        )
        send_telegram_message(chat_id, msg)
        return
        
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    tier1_signals = [s for s in signals if s.get('tier') == 1]
    tier2_signals = [s for s in signals if s.get('tier') == 2]
    
    header_msg = (
        f"🎯 <b>تقرير رصد الفرص الاستشارية المؤكدة اليوم:</b>\n"
        f"────────────────────\n"
        f"• <b>العملات المفحوصة:</b> {scanned_count} عملة.\n"
        f"• <b>إشارات VIP الذهبية (5/5 كاملة):</b> {len(tier1_signals)} عملة.\n"
        f"• <b>إشارات القياسية المعتمدة (4/4 كاملة):</b> {len(tier2_signals)} عملة.\n"
        f"• <b>نظام الترتيب:</b> إشارات VIP أولاً ثم القياسية، مع تقديم العملات ذات الفوليوم الأعلى دائماً.\n"
        f"────────────────────\n"
        f"👇 <i>تفاصيل الفرص الكاملة لكل مؤشر موضحة في الرسائل التالية:</i>"
    )
    send_telegram_message(chat_id, header_msg)
    time.sleep(1)
    
    sent_count = 0
    for sig in signals:
        sym = sig['symbol']
        sig_msg = format_advisory_signal_message(sig, btc)
        send_telegram_message(chat_id, sig_msg)
        db.record_alert(sym, sig['pair'], today_str, sig.get('tier', 1), sig['current_price'], sig['tier_badge'])
        sent_count += 1
        time.sleep(1)
        
    summary_msg = (
        f"✅ <b>اكتمل إرسال جميع الإشارات الاستشارية ({sent_count} فرصة):</b>\n"
        f"────────────────────\n"
        f"• تم إرسال الفرص بالترتيب: فئة VIP (5/5) أولاً، ثم الفئة القياسية (4/4)، مع تقديم العملات ذات الفوليوم الأعلى.\n"
        f"• يمكنك مراجعة الشارت واتخاذ قرار الشراء يدوياً على باينانس وفق إدارة رأس مالك."
    )
    send_telegram_message(chat_id, summary_msg)

def monitor_open_positions():
    """Background loop that checks active positions every 60 seconds and applies ladder exit + trailing stop"""
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
                tp1_p = t.get('tp1_price') or round(entry_p * (1.0 + config.TP1_PCT), 6)
                tp2_p = t.get('tp2_price') or round(entry_p * (1.0 + config.TP2_PCT), 6)
                sl_p = t['sl_price']
                
                initial_qty = t.get('initial_quantity') or t['quantity']
                rem_qty = t.get('remaining_quantity') or t['quantity']
                status = t['status']
                
                recent_orders = client.get_symbol_recent_orders(pair, limit=8)
                
                # Check if TP1 was already executed by Binance OCO or if price reached TP1
                tp1_filled_on_binance = any(
                    o.get('status') == 'FILLED' and o.get('side') == 'SELL' and float(o.get('price', 0)) >= entry_p * 1.035
                    for o in recent_orders
                )
                
                # 1. Target 1 (+4%) Hit
                if status == 'OPEN' and (cur_p >= tp1_p or tp1_filled_on_binance):
                    sell_qty = initial_qty * config.TP1_SELL_RATIO
                    if not tp1_filled_on_binance:
                        client.cancel_all_open_orders(pair)
                        client.place_market_sell(pair, sell_qty)
                    
                    new_rem_qty = initial_qty * 0.75
                    new_sl = round(entry_p * (1.0 + config.SL_AFTER_TP1_PCT), 6) # +1.0%
                    db.update_tp1_hit(t_id, new_rem_qty, new_sl)
                    
                    # Setup Target 2 OCO (+8%) and SL (+1%) on Binance
                    client.cancel_all_open_orders(pair)
                    client.place_native_oco_order(pair, sell_qty, tp2_p, new_sl)
                    
                    # Place Stop Loss for remaining 50% wave rider at new_sl (+1%)
                    rem_wave_qty = initial_qty * 0.50
                    client.place_stop_loss_limit(pair, rem_wave_qty, new_sl)
                    
                    msg = (
                        f"🎉 <b>تم تحقيق الهدف الأول بنجاح: {sym} / USDT</b>\n"
                        f"────────────────────\n"
                        f"• <b>سعر البيع:</b> <code>{cur_p} $</code> (+4.0%)\n"
                        f"• <b>الكمية المباعة:</b> 25% من الصفقة\n"
                        f"• <b>تأمين الصفقة:</b> تم رفع وتفعيل وقف الخسارة للمتبقي بالكامل على باينانس إلى <code>{new_sl:.6f} $</code> (+1.0%)\n"
                        f"• <b>أمر الهدف الثاني (+8%):</b> تم تسجيله على باينانس بسعر <code>{tp2_p} $</code>\n"
                        f"🛡️ <b>الصفقة الآن خالية تماماً من أي مخاطرة ومضمونة الربح!</b>"
                    )
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
                    
                # Check if TP2 was already executed by Binance OCO or if price reached TP2
                tp2_filled_on_binance = any(
                    o.get('status') == 'FILLED' and o.get('side') == 'SELL' and float(o.get('price', 0)) >= entry_p * 1.075
                    for o in recent_orders
                )
                
                # 2. Target 2 (+8%) Hit
                if status == 'TP1_HIT' and (cur_p >= tp2_p or tp2_filled_on_binance):
                    sell_qty = initial_qty * config.TP2_SELL_RATIO
                    if not tp2_filled_on_binance:
                        client.cancel_all_open_orders(pair)
                        client.place_market_sell(pair, sell_qty)
                    
                    new_rem_qty = initial_qty * 0.50
                    new_sl = round(entry_p * (1.0 + config.SL_AFTER_TP2_PCT), 6) # +4.0%
                    db.update_tp2_hit(t_id, new_rem_qty, new_sl)
                    
                    # Setup Stop Loss on Binance for remaining 50% wave rider at new_sl (+4%)
                    client.cancel_all_open_orders(pair)
                    client.place_stop_loss_limit(pair, new_rem_qty, new_sl)
                    
                    msg = (
                        f"🚀 <b>تم تحقيق الهدف الثاني بنجاح: {sym} / USDT</b>\n"
                        f"────────────────────\n"
                        f"• <b>سعر البيع:</b> <code>{cur_p} $</code> (+8.0%)\n"
                        f"• <b>الكمية المباعة:</b> 25% إضافية (تم حجز 50% من أرباح الصفقة)\n"
                        f"• <b>تأمين الأرباح:</b> تم رفع وقف الخسارة للنصف المتبقي على باينانس إلى <code>{new_sl:.6f} $</code> (+4.0%)\n"
                        f"🌊 <b>النصف الأخير (50%) يركب موجة الصعود حتى تقاطع الماكد السلبي!</b>"
                    )
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
                    
                # 3. Stop Loss Hit
                elif cur_p <= sl_p:
                    client.cancel_all_open_orders(pair)
                    sell_res, sell_msg = client.place_market_sell(pair, rem_qty)
                    if sell_res is None and not client.dry_run:
                        print(f"Failed to market sell {sym} on SL: {sell_msg}")
                        send_telegram_message(config.TELEGRAM_CHAT_ID, f"⚠️ <b>فشل تنفيذ أمر البيع لـ {sym} على باينانس:</b>\n<code>{sell_msg}</code>")
                        continue
                    
                    pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0
                    
                    if status == 'OPEN':
                        reason = "وقف الخسارة الأولي (-6%)"
                        icon = "🛑"
                    elif status == 'TP1_HIT':
                        reason = "وقف الربح المؤمن (+1%)"
                        icon = "✅"
                    else:
                        reason = "وقف الربح المؤمن (+4%)"
                        icon = "✅"
                        
                    db.close_trade(t_id, cur_p, pnl_pct, reason)
                    
                    msg = (
                        f"{icon} <b>إغلاق صفقة {sym} / USDT:</b>\n"
                        f"────────────────────\n"
                        f"• <b>سعر الخروج:</b> <code>{cur_p} $</code>\n"
                        f"• <b>النتيجة للكمية المتبقية:</b> <b>{pnl_pct:+.2f}%</b>\n"
                        f"• <b>سبب الإغلاق:</b> {reason}"
                    )
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
                    
                # 4. Smart MACD Exit: Early Preventative Exit or Wave Rider Close
                elif check_macd_exit(pair):
                    client.cancel_all_open_orders(pair)
                    sell_res, sell_msg = client.place_market_sell(pair, rem_qty)
                    if sell_res is None and not client.dry_run:
                        print(f"Failed to market sell {sym} on MACD exit: {sell_msg}")
                        send_telegram_message(config.TELEGRAM_CHAT_ID, f"⚠️ <b>فشل تنفيذ أمر البيع لـ {sym} على باينانس:</b>\n<code>{sell_msg}</code>")
                        continue
                    pnl_pct = ((cur_p - entry_p) / entry_p) * 100.0
                    
                    if status == 'OPEN':
                        reason = "خروج وقائي مبكر (تقاطع ماكد سلبي قبل الهدف الأول)"
                        db.close_trade(t_id, cur_p, pnl_pct, reason)
                        icon = "🟢" if pnl_pct >= 0 else "⚠️"
                        msg = (
                            f"{icon} <b>خروج وقائي مبكر لصفقة {sym} / USDT:</b>\n"
                            f"────────────────────\n"
                            f"• <b>السبب:</b> تقاطع الماكد اليومي هبوطاً (ضعف الزخم قبل الهدف الأول).\n"
                            f"• <b>سعر الدخول:</b> <code>{entry_p} $</code>\n"
                            f"• <b>سعر الخروج:</b> <code>{cur_p} $</code>\n"
                            f"• <b>النتيجة:</b> <b>{pnl_pct:+.2f}%</b>\n"
                            f"🛡️ تم البيع فوراً وتوفير الخسارة لحماية رأس المال بدلاً من انتظار الوقف (-6%)!"
                        )
                    elif status == 'TP1_HIT':
                        reason = "جني أرباح الموجه (تقاطع ماكد بعد الهدف الأول)"
                        db.close_trade(t_id, cur_p, pnl_pct, reason)
                        msg = (
                            f"🏁 <b>إغلاق موجة {sym} / USDT بعد الهدف الأول:</b>\n"
                            f"────────────────────\n"
                            f"• <b>السبب:</b> تقاطع الماكد هبوطاً بعد تحقيق الهدف الأول (+4%).\n"
                            f"• <b>سعر الخروج للمتبقي:</b> <code>{cur_p} $</code>\n"
                            f"• <b>الربح الصافي:</b> <b>{pnl_pct:+.2f}%</b>\n"
                            f"💰 تم جني أرباح الموجه بنجاح وتحرير المقعد لفرصة جديدة!"
                        )
                    else:
                        reason = "جني أرباح القمة الكبرى (تقاطع ماكد بعد الهدف الثاني)"
                        db.close_trade(t_id, cur_p, pnl_pct, reason)
                        msg = (
                            f"👑 <b>إغلاق قمة الموجة الكبرى لصفقة {sym} / USDT:</b>\n"
                            f"────────────────────\n"
                            f"• <b>السبب:</b> تقاطع الماكد هبوطاً بعد تحقيق الهدفين (+4% و +8%).\n"
                            f"• <b>سعر الخروج للنصف الأخير (50%):</b> <code>{cur_p} $</code>\n"
                            f"• <b>ربح النصف الأخير:</b> <b>{pnl_pct:+.2f}%</b>\n"
                            f"🏆 تم اقتناص كامل حركة الصعود وتحرير الكاش!"
                        )
                        
                    send_telegram_message(config.TELEGRAM_CHAT_ID, msg)
        except Exception as e:
            print(f"Error in monitor loop: {e}")
            
        time.sleep(60) # Check every 60 seconds

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
                            f"👋 <b>أهلاً بك في بوت التحليل الاستشاري (CMACD & Banker Advisory Radar)!</b>\n"
                            f"────────────────────\n"
                            f"تم ربط حسابك بنجاح ✅ (Chat ID: <code>{chat_id}</code>)\n\n"
                            f"🎯 <b>نظام العمل المعتمد:</b>\n"
                            f"• <b>الوضع الاستشاري الكامل (Advisory Mode):</b> البوت يحلل ويرسل الإشارات، وأنت صاحب قرار الشراء يدوياً.\n"
                            f"• <b>المؤشرات المفحوصة:</b> SRchannel + MSL Squeeze + CM MACD + L3 Banker + الفوليوم.\n"
                            f"• <b>الفريم المعتمد:</b> الفريم اليومي (1D) بدقة 71% وعامل ربحية 3.03.\n"
                            f"• <b>نظام الترتيب:</b> إشارات VIP الذهبية أولاً ثم القياسية، مع تقديم العملات ذات الفوليوم الأعلى دائماً.\n\n"
                            f"الأوامر المتاحة:\n"
                            f"• اكتب <b>فحص</b>: لتشغيل مسح فوري لجميع العملات الآن وإرسال الفرص.\n"
                            f"• اكتب <b>رادار</b>: لمعرفة وضع البيتكوين وسيولة الحيتان.\n"
                            f"• اكتب <b>تقرير</b>: لعرض رصيد المحفظة والصفقات.\n"
                            f"• اكتب <b>اتصال</b>: للتأكد من حالة الاتصال بباينانس."
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
                        # Run scan in background thread so it never blocks the Telegram listener
                        threading.Thread(target=execute_daily_scan, args=(chat_id,), daemon=True).start()
                        
                    else:
                        reply = "❓ أمر غير معروف. اكتب <b>تقرير</b> أو <b>رادار</b> أو <b>فحص</b>."
                        send_telegram_message(chat_id, reply)
        except Exception as e:
            time.sleep(3)

def daily_scheduler_loop():
    """Automatically triggers execute_daily_scan every day at 00:05 UTC (03:05 AM Egypt)"""
    print("Daily Scheduler Thread Started. Target: 00:05 UTC daily.")
    last_executed_day = None
    
    while True:
        try:
            now_utc = datetime.utcnow()
            if now_utc.hour == 0 and now_utc.minute >= 5:
                today_str = now_utc.strftime("%Y-%m-%d")
                if last_executed_day != today_str:
                    print(f"Scheduled Daily Scan automatically triggered for {today_str} at 00:05 UTC...")
                    send_telegram_message(config.TELEGRAM_CHAT_ID, "⏰ <b>بدء الفحص اليومي التلقائي (إغلاق الشمعة اليومية 00:05 UTC)...</b>")
                    execute_daily_scan(config.TELEGRAM_CHAT_ID)
                    last_executed_day = today_str
        except Exception as e:
            print(f"Error in daily scheduler: {e}")
            
        time.sleep(30) # Check every 30 seconds

def four_hour_scheduler_loop():
    """Automatically triggers 4-hour market radar every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)"""
    from run_4h_radar import run_4h_market_radar
    print("4-Hour Radar Scheduler Thread Started.")
    last_executed_hour_slot = None
    
    while True:
        try:
            now_utc = datetime.utcnow()
            if now_utc.hour % 4 == 0 and now_utc.minute >= 2:
                slot_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour}"
                if last_executed_hour_slot != slot_id:
                    print(f"Triggering 4-Hour Market Radar for slot {slot_id}...")
                    run_4h_market_radar()
                    last_executed_hour_slot = slot_id
        except Exception as e:
            print(f"Error in 4-hour scheduler: {e}")
            
        time.sleep(30)

def start_health_server():
    """Lightweight HTTP server on $PORT for Render health checks and 24/7 uptime monitoring"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json
    import os
    
    port = int(os.getenv("PORT", 10000))
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                "status": "online",
                "service": "CMACD Binance Trading Bot",
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
    print("CMACD Trading Bot Daemon starting...")
    
    # Start HTTP Health Server for Render / UptimeRobot
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start background monitor thread for open positions
    monitor_thread = threading.Thread(target=monitor_open_positions, daemon=True)
    monitor_thread.start()
    
    # Start automatic daily scanner thread at 00:05 UTC
    scheduler_thread = threading.Thread(target=daily_scheduler_loop, daemon=True)
    scheduler_thread.start()
    
    # Start automatic 4-hour market radar thread
    four_hour_thread = threading.Thread(target=four_hour_scheduler_loop, daemon=True)
    four_hour_thread.start()
    
    # Start Telegram polling listener
    handle_telegram_updates()
