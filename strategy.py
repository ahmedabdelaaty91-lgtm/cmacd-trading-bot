import os
import json
import concurrent.futures
import pandas as pd
import numpy as np
import requests
from config import BINANCE_DATA_URL, BINANCE_REST_URL, get_watchlist

def fetch_klines_fast(symbol, interval="1d", limit=160):
    """
    Fetches daily or 4H klines fast with failover between Binance vision and rest endpoints.
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        f"{BINANCE_DATA_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"{BINANCE_REST_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=4)
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 90:
                    df = pd.DataFrame(data, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_asset_volume', 'trades', 'taker_base', 'taker_quote', 'ignore'
                    ])
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = df[col].astype(float)
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                    return df
        except Exception:
            continue
    return None

def calc_ichimoku_and_indicators(df):
    """
    Calculates Tenkan-sen, Kijun-sen, Senkou Span A, Senkou Span B, Kumo Cloud,
    RSI (14), EMA 50, EMA 200, and Volume MA.
    """
    h = df['high']
    l = df['low']
    c = df['close']
    v = df['volume']
    
    # 1. Tenkan-sen (9)
    df['tenkan'] = (h.rolling(9).max() + l.rolling(9).min()) / 2.0
    
    # 2. Kijun-sen (26)
    df['kijun'] = (h.rolling(26).max() + l.rolling(26).min()) / 2.0
    
    # 3. Senkou Span A (shifted 26 periods ahead)
    span_a_raw = (df['tenkan'] + df['kijun']) / 2.0
    df['span_a'] = span_a_raw.shift(26)
    df['future_span_a'] = span_a_raw # 26 periods ahead into the future
    
    # 4. Senkou Span B (52 periods shifted 26 periods ahead)
    span_b_raw = (h.rolling(52).max() + l.rolling(52).min()) / 2.0
    df['span_b'] = span_b_raw.shift(26)
    df['future_span_b'] = span_b_raw # 26 periods ahead into the future
    
    # Cloud boundaries at current candle
    df['kumo_top'] = np.maximum(df['span_a'], df['span_b'])
    df['kumo_bottom'] = np.minimum(df['span_a'], df['span_b'])
    
    # RSI (14)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100.0 - (100.0 / (1.0 + (avg_g / (avg_l + 1e-9))))
    
    # Dynamic Supports
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    df['vol_ma20'] = v.rolling(20).mean()
    
    return df

def find_swing_support(df, idx, lookback=35):
    """Checks if the low at idx is near a recent prominent swing low support"""
    start = max(0, idx - lookback)
    cur_low = df['low'].iloc[idx]
    cur_close = df['close'].iloc[idx]
    
    for j in range(start + 2, idx - 1):
        l_j = df['low'].iloc[j]
        if (l_j <= df['low'].iloc[j-1] and 
            l_j <= df['low'].iloc[j-2] and 
            l_j <= df['low'].iloc[j+1] and 
            l_j <= df['low'].iloc[j+2]):
            if abs(cur_low - l_j) / l_j <= 0.02 or (cur_low <= l_j and cur_close >= l_j * 0.985):
                return True, round(l_j, 4)
    return False, None

def check_btc_regime():
    """Checks BTC Daily price vs EMA 50 to assess macro market health"""
    df = fetch_klines_fast("BTCUSDT", interval="1d", limit=100)
    if df is None or len(df) < 55:
        return {"price": 0, "ema50": 0, "is_bull": False, "diff_pct": 0}
    c = df['close']
    ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    cur_p = c.iloc[-1]
    diff = ((cur_p - ema50) / ema50) * 100.0
    return {
        "price": cur_p,
        "ema50": round(ema50, 1),
        "is_bull": cur_p > ema50,
        "diff_pct": round(diff, 2)
    }

def analyze_coin_ichimoku_trio(item):
    """
    Scans a coin for the 3 authorized Ichimoku master strategies:
    1. The Supreme Combo (Strong TK cross above cloud, close to Kijun <= 4%, Chikou free, Future Kumo Green, RSI 48-68)
    2. Kumo Breakout at Support (Cloud breakout with swing/dynamic support confluence)
    3. Kumo Retest & Bounce (Pullback to Kumo Top support and bouncing upwards)
    """
    sym, pair = item
    df = fetch_klines_fast(pair, interval="1d", limit=130)
    if df is None or len(df) < 85:
        return None
        
    df = calc_ichimoku_and_indicators(df)
    n = len(df)
    i = n - 1 # Current / most recent daily candle
    
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    tenkan = df['tenkan'].values
    kijun = df['kijun'].values
    k_top = df['kumo_top'].values
    k_bot = df['kumo_bottom'].values
    fut_a = df['future_span_a'].values
    fut_b = df['future_span_b'].values
    rsi = df['rsi'].values
    vol = df['volume'].values
    vol_ma = df['vol_ma20'].values
    
    if pd.isna(k_top[i]) or pd.isna(kijun[i]) or pd.isna(tenkan[i]):
        return None
        
    cur_p = c[i]
    is_green = c[i] > o[i]
    cur_rsi = rsi[i]
    is_vol_boost = vol[i] >= vol_ma[i] * 1.15 if vol_ma[i] > 0 else False
    
    # TK Cross Check (Today or Yesterday)
    tk_cross_today = (tenkan[i] > kijun[i]) and (tenkan[i-1] <= kijun[i-1])
    tk_cross_yest = (tenkan[i-1] > kijun[i-1]) and (tenkan[i-2] <= kijun[i-2]) and (tenkan[i] > kijun[i])
    has_tk_bullish_cross = tk_cross_today or tk_cross_yest
    
    is_above_cloud = cur_p > k_top[i]
    
    signals = []
    
    # -------------------------------------------------------------------------
    # STRATEGY 1: 🏆 The Supreme Combo (المعادلة الفائقة للإيشيموكو - PF: 6.65)
    # -------------------------------------------------------------------------
    if has_tk_bullish_cross and is_above_cloud:
        # 1. Kijun Rubber-Band check: Price is close to Kijun-sen (distance <= 4.0%)
        kijun_dist_pct = ((cur_p - kijun[i]) / kijun[i]) * 100.0
        is_close_to_kijun = (0.0 <= kijun_dist_pct <= 4.5)
        
        # 2. Chikou Span Bullish: Close today > Close 26 days ago (Unobstructed momentum)
        chikou_bullish = (c[i] > c[i-26]) if i >= 26 else True
        
        # 3. Future Kumo Bullish: Future Span A > Future Span B (Bullish green cloud ahead)
        future_kumo_green = (fut_a[i] > fut_b[i])
        
        # 4. Healthy RSI (48 <= RSI <= 68 - not overbought)
        rsi_healthy = (46.0 <= cur_rsi <= 68.0)
        
        if is_close_to_kijun and chikou_bullish and future_kumo_green and rsi_healthy:
            signals.append({
                'strategy_type': 'SUPREME_COMBO',
                'strategy_name': '🏆 المعادلة الفائقة (The Supreme Combo)',
                'badge': '🏆 النخبة (PF: 6.65)',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'kijun': round(kijun[i], 4),
                'tenkan': round(tenkan[i], 4),
                'kumo_top': round(k_top[i], 4),
                'kijun_dist_pct': round(kijun_dist_pct, 1),
                'rsi': round(cur_rsi, 1),
                'is_vol_boost': is_vol_boost,
                'stop_loss': round(kijun[i] * 0.985, 4), # Daily close below Kijun by 1.5%
                'target_1': round(cur_p * 1.10, 4),      # +10%
                'target_2': round(cur_p * 1.25, 4),      # +25%
                'description': f'تقاطع Tenkan/Kijun صاعد فوق السحابة + قرب السعر من الكيجين ({kijun_dist_pct:.1f}%) + سحابة مستقبلية خضراء + RSI صحي ({cur_rsi:.1f}).'
            })
            
    # -------------------------------------------------------------------------
    # STRATEGY 2: ☁️ Kumo Breakout at Support (اختراق السحابة عند الدعم)
    # -------------------------------------------------------------------------
    # Breakout condition: Price currently above Kumo Top, and broke through within last 1-3 days
    cloud_breakout_recent = is_above_cloud and ((c[i-1] <= k_top[i-1]) or (c[i-2] <= k_top[i-2]))
    if cloud_breakout_recent and (tenkan[i] >= kijun[i]):
        # Check support confluence (Swing low support OR Kijun OR Dynamic EMA50/200)
        has_swing, swing_val = find_swing_support(df, i, lookback=30)
        near_ema50 = abs(l[i] - df['ema50'].iloc[i]) / df['ema50'].iloc[i] <= 0.02
        near_ema200 = abs(l[i] - df['ema200'].iloc[i]) / df['ema200'].iloc[i] <= 0.02
        near_kijun = abs(l[i] - kijun[i]) / kijun[i] <= 0.025
        
        has_support = has_swing or near_ema50 or near_ema200 or near_kijun
        
        if has_support and cur_rsi >= 46.0:
            support_desc = "قاع سابق (Swing Low)" if has_swing else ("دعم Kijun" if near_kijun else "متوسط متحرك EMA")
            signals.append({
                'strategy_type': 'BREAKOUT_SUPPORT',
                'strategy_name': '☁️ اختراق سحابة الإيشيموكو عند الدعم',
                'badge': '☁️ اختراق + دعم',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'kijun': round(kijun[i], 4),
                'kumo_top': round(k_top[i], 4),
                'rsi': round(cur_rsi, 1),
                'is_vol_boost': is_vol_boost,
                'support_level': support_desc,
                'stop_loss': round(k_top[i] * 0.98, 4), # Exit if price falls back below Kumo Top
                'target_1': round(cur_p * 1.08, 4),     # +8%
                'target_2': round(cur_p * 1.18, 4),     # +18%
                'description': f'اختراق حديث لسقف سحابة الإيشيموكو مستنداً على {support_desc} مع زخم RSI ({cur_rsi:.1f}).'
            })
            
    # -------------------------------------------------------------------------
    # STRATEGY 3: 🔄 Kumo Retest & Bounce (إعادة اختبار السحابة والارتداد منها)
    # -------------------------------------------------------------------------
    # Price is in an uptrend above Kumo, pulls back to touch Kumo Top as support, and holds/bounces
    was_comfortably_above = (c[i-2] > k_top[i-2] * 1.02) or (c[i-3] > k_top[i-3] * 1.02)
    touched_kumo_top = (l[i] <= k_top[i] * 1.018) and (c[i] >= k_top[i] * 0.988)
    bouncing = is_green or (c[i] > l[i] + (h[i] - l[i]) * 0.4) # green candle or strong lower wick rejection
    
    if was_comfortably_above and touched_kumo_top and bouncing and cur_p >= k_top[i]:
        signals.append({
            'strategy_type': 'RETEST_BOUNCE',
            'strategy_name': '🔄 إعادة اختبار السحابة والارتداد (Kumo Retest & Bounce)',
            'badge': '🔄 ارتداد من السحابة',
            'symbol': sym,
            'pair': pair,
            'price': cur_p,
            'kijun': round(kijun[i], 4),
            'kumo_top': round(k_top[i], 4),
            'rsi': round(cur_rsi, 1),
            'is_vol_boost': is_vol_boost,
            'stop_loss': round(k_top[i] * 0.978, 4), # Below Kumo Top by 2.2%
            'target_1': round(cur_p * 1.08, 4),      # +8%
            'target_2': round(cur_p * 1.20, 4),      # +20%
            'description': f'السعر صحح واختبر سقف السحابة كدعم ({k_top[i]:.4f}) وشكل شمعة ارتدادية صاعدة تؤكد احترام السحابة.'
        })
        
    return signals

def scan_ichimoku_trio():
    """
    Scans the complete Binance USDT watchlist in parallel for the 3 Ichimoku Master Strategies.
    """
    watchlist = get_watchlist()
    supreme_list = []
    breakout_list = []
    retest_list = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(analyze_coin_ichimoku_trio, item) for item in watchlist]
        for f in concurrent.futures.as_completed(futures):
            sigs = f.result()
            if sigs:
                for s in sigs:
                    if s['strategy_type'] == 'SUPREME_COMBO':
                        supreme_list.append(s)
                    elif s['strategy_type'] == 'BREAKOUT_SUPPORT':
                        breakout_list.append(s)
                    elif s['strategy_type'] == 'RETEST_BOUNCE':
                        retest_list.append(s)
                        
    # Sort by strength (RSI and volume boost)
    supreme_list.sort(key=lambda x: (x['is_vol_boost'], -abs(x['kijun_dist_pct'])), reverse=True)
    breakout_list.sort(key=lambda x: (x['is_vol_boost'], x['rsi']), reverse=True)
    retest_list.sort(key=lambda x: (x['is_vol_boost'], x['rsi']), reverse=True)
    
    return {
        'supreme': supreme_list,
        'breakout': breakout_list,
        'retest': retest_list,
        'total_scanned': len(watchlist)
    }

def format_ichimoku_trio_report(scan_res):
    """
    Formats the 3-Strategy Ichimoku Master Digest for Telegram into beautiful, clean messages.
    """
    btc = check_btc_regime()
    btc_status = "🟢 صاعد فوق Daily EMA50" if btc.get('is_bull') else "🔴 تصحيحي أسفل Daily EMA50"
    
    supreme = scan_res.get('supreme', [])
    breakout = scan_res.get('breakout', [])
    retest = scan_res.get('retest', [])
    
    messages = []
    
    # Header Message
    header = (
        f"⚡ <b>رادار الإيشيموكو الذهبي الثلاثي (Ichimoku Master Radar)</b>\n"
        f"────────────────────\n"
        f"• <b>سعر البيتكوين:</b> <code>{btc.get('price', 0):,.1f} $</code> ({btc_status})\n"
        f"• <b>الاستراتيجيات المفحوصة:</b> الثلاثية المعتمدة فقط (فريم Daily 1D)\n"
        f"• <b>عدد العملات المفحوصة:</b> {scan_res.get('total_scanned', 301)} عملة\n"
        f"────────────────────\n"
        f"📊 <b>ملخص الإشارات المرصودة حالياً:</b>\n"
        f"• 🏆 <b>المعادلة الفائقة (Supreme Combo - PF 6.65):</b> {len(supreme)} عملة\n"
        f"• ☁️ <b>اختراق السحابة عند الدعم (Breakout):</b> {len(breakout)} عملة\n"
        f"• 🔄 <b>إعادة اختبار السحابة والارتداد (Retest):</b> {len(retest)} عملة\n"
        f"────────────────────"
    )
    messages.append(header)
    
    # 1. SECTION 1: SUPREME COMBO
    if supreme:
        lines = [
            f"🏆 <b>1. إشارات المعادلة الفائقة (The Supreme Combo):</b>\n"
            f"<i>(تقاطع Tenkan/Kijun صاعد فوق السحابة + قرب الكيجين &lt;= 4% + سحابة خضراء - معيار ربح 6.65)</i>\n"
        ]
        for s in supreme[:6]:
            vol_icon = "🔥 فوليوم عالي" if s['is_vol_boost'] else "معتدل"
            lines.append(
                f"🌟 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | Kijun: <code>{s['kijun']} $</code> (فارق: +{s['kijun_dist_pct']}%)\n"
                f"• مؤشر RSI: <code>{s['rsi']}</code> | السيولة: {vol_icon}\n"
                f"• 🛑 <b>وقف الخسارة (SL):</b> إغلاق يومي أسفل <code>{s['stop_loss']} $</code>\n"
                f"• 🎯 <b>الهدف 1:</b> <code>{s['target_1']} $</code> (+10%)\n"
                f"• 🚀 <b>الهدف 2 / ركوب الموجه:</b> تتبع خط الكيجين سن أو <code>{s['target_2']} $</code> (+25%)\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))
    else:
        messages.append("🏆 <b>1. المعادلة الفائقة (The Supreme Combo):</b>\nلا توجد إشارات مكتملة الشروط الـ 5 حالياً (المعادلة نادرة وصارمة لحماية رأس المال).")
        
    # 2. SECTION 2: BREAKOUT AT SUPPORT
    if breakout:
        lines = [
            f"☁️ <b>2. إشارات اختراق سحابة الإيشيموكو عند الدعم:</b>\n"
            f"<i>(اختراق صاعد لسقف السحابة مستنداً على منطقة دعم قوية)</i>\n"
        ]
        for s in breakout[:6]:
            lines.append(
                f"🚀 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | سقف السحابة: <code>{s['kumo_top']} $</code>\n"
                f"• الدعم المستند عليه: <b>{s['support_level']}</b> | RSI: <code>{s['rsi']}</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق أسفل <code>{s['stop_loss']} $</code>\n"
                f"• 🎯 <b>الأهداف:</b> <code>{s['target_1']} $</code> (+8%) ── <code>{s['target_2']} $</code> (+18%)\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))
        
    # 3. SECTION 3: RETEST & BOUNCE
    if retest:
        lines = [
            f"🔄 <b>3. إشارات إعادة اختبار السحابة والارتداد (Kumo Retest & Bounce):</b>\n"
            f"<i>(السعر صحح وملس سقف السحابة وبدأ بالارتداد للصعود مجدداً)</i>\n"
        ]
        for s in retest[:6]:
            lines.append(
                f"💎 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر الحالي: <code>{s['price']} $</code> | سقف السحابة المرتد منه: <code>{s['kumo_top']} $</code>\n"
                f"• مؤشر RSI: <code>{s['rsi']}</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{s['stop_loss']} $</code>\n"
                f"• 🎯 <b>الأهداف:</b> <code>{s['target_1']} $</code> (+8%) ── <code>{s['target_2']} $</code> (+20%)\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))
        
    # Instructions Footer
    footer = (
        "💡 <b>قواعد تداول الإيشيموكو الذهبية:</b>\n"
        "1. نظام الإيشيموكو صُمم لركوب الاتجاهات الكبرى (Trend Following)، لا تخرج بأهداف سريعة ضيقة.\n"
        "2. ارفع وقف خسارتك يومياً مع صعود خط <b>الكيجين سن (Kijun-sen)</b> لضمان أقصى ربحية ممكنة.\n"
        "3. أرسل <b>سحابة</b> أو <code>/scan</code> في أي وقت لإعادة الفحص المحدث."
    )
    messages.append(footer)
    
    return messages
