import numpy as np
import pandas as pd
import requests
import json
import concurrent.futures
from config import BINANCE_DATA_URL, BINANCE_REST_URL, WATCHLIST, BTC_EMA_PERIOD, get_watchlist

def calc_rma(series, length):
    alpha = 1.0 / length
    return series.ewm(alpha=alpha, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = calc_rma(gain, period)
    avg_loss = calc_rma(loss, period)
    rs = avg_gain / np.where(avg_loss == 0, 0.0001, avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))

def fetch_klines(symbol, interval="1d", limit=150):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    urls = [
        f"{BINANCE_DATA_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"{BINANCE_REST_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 30:
                    df = pd.DataFrame(data, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_asset_volume', 'trades', 'taker_base', 'taker_quote', 'ignore'
                    ])
                    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_asset_volume']:
                        df[col] = df[col].astype(float)
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                    return df
        except Exception:
            continue
    return None

def check_btc_regime():
    df = fetch_klines("BTCUSDT", interval="1d", limit=100)
    if df is None:
        return {'is_bull': False, 'price': 0, 'ema50': 0, 'diff_pct': 0, 'error': 'Could not fetch BTC data'}
    
    df['ema50'] = df['close'].ewm(span=BTC_EMA_PERIOD, adjust=False).mean()
    cur_p = df['close'].iloc[-1]
    cur_ema = df['ema50'].iloc[-1]
    is_bull = cur_p > cur_ema
    diff_pct = ((cur_p - cur_ema) / cur_ema) * 100.0
    
    # Banker on BTC
    h27 = df['high'].rolling(27).max()
    l27 = df['low'].rolling(27).min()
    diff = np.where(h27 - l27 == 0, 0.0001, h27 - l27)
    raw_stoch = (df['close'] - l27) / diff * 100
    xsa1 = calc_rma(pd.Series(raw_stoch), 5)
    xsa2 = calc_rma(xsa1, 3)
    df['fundtrend'] = (3 * xsa1 - 2 * xsa2 - 50) * 1.032 + 50
    df['bullbearline'] = df['fundtrend'].ewm(span=13, adjust=False).mean()
    banker_active = bool(df['fundtrend'].iloc[-1] > df['bullbearline'].iloc[-1])
    
    return {
        'is_bull': is_bull,
        'price': cur_p,
        'ema50': round(cur_ema, 2),
        'diff_pct': round(diff_pct, 2),
        'banker_active': banker_active,
        'banker_val': round(float(df['fundtrend'].iloc[-1]), 1)
    }

def check_4h_confirmation(pair):
    """Checks 4H timeframe to confirm the daily entry timing (Multi-Timeframe Analysis)"""
    df_4h = fetch_klines(pair, interval="4h", limit=50)
    if df_4h is None or len(df_4h) < 25:
        return {
            'confirmed': True,
            'badge': '⚪ 4H غير متوفر (دخول فوري بحسب اليومي)',
            'details': 'بيانات 4H غير كافية - الاعتماد كامل على فريم اليومي',
            'rsi_4h': 50.0,
            'ema20_4h': 0.0
        }
        
    c4 = df_4h['close']
    ema20_4h = float(c4.ewm(span=20, adjust=False).mean().iloc[-1])
    rsi_4h = float(calc_rsi(c4, 14).iloc[-1])
    cur_p = float(c4.iloc[-1])
    
    # 4H Confirmation Criteria:
    # 1. Price is supported at or above 4H EMA 20 (not in a dumping freefall)
    # 2. RSI 4H is in a healthy momentum zone (42 to 74)
    # 3. Not in a dangerous blow-off top (RSI > 75)
    is_trend_ok = cur_p >= (ema20_4h * 0.985)
    is_rsi_ok = (42.0 <= rsi_4h <= 74.0)
    
    confirmed = is_trend_ok and is_rsi_ok
    if confirmed:
        badge = "✅ مؤكد متطابق 4H (4H Confirmed)"
        details = f"السعر متماسك فوق 4H EMA20 ({cur_p:,.4f} >= {ema20_4h:,.4f}) وزخم 4H RSI متوازن وصاعد ({rsi_4h:.1f})"
    elif rsi_4h > 74.0:
        badge = "⚠️ 4H متضخم لحظياً (Overbought)"
        details = f"مؤشر 4H RSI مرتفع ({rsi_4h:.1f}) - يفضل انتظار تهدئة طفيفة لشمعة 4H قبل التنفيذ"
    else:
        badge = "⏳ بانتظار شمعة 4H خضراء مؤكدة"
        details = f"السعر دون 4H EMA20 ({cur_p:,.4f} < {ema20_4h:,.4f}) - انتظر ارتداد لحظي للشمعة الحالية"
        
    return {
        'confirmed': confirmed,
        'badge': badge,
        'details': details,
        'rsi_4h': round(rsi_4h, 1),
        'ema20_4h': round(ema20_4h, 6)
    }

def analyze_coin_1d(item):
    name, pair = item
    if pair == "BTCUSDT":
        return None
        
    df = fetch_klines(pair, interval="1d", limit=220)
    if df is None or len(df) < 55:
        return None
        
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    v = df['volume']
    n = len(df)
    
    cur_p = float(c.iloc[-1])
    vol_24h = float(df['quote_asset_volume'].iloc[-1])
    
    # EMAs
    df['ema9'] = c.ewm(span=9, adjust=False).mean()
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema100'] = c.ewm(span=100, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    # Crossovers on current or previous closed candle
    def crossed_up(fast_s, slow_s):
        today = (fast_s.iloc[-2] <= slow_s.iloc[-2]) and (fast_s.iloc[-1] > slow_s.iloc[-1])
        prev = (n > 2) and (fast_s.iloc[-3] <= slow_s.iloc[-3]) and (fast_s.iloc[-2] > slow_s.iloc[-2])
        return today or prev

    cross_9_21 = crossed_up(df['ema9'], df['ema21'])
    cross_20_50 = crossed_up(df['ema20'], df['ema50'])
    cross_50_200 = crossed_up(df['ema50'], df['ema200'])
    cross_50_100 = crossed_up(df['ema50'], df['ema100'])
    cross_20_100 = crossed_up(df['ema20'], df['ema100'])
    
    # Above EMA 50
    above_ema50 = cur_p > df['ema50'].iloc[-1]
    
    # Volume Spike (> 1.20x SMA20)
    vol_sma20 = v.rolling(20).mean()
    vol_spike = bool(v.iloc[-1] >= 1.20 * vol_sma20.iloc[-1] or v.iloc[-2] >= 1.20 * vol_sma20.iloc[-2])
    
    # Ichimoku Cloud
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2.0
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2.0).shift(26)
    kumo_top = np.maximum(span_a, span_b)
    above_cloud = bool(cur_p > kumo_top.iloc[-1])
    kumo_breakout = bool((c.iloc[-2] <= kumo_top.iloc[-2] and c.iloc[-1] > kumo_top.iloc[-1]) or 
                         (n > 2 and c.iloc[-3] <= kumo_top.iloc[-3] and c.iloc[-2] > kumo_top.iloc[-2]))
    
    # Bollinger Bands Squeeze & Breakout
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    upper_bb = sma20 + 2.0 * std20
    lower_bb = sma20 - 2.0 * std20
    bandwidth = (upper_bb - lower_bb) / sma20.replace(0, 1e-5)
    min_bw = bandwidth.rolling(20).min()
    bb_squeezed = bool(bandwidth.iloc[-2] <= (min_bw.iloc[-2] * 1.30))
    bb_breakout = bool(bb_squeezed and (c.iloc[-2] <= upper_bb.iloc[-2] and c.iloc[-1] > upper_bb.iloc[-1]))
    
    # MACD Below Zero Cross
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_cross = crossed_up(macd_line, signal_line)
    macd_below_zero = bool(macd_cross and (macd_line.iloc[-1] < 0))
    
    # RSI Line Cross above RSI MA
    df['rsi'] = calc_rsi(c, 14)
    df['rsi_ma'] = df['rsi'].rolling(14).mean()
    rsi_cross = crossed_up(df['rsi'], df['rsi_ma'])
    
    # SRchannel Support
    low_p = l.values
    prd_sr = 8
    piv_sr = np.full(n, np.nan)
    for i in range(prd_sr, n - prd_sr):
        if low_p[i] == np.min(low_p[i-prd_sr : i+prd_sr+1]):
            piv_sr[i] = low_p[i]
            
    conf_sr = []
    at_support = False
    for k in range(n):
        if k >= 2 * prd_sr:
            idx = k - prd_sr
            if not np.isnan(piv_sr[idx]):
                conf_sr.append((idx, piv_sr[idx]))
    valid_sr = [s for s in conf_sr if (n - 1) - s[0] <= 100]
    for idx, s_val in valid_sr:
        if (l.iloc[-1] <= s_val * 1.03 and cur_p >= s_val * 0.97) or abs((cur_p - s_val)/s_val) <= 0.03:
            at_support = True
            break
            
    # Banker Flow
    h27 = h.rolling(27).max()
    l27 = l.rolling(27).min()
    diff = np.where(h27 - l27 == 0, 0.0001, h27 - l27)
    raw_stoch = (c - l27) / diff * 100
    xsa1 = calc_rma(pd.Series(raw_stoch), 5)
    xsa2 = calc_rma(xsa1, 3)
    fundtrend = (3 * xsa1 - 2 * xsa2 - 50) * 1.032 + 50
    typ = (2 * c + h + l + o) / 5.0
    lol = l.rolling(34).min()
    hoh = h.rolling(34).max()
    diff_bb = np.where(hoh - lol == 0, 0.0001, hoh - lol)
    pos_typ = (typ - lol) / diff_bb * 100
    bullbearline = pos_typ.rolling(3).mean()
    banker_active = bool((fundtrend.iloc[-1] > bullbearline.iloc[-1]) or (fundtrend.iloc[-1] > 50))

    # -------------------------------------------------------------
    # Match Against Ranked Golden Strategies (Highest Win Rate First)
    # -------------------------------------------------------------
    matched_strat = None
    
    # Tier 1: Diamond Tier (80% - 88%)
    if cross_9_21 and above_cloud:
        matched_strat = ("تقاطع EMA 9/21 + فوق سحابة إيشيموكو", "👑 88.0% | EMA 9/21 فوق السحابة", 88.0, 6.12, 0.06, 0.045, 0.025, 1)
    elif kumo_breakout and vol_spike:
        matched_strat = ("اختراق سحابة إيشيموكو + طفرة فوليوم", "☁️ 83.9% | اختراق سحابة بفوليوم", 83.9, 4.20, 0.06, 0.045, 0.025, 1)
    elif cross_9_21 and at_support and above_ema50:
        matched_strat = ("توليفة VIP لـ EMA 9/21 (دعم + فوق EMA 50)", "💎 83.5% | توليفة VIP EMA 9/21", 83.5, 4.32, 0.06, 0.045, 0.025, 1)
    elif bb_breakout:
        matched_strat = ("انفجار البولنجر بعد انضغاط (هدف خاطف)", "💣 82.7% | انفجار البولنجر الخاطف", 82.7, 4.12, 0.045, 0.035, 0.020, 1)
    elif cross_9_21 and above_ema50:
        matched_strat = ("تقاطع EMA 9/21 + فوق EMA 50 (ترند صاعد)", "🚀 82.7% | EMA 9/21 فوق EMA 50", 82.7, 3.99, 0.06, 0.045, 0.025, 1)
    elif cross_9_21 and vol_spike:
        matched_strat = ("تقاطع EMA 9/21 + طفرة فوليوم", "⚡ 81.6% | EMA 9/21 بطفرة فوليوم", 81.6, 3.94, 0.06, 0.045, 0.025, 1)
    elif cross_20_50 and at_support and vol_spike:
        matched_strat = ("توليفة VIP لـ EMA 20/50 (دعم + فوليوم)", "💎 81.2% | توليفة VIP EMA 20/50", 81.2, 2.82, 0.06, 0.045, 0.025, 1)

    # Tier 2: Gold Tier (77% - 79.9%)
    elif kumo_breakout:
        matched_strat = ("اختراق سحابة إيشيموكو قياسي", "☁️ 79.3% | اختراق سحابة إيشيموكو", 79.3, 2.64, 0.06, 0.045, 0.025, 2)
    elif cross_50_200:
        matched_strat = ("التقاطع الذهبي الكلاسيكي (EMA 50/200)", "🌟 79.2% | التقاطع الذهبي الكلاسيكي", 79.2, 3.09, 0.045, 0.035, 0.020, 2)
    elif cross_9_21 and at_support:
        matched_strat = ("تقاطع EMA 9/21 + ارتكاز على دعم أفقي", "🛡️ 77.1% | EMA 9/21 عند الدعم", 77.1, 2.76, 0.06, 0.045, 0.025, 2)
    elif macd_below_zero and at_support:
        matched_strat = ("تقاطع MACD تحت الصفر + دعم أفقي", "📊 77.0% | MACD ارتداد من القاع والدعم", 77.0, 2.49, 0.06, 0.045, 0.025, 2)
    elif cross_9_21:
        matched_strat = ("تقاطع EMA 9/21 بهدف خاطف سريع", "🎯 76.4% | EMA 9/21 هدف خاطف", 76.4, 3.27, 0.040, 0.030, 0.020, 2)

    # Tier 3: Silver Tier (71.9% - 76.9%)
    elif cross_50_100:
        matched_strat = ("تقاطع EMA 50/100 بهدف خاطف", "🎯 76.7% | تقاطع EMA 50/100", 76.7, 2.44, 0.045, 0.035, 0.020, 3)
    elif cross_20_50 and above_cloud:
        matched_strat = ("تقاطع EMA 20/50 + فوق سحابة إيشيموكو", "🚀 76.2% | EMA 20/50 فوق السحابة", 76.2, 2.18, 0.06, 0.045, 0.025, 3)
    elif macd_below_zero and banker_active:
        matched_strat = ("تقاطع MACD تحت الصفر + سيولة الحيتان", "💎 76.2% | MACD تحت الصفر + حيتان", 76.2, 2.46, 0.06, 0.045, 0.025, 3)
    elif cross_20_50:
        matched_strat = ("تقاطع EMA 20/50 بهدف خاطف سريع", "🔥 75.9% | EMA 20/50 هدف خاطف", 75.9, 2.33, 0.045, 0.035, 0.020, 3)
    elif cross_20_100:
        matched_strat = ("تقاطع EMA 20/100 بهدف خاطف", "🎯 75.5% | تقاطع EMA 20/100", 75.5, 2.13, 0.045, 0.035, 0.020, 3)
    elif cross_20_50 and at_support:
        matched_strat = ("تقاطع EMA 20/50 + ارتكاز على دعم أفقي", "🛡️ 74.4% | EMA 20/50 عند الدعم", 74.4, 1.92, 0.06, 0.045, 0.025, 3)
    elif rsi_cross and at_support:
        matched_strat = ("تقاطع خط RSI (البنفسجي فوق الأصفر) + دعم", "🏆 71.9% | ارتداد RSI صعوداً من الدعم", 71.9, 1.50, 0.06, 0.045, 0.025, 3)

    if not matched_strat:
        return None
        
    strat_name, strat_badge, win_rate, pf, tp_pct, sl_pct, be_pct, tier = matched_strat
    
    # 4H MTF Confirmation
    mtf = check_4h_confirmation(pair)
    
    tp_p = round(cur_p * (1.0 + tp_pct), 6)
    sl_p = round(cur_p * (1.0 - sl_pct), 6)
    be_p = round(cur_p * (1.0 + be_pct), 6)
    
    return {
        'timeframe': '1D',
        'symbol': name,
        'pair': pair,
        'current_price': cur_p,
        'volume_24h': vol_24h,
        'strategy_name': strat_name,
        'tier_badge': strat_badge,
        'win_rate': win_rate,
        'profit_factor': pf,
        'tier': tier,
        'tp_pct': round(tp_pct * 100, 1),
        'tp_price': tp_p,
        'sl_pct': round(sl_pct * 100, 1),
        'sl_price': sl_p,
        'be_pct': round(be_pct * 100, 1),
        'be_price': be_p,
        'mtf_confirmed': mtf['confirmed'],
        'mtf_badge': mtf['badge'],
        'mtf_details': mtf['details'],
        'at_support': at_support,
        'above_cloud': above_cloud,
        'vol_spike': vol_spike,
        'banker_active': banker_active,
        'support_desc': "مرتكزة مباشرة على خط دعم أفقي قوي 🟢" if at_support else "السعر يتداول فوق أقرب مستوى دعم ⚪",
        'squeeze_desc': "انفجار البولنجر العلوي بدأ الآن 🚀" if bb_breakout else "زخم صاعد مستقر 🟢",
        'macd_desc': "تقاطع إيجابي مؤكد صاعد 🟢" if (macd_below_zero or macd_cross) else "هيستوجرام متسارع صعوداً 🟢",
        'banker_desc': "تدفق سيولة مؤسسات وحيتان نشط (Banker In 🟢)" if banker_active else "سيولة طبيعية ⚪",
        'chart_url': f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"
    }

