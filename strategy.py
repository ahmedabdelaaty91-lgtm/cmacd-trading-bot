import numpy as np
import pandas as pd
import requests
import json
import concurrent.futures
from config import BINANCE_DATA_URL, BINANCE_REST_URL, WATCHLIST, BTC_EMA_PERIOD, INITIAL_SL_PCT, TP1_PCT, TP2_PCT, get_watchlist

def calc_rma(series, length):
    alpha = 1.0 / length
    return series.ewm(alpha=alpha, adjust=False).mean()

def fetch_klines(symbol, interval="1d", limit=120):
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
                if len(data) >= 40:
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
    
    # Also check Banker on BTC
    h27 = df['high'].rolling(27).max()
    l27 = df['low'].rolling(27).min()
    diff = h27 - l27
    diff = np.where(diff == 0, 0.0001, diff)
    raw_stoch = (df['close'] - l27) / diff * 100
    xsa1 = calc_rma(pd.Series(raw_stoch), 5)
    xsa2 = calc_rma(xsa1, 3)
    df['fundtrend'] = (3 * xsa1 - 2 * xsa2 - 50) * 1.032 + 50
    df['bullbearline'] = df['fundtrend'].ewm(span=13, adjust=False).mean()
    banker_active = df['fundtrend'].iloc[-1] > df['bullbearline'].iloc[-1]
    
    return {
        'is_bull': is_bull,
        'price': cur_p,
        'ema50': round(cur_ema, 2),
        'diff_pct': round(diff_pct, 2),
        'banker_active': banker_active,
        'banker_val': round(df['fundtrend'].iloc[-1], 1)
    }

def check_macd_exit(pair):
    """Checks if daily CM MACD crossed down on the latest closed candle"""
    df = fetch_klines(pair, interval="1d", limit=40)
    if df is None or len(df) < 30:
        return False
        
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    
    macd_cross_down = (macd.iloc[-2] >= signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])
    return bool(macd_cross_down)

