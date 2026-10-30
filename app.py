import gradio as gr
import threading
import time
import os
from datetime import datetime
import config
from binance_client import BinanceClient
from database import get_open_trades, get_all_trades
from bot import monitor_open_positions, daily_scheduler_loop, handle_telegram_updates, execute_daily_scan, format_report_message, format_radar_message

client = BinanceClient()

# Start bot background threads automatically on startup
print("Starting background threads in Hugging Face Space...")
threading.Thread(target=monitor_open_positions, daemon=True).start()
threading.Thread(target=daily_scheduler_loop, daemon=True).start()
threading.Thread(target=handle_telegram_updates, daemon=True).start()

def get_live_status():
    eq = client.get_total_account_equity()
    usdt = client.get_usdt_balance()
    trades = get_open_trades()
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    txt = f"### 🟢 حالة البوت: نشط ويعمل 24/7 سحابياً\n"
    txt += f"• **الوقت الحالي:** `{time_str}`\n"
    txt += f"• **إجمالي رأس المال (Equity):** `{eq:,.2f} USDT`\n"
    txt += f"• **الكاش الحر المتاح:** `{usdt:,.2f} USDT`\n"
    txt += f"• **عدد الصفقات المفتوحة:** `{len(trades)} / 4`\n\n"
    
    if trades:
        txt += "#### 📋 الصفقات المفتوحة حالياً:\n"
        for t in trades:
            sym = t['symbol']
            ep = t['entry_price']
            tp1 = t.get('tp1_price', 0)
            sl = t.get('sl_price', 0)
            status = t.get('status', 'OPEN')
            txt += f"- **{sym}**: دخول: `{ep}$` | هدف1: `{tp1}$` | وقف: `{sl}$` | الحالة: `{status}`\n"
    else:
        txt += "لا توجد صفقات مفتوحة حالياً. الخانات شاغرة بانتظار إشارات الفحص اليومي."
        
    return txt

def check_binance():
    res = client.check_connection()
    return res.get('message', 'تم الفحص.')

def trigger_manual_scan():
    threading.Thread(target=execute_daily_scan, args=(config.TELEGRAM_CHAT_ID,), daemon=True).start()
    return "🚀 تم بدء الفحص اليومي لـ 161 عملة في الخلفية! سيصلك التقرير كاملاً على تليجرام فور الانتهاء."

# Gradio Dashboard Layout
with gr.Blocks(title="CMACD Binance Bot", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚀 لوحة تحكم بوت التداول الآلي (CMACD & Squeeze)")
    gr.Markdown("يعمل هذا السيرفر سحابياً على مدار الساعة 24/7 ويراقب صفقاتك على باينانس ويرسل لك التحديثات على تليجرام.")
    
    status_output = gr.Markdown(value=get_live_status)
    refresh_btn = gr.Button("🔄 تحديث حالة المحفظة الآن", variant="primary")
    refresh_btn.click(fn=get_live_status, outputs=status_output)
    
    with gr.Row():
        test_btn = gr.Button("🔌 اختبار الاتصال بباينانس", variant="secondary")
        scan_btn = gr.Button("🔍 تشغيل فحص يدوي للسوق الآن", variant="secondary")
        
    action_output = gr.HTML()
    test_btn.click(fn=check_binance, outputs=action_output)
    scan_btn.click(fn=trigger_manual_scan, outputs=action_output)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