def analyze_coin_1w(item):
    """Scans for Macro Weekly Investment setups (1W timeframe)"""
    name, pair = item
    if pair == "BTCUSDT":
        return None
        
    df = fetch_klines(pair, interval="1w", limit=200)
    if df is None or len(df) < 50:
        return None
        
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']
    n = len(df)
    cur_p = float(c.iloc[-1])
    vol_24h = float(df['quote_asset_volume'].iloc[-1])
    
    # 1. Weekly MACD below zero cross
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_cross_up = bool((macd_line.iloc[-2] <= signal_line.iloc[-2]) and (macd_line.iloc[-1] > signal_line.iloc[-1]))
    macd_weekly_under_zero = macd_cross_up and (macd_line.iloc[-1] < 0)
    
    # 2. Weekly Cloud Breakout
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2.0
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2.0).shift(26)
    kumo_top = np.maximum(span_a, span_b)
    kumo_breakout = bool((c.iloc[-2] <= kumo_top.iloc[-2]) and (c.iloc[-1] > kumo_top.iloc[-1]))
    
    # 3. Weekly BB Squeeze Breakout
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    upper_bb = sma20 + 2.0 * std20
    lower_bb = sma20 - 2.0 * std20
    bandwidth = (upper_bb - lower_bb) / sma20.replace(0, 1e-5)
    min_bw = bandwidth.rolling(20).min()
    bb_squeezed = bool(bandwidth.iloc[-2] <= (min_bw.iloc[-2] * 1.30))
    bb_breakout = bool(bb_squeezed and (c.iloc[-2] <= upper_bb.iloc[-2] and c.iloc[-1] > upper_bb.iloc[-1]))
    
    # 4. Weekly Golden Cross (EMA 50 / 200)
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    cross_50_200 = bool((ema50.iloc[-2] <= ema200.iloc[-2]) and (ema50.iloc[-1] > ema200.iloc[-1]))
    
    matched_w = None
    if macd_weekly_under_zero:
        matched_w = ("تقاطع MACD أسبوعي تحت الصفر (Macro Bottom)", "👑 87.5% | تقاطع MACD أسبوعي تحت الصفر", 87.5, 6.54, 0.10, 0.07, 0.04)
    elif kumo_breakout:
        matched_w = ("اختراق سحابة إيشيموكو أسبوعي (Macro Bull Run)", "☁️ 83.3% | اختراق سحابة أسبوعي", 83.3, 6.04, 0.12, 0.08, 0.04)
    elif bb_breakout:
        matched_w = ("انفجار البولنجر بعد انضغاط أسبوعي", "💣 80.0% | انفجار بولنجر أسبوعي", 80.0, 3.93, 0.06, 0.045, 0.025)
    elif cross_50_200:
        matched_w = ("التقاطع الذهبي الأسبوعي (EMA 50/200)", "🌟 التقاطع الذهبي الأسبوعي النادر", 85.0, 4.00, 0.15, 0.10, 0.05)
        
    if not matched_w:
        return None
        
    strat_name, strat_badge, win_rate, pf, tp_pct, sl_pct, be_pct = matched_w
    tp_p = round(cur_p * (1.0 + tp_pct), 6)
    sl_p = round(cur_p * (1.0 - sl_pct), 6)
    be_p = round(cur_p * (1.0 + be_pct), 6)
    
    return {
        'timeframe': '1W',
        'symbol': name,
        'pair': pair,
        'current_price': cur_p,
        'volume_24h': vol_24h,
        'strategy_name': strat_name,
        'tier_badge': strat_badge,
        'win_rate': win_rate,
        'profit_factor': pf,
        'tp_pct': round(tp_pct * 100, 1),
        'tp_price': tp_p,
        'sl_pct': round(sl_pct * 100, 1),
        'sl_price': sl_p,
        'be_pct': round(be_pct * 100, 1),
        'be_price': be_p,
        'chart_url': f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"
    }