def analyze_coin(item):
    name, pair = item
    if pair == "BTCUSDT":
        return None
        
    df = fetch_klines(pair, interval="1d", limit=120)
    if df is None or len(df) < 40:
        return None
        
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    close_p = df['close'].values
    vol_p = df['volume'].values
    n = len(df)
    
    cur_p = float(close_p[-1])
    cur_low = float(low_p[-1])
    cur_high = float(high_p[-1])
    cur_vol = float(vol_p[-1])
    
    # 24H Volume in USDT
    quote_vol_24h = float(df['quote_asset_volume'].iloc[-1])
    vol_sma20 = float(df['volume'].rolling(20).mean().iloc[-1])
    vol_ratio = (cur_vol / vol_sma20) if vol_sma20 > 0 else 1.0
    vol_spike = vol_ratio >= 1.20
    
    # 1. SR Channel Support (Pivot Lows, prd=8, lookback=100)
    prd = 8
    df['pivot_low'] = np.nan
    for i in range(prd, n - prd):
        if low_p[i] == np.min(low_p[i - prd : i + prd + 1]):
            df.loc[df.index[i], 'pivot_low'] = low_p[i]
            
    confirmed_supports = []
    for k in range(n):
        if k >= 2 * prd:
            cand_idx = k - prd
            if not np.isnan(df['pivot_low'].iloc[cand_idx]):
                confirmed_supports.append((cand_idx, df['pivot_low'].iloc[cand_idx]))
                
    valid_supports = [s for s in confirmed_supports if (n - 1) - s[0] <= 100]
    
    at_support = False
    sup_level = None
    dist_pct = 0.0
    support_desc = "بعيد عن الدعوم الرئيسية"
    
    for idx, s_val in valid_supports:
        dist = ((cur_p - s_val) / s_val) * 100.0
        # If price touches or is within 3.5% above confirmed daily support
        if (cur_low <= s_val * 1.035 and cur_p >= s_val * 0.965) or abs(dist) <= 3.5:
            at_support = True
            sup_level = float(s_val)
            dist_pct = dist
            support_desc = f"يرتكز على دعم يومي رئيسي مؤكد عند <code>{sup_level:,.4f} $</code> (يبعد عنه <code>{dist_pct:+.2f}%</code>)"
            break
            
    # 2. MSL Squeeze (Momentum Squeeze)
    basis = df['close'].rolling(20).mean()
    dev = 2.0 * df['close'].rolling(20).std()
    upper_bb = basis + dev
    lower_bb = basis - dev
    
    tr = pd.concat([df['high'] - df['low'], np.abs(df['high'] - df['close'].shift(1)), np.abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()
    upper_kc = basis + 1.5 * atr20
    lower_kc = basis - 1.5 * atr20
    
    in_squeeze = (lower_bb > lower_kc) & (upper_bb < upper_kc)
    squeeze_fired = ((in_squeeze.shift(1) == True) & (in_squeeze == False)) | ((in_squeeze.shift(2) == True) & (in_squeeze.shift(1) == False))
    recent_squeeze = in_squeeze | in_squeeze.shift(1) | in_squeeze.shift(2) | in_squeeze.shift(3)
    
    hl_avg = (df['high'].rolling(20).max() + df['low'].rolling(20).min()) / 2.0
    val = df['close'] - (hl_avg + basis) / 2.0
    mom = val.rolling(12).mean()
    mom_bullish = bool((mom.iloc[-1] > mom.iloc[-2]) or (mom.iloc[-1] > 0))
    
    is_sq_now = bool(in_squeeze.iloc[-1])
    is_sq_fired = bool(squeeze_fired.iloc[-1] or (n > 2 and squeeze_fired.iloc[-2]))
    is_sq_energy = bool(recent_squeeze.iloc[-1])
    
    has_squeeze_condition = (is_sq_fired or is_sq_energy or is_sq_now) and mom_bullish
    
    if is_sq_fired:
        squeeze_status_text = "🚀 <b>انفجار الزخم بدأ الآن (Squeeze Fired):</b> تحرر طاقة التجميع وانطلاق السيولة الانفجارية."
        squeeze_badge = "FIRED 🚀"
    elif is_sq_now:
        squeeze_status_text = "⚡ <b>انضغاط وتجميع طاقة شديد (Squeeze ON):</b> البولينجر داخل الكلتنر (انفجار وشيك)."
        squeeze_badge = "ON ⚡"
    elif is_sq_energy:
        squeeze_status_text = "⚡ <b>طاقة تجميع حديثة (Recent Energy):</b> زخم إيجابي صاعد متسارع."
        squeeze_badge = "ENERGY ⚡"
    else:
        squeeze_status_text = "⚪ <b>لا يوجد انضغاط حالياً:</b> الزخم اعتيادي."
        squeeze_badge = "NONE ⚪"
        
    # 3. CM Ult MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    macd_cross_today = bool((df['macd'].iloc[-2] <= df['signal'].iloc[-2]) and (df['macd'].iloc[-1] > df['signal'].iloc[-1]))
    macd_cross_prev = bool((df['macd'].iloc[-3] <= df['signal'].iloc[-3]) and (df['macd'].iloc[-2] > df['signal'].iloc[-2]))
    macd_recent_cross = macd_cross_today or macd_cross_prev
    macd_hist_expanding = bool((df['hist'].iloc[-1] > 0) and (df['hist'].iloc[-1] >= df['hist'].iloc[-2]))
    macd_ok = macd_recent_cross or macd_hist_expanding
    
    if macd_cross_today:
        macd_status_text = "🟢 <b>تقاطع إيجابي مؤكد اليوم (Fresh Bullish Cross):</b> خط الماكد قطع خط الإشارة لأعلى."
    elif macd_cross_prev:
        macd_status_text = "🟢 <b>تقاطع إيجابي حديث (منذ شمعة سابقة):</b> الماكد مستقر فوق الإشارة."
    elif macd_hist_expanding:
        macd_status_text = "🟢 <b>هيستوجرام إيجابي متسارع:</b> أعمدة خضراء تتسع وتتصاعد فوق خط الصفر."
    else:
        macd_status_text = "⚪ <b>لا يوجد تقاطع إيجابي صريح اليوم.</b>"
        
    # 4. L3 Banker Fund Flow
    h27 = df['high'].rolling(27).max()
    l27 = df['low'].rolling(27).min()
    diff_stoch = h27 - l27
    diff_stoch = np.where(diff_stoch == 0, 0.0001, diff_stoch)
    raw_stoch = (df['close'] - l27) / diff_stoch * 100
    xsa1 = calc_rma(pd.Series(raw_stoch), 5)
    xsa2 = calc_rma(xsa1, 3)
    df['fundtrend'] = (3 * xsa1 - 2 * xsa2 - 50) * 1.032 + 50
    
    typ = (2 * df['close'] + df['high'] + df['low'] + df['open']) / 5.0
    lol = df['low'].rolling(34).min()
    hoh = df['high'].rolling(34).max()
    diff_bb = np.where(hoh - lol == 0, 0.0001, hoh - lol)
    pos_typ = (typ - lol) / diff_bb * 100
    df['bullbearline'] = pos_typ.rolling(3).mean()
    
    cur_ft = float(df['fundtrend'].iloc[-1])
    prev_ft = float(df['fundtrend'].iloc[-2])
    cur_bbl = float(df['bullbearline'].iloc[-1])
    prev_bbl = float(df['bullbearline'].iloc[-2])
    
    is_long_active = cur_ft > cur_bbl
    cross_banker_in = (prev_ft <= prev_bbl) and (cur_ft > cur_bbl)
    cross_banker_recent = cross_banker_in or ((df['fundtrend'].iloc[-3] <= df['bullbearline'].iloc[-3]) and (prev_ft > prev_bbl))
    is_osr = (prev_ft <= 20) and (cur_ft > prev_ft)
    
    banker_ok = is_long_active or cross_banker_recent or is_osr
    
    # Banker Badges
    banker_badges = []
    if cross_banker_in or cross_banker_recent:
        banker_badges.append("Banker In 🟢")
    if is_osr:
        banker_badges.append("IN - OSR 💎")
    if cur_ft > 50 and cur_ft > prev_ft:
        banker_badges.append("IN - R - XB ⚡")
    if not banker_badges and is_long_active:
        banker_badges.append("Whale Active 🟢")
        
    banker_badge_str = " | ".join(banker_badges) if banker_badges else "لا توجد علامة جديدة"
    banker_table_pos = "LONG 🟢 (صفقة شراء نشطة ومفتوحة على المؤشر)" if is_long_active else "FLAT ⚪ (محايد / بانتظار إشارة)"
    banker_status_text = (
        f"• <b>العلامة الظاهرة:</b> <code>{banker_badge_str}</code>\n"
        f"• <b>حالة الصفقة على المؤشر:</b> {banker_table_pos}\n"
        f"• <b>مستوى سيولة الحيتان (FundTrend):</b> <code>{cur_ft:,.1f} / 100</code>"
    )
    
    # Target calculations
    sl_p = round(cur_p * (1.0 - INITIAL_SL_PCT), 6)
    tp1_p = round(cur_p * (1.0 + TP1_PCT), 6)
    tp2_p = round(cur_p * (1.0 + TP2_PCT), 6)
    
    return {
        'symbol': name,
        'pair': pair,
        'current_price': cur_p,
        'quote_volume_24h': quote_vol_24h,
        'vol_ratio': round(vol_ratio, 2),
        'vol_spike': vol_spike,
        'at_support': at_support,
        'support_level': sup_level,
        'support_desc': support_desc,
        'dist_pct': round(dist_pct, 2),
        'has_squeeze': has_squeeze_condition,
        'squeeze_badge': squeeze_badge,
        'squeeze_desc': squeeze_status_text,
        'macd_ok': macd_ok,
        'macd_desc': macd_status_text,
        'banker_ok': banker_ok,
        'banker_desc': banker_status_text,
        'banker_badge_str': banker_badge_str,
        'banker_table_pos': banker_table_pos,
        'sl_price': sl_p,
        'tp1_price': tp1_p,
        'tp2_price': tp2_p
    }

def scan_market():
    btc_status = check_btc_regime()
    is_btc_bull = btc_status.get('is_bull', False)
    
    coins_to_scan = get_watchlist()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=35) as executor:
        scan_res = executor.map(analyze_coin, coins_to_scan)
        for r in scan_res:
            if r is not None:
                results.append(r)
                
    signals = []
    
    for r in results:
        # Check Core Requirements: Support + MACD + Banker
        core_met = r['at_support'] and r['macd_ok'] and r['banker_ok']
        if not core_met:
            continue
            
        # Case 1: All 4 indicators met (Support + Squeeze + MACD + Banker)
        if r['has_squeeze']:
            if is_btc_bull:
                r['tier'] = 1
                r['tier_badge'] = "💎🚀 إشارة ذهبية VIP (5/5 كاملة - السوق صاعد)"
                r['tier_desc'] = "محققة كامل الشروط الـ 5 مع طفرة فوليوم وانفجار سكويز ودعم البيتكوين"
                r['btc_warning'] = False
                signals.append(r)
            else:
                # BTC is NOT bull, but the 4 indicators are completely fulfilled!
                r['tier'] = 2
                r['tier_badge'] = "⚡🚀 صاروخ فني مستقل (4/4 مؤشرات كاملة)"
                r['tier_desc'] = "محققة كامل الشروط الفنية الـ 4 ذاتياً (دعم + سكويز + ماكد + بانكر)"
                r['btc_warning'] = True
                signals.append(r)
        # Case 2: Core met without active squeeze, but BTC is bull
        elif is_btc_bull:
            r['tier'] = 3
            r['tier_badge'] = "🟢 إشارة قياسية معتمدة (4/4 كاملة)"
            r['tier_desc'] = "محققة الأركان الأساسية بدعم صاعد من البيتكوين"
            r['btc_warning'] = False
            signals.append(r)
            
    # Priority Sorting:
    # 1. Tier 1 first, then Tier 2, then Tier 3
    # 2. Inside each Tier, highest 24H volume first!
    signals.sort(key=lambda x: (x['tier'], -x['quote_volume_24h']))
    
    reason = ""
    if len(signals) == 0:
        if not is_btc_bull:
            reason = f"🛡️ البيتكوين تحت Daily EMA50 ({btc_status['price']:,.1f} $ أقل من {btc_status['ema50']:,.1f} $)، الأجواء غير مناسبة لفتح إشارات شراء جديدة."
        else:
            reason = "ℹ️ البيتكوين صاعد، ولكن لم تكتمل شروط الشمعة اليومية ومناطق الدعم وتقاطع الماكد معاً في أي عملة اليوم."
            
    return {
        'btc_status': btc_status,
        'signals': signals,
        'all_scanned_count': len(results),
        'reason': reason
    }