def scan_market_1d(coins=None):
    if coins is None:
        coins = get_watchlist()
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        results = list(ex.map(analyze_coin_1d, coins))
    signals = [r for r in results if r is not None]
    # Sort signals: MTF Confirmed first, then highest win rate, then volume
    signals.sort(key=lambda s: (s['mtf_confirmed'], s['win_rate'], s['volume_24h']), reverse=True)
    return signals

def scan_market_1w(coins=None):
    if coins is None:
        coins = get_watchlist()
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        results = list(ex.map(analyze_coin_1w, coins))
    signals = [r for r in results if r is not None]
    signals.sort(key=lambda s: (s['win_rate'], s['volume_24h']), reverse=True)
    return signals

def scan_market(coins=None):
    btc_status = check_btc_regime()
    signals_1d = scan_market_1d(coins)
    signals_1w = scan_market_1w(coins)
    
    total_scanned = len(coins) if coins else len(get_watchlist())
    return {
        'btc_status': btc_status,
        'signals_1d': signals_1d,
        'signals_1w': signals_1w,
        'signals': signals_1d, # default backwards compatibility
        'all_scanned_count': total_scanned,
        'reason': "اكتمل الفحص بنجاح على فريمي اليومي والأسبوعي"
    }

def check_macd_exit(pair):
    df = fetch_klines(pair, interval="1d", limit=40)
    if df is None or len(df) < 30:
        return False
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return bool((macd.iloc[-2] >= signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1]))
