import numpy as np
import pandas as pd
import requests
import json
import concurrent.futures
from config import BINANCE_DATA_URL, BINANCE_REST_URL, WATCHLIST, BTC_EMA_PERIOD, INITIAL_SL_PCT, TP1_PCT

def calc_rma(series, length):
    alpha = 1.0 / length
    return series.ewm(alpha=alpha, adjust=False).mean()

def fetch_klines(symbol, interval="1d", limit=120):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    # Try data-api.binance.vision first (ideal for cloud/GitHub Actions)
    urls = [
        f"{BINANCE_DATA_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"{BINANCE_REST_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 40:
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

def analyze_coin(item):
    name, pair = item
    if pair == "BTCUSDT":
        return None
        
    df = fetch_klines(pair, interval="1d", limit=100)
    if df is None or len(df) < 40:
        return None
        
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    close_p = df['close'].values
    n = len(df)
    
    # 1. CM MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    df['macd_cross_up'] = (df['macd'].shift(1) <= df['signal'].shift(1)) & (df['macd'] > df['signal'])
    df['macd_cross_down'] = (df['macd'].shift(1) >= df['signal'].shift(1)) & (df['macd'] < df['signal'])
    
    # 2. Banker Fund Flow
    h27 = df['high'].rolling(27).max()
    l27 = df['low'].rolling(27).min()
    diff = h27 - l27
    diff = np.where(diff == 0, 0.0001, diff)
    raw_stoch = (df['close'] - l27) / diff * 100
    xsa1 = calc_rma(pd.Series(raw_stoch), 5)
    xsa2 = calc_rma(xsa1, 3)
    df['fundtrend'] = (3 * xsa1 - 2 * xsa2 - 50) * 1.032 + 50
    df['bullbearline'] = df['fundtrend'].ewm(span=13, adjust=False).mean()
    df['banker_active'] = df['fundtrend'] > df['bullbearline']
    
    # 3. Candlesticks
    body = np.abs(close_p - open_p)
    candle_range = high_p - low_p
    candle_range = np.where(candle_range == 0, 0.00001, candle_range)
    body = np.where(body == 0, 0.00001, body)
    lower_shadow = np.minimum(open_p, close_p) - low_p
    upper_shadow = high_p - np.maximum(open_p, close_p)
    is_green = close_p > open_p
    is_red = close_p < open_p
    
    # Patterns on last 2 candles
    patterns = []
    for i in [n-2, n-1]:
        # Hammer
        if (lower_shadow[i] >= 1.6 * body[i]) and (upper_shadow[i] <= 0.9 * body[i]) and ((close_p[i] - low_p[i]) >= 0.6 * candle_range[i]):
            patterns.append("Hammer")
        # Bullish Engulfing
        if i >= 1 and is_red[i-1] and is_green[i]:
            if close_p[i] >= open_p[i-1] * 0.998 and open_p[i] <= close_p[i-1] * 1.002:
                patterns.append("Bullish Engulfing")
        # 3 White Soldiers
        if i >= 2 and is_green[i] and is_green[i-1] and is_green[i-2]:
            if close_p[i] > close_p[i-1] and close_p[i-1] > close_p[i-2]:
                patterns.append("Three White Soldiers")
                
    # 4. Support Detection (SR Support Channel)
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
    
    cur_p = close_p[-1]
    cur_low = low_p[-1]
    
    # Check if price is within 3.5% of any confirmed support
    at_support = False
    sup_level = None
    for idx, s_val in valid_supports:
        if (cur_low <= s_val * 1.035 and cur_p >= s_val * 0.97) or abs(cur_low - s_val) / s_val <= 0.035:
            at_support = True
            sup_level = s_val
            break
            
    # 5. SML Squeeze (TTM Squeeze Pro)
    basis = df['close'].rolling(20).mean()
    dev = 2.0 * df['close'].rolling(20).std()
    upper_bb = basis + dev
    lower_bb = basis - dev
    
    tr = pd.concat([df['high'] - df['low'], np.abs(df['high'] - df['close'].shift(1)), np.abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()
    upper_kc = basis + 1.5 * atr20
    lower_kc = basis - 1.5 * atr20
    
    in_squeeze = (lower_bb > lower_kc) & (upper_bb < upper_kc)
    # Fired: was in squeeze 1 or 2 bars ago and now released
    squeeze_fired = ((in_squeeze.shift(1) == True) & (in_squeeze == False)) | ((in_squeeze.shift(2) == True) & (in_squeeze.shift(1) == False))
    recent_squeeze = in_squeeze | in_squeeze.shift(1) | in_squeeze.shift(2) | in_squeeze.shift(3)
    
    is_sq_now = bool(in_squeeze.iloc[-1])
    is_sq_fired = bool(squeeze_fired.iloc[-1] or (n > 2 and squeeze_fired.iloc[-2]))
    is_sq_energy = bool(recent_squeeze.iloc[-1])
    
    macd_cross = df['macd_cross_up'].iloc[-1] or df['macd_cross_up'].iloc[-2]
    banker_act = df['banker_active'].iloc[-1]
    
    # Base technical setup without BTC requirement
    core_technical_ok = at_support and (len(patterns) > 0) and macd_cross and banker_act
    
    squeeze_label = "NONE"
    if is_sq_fired:
        squeeze_label = "FIRED 🚀"
    elif is_sq_now or is_sq_energy:
        squeeze_label = "ENERGY ⚡"
        
    return {
        'symbol': name,
        'pair': pair,
        'current_price': cur_p,
        'at_support': at_support,
        'support_level': round(sup_level, 6) if sup_level else 0,
        'patterns': list(set(patterns)),
        'macd_cross': macd_cross,
        'macd_hist': round(df['hist'].iloc[-1], 6),
        'banker_active': banker_act,
        'banker_val': round(df['fundtrend'].iloc[-1], 1),
        'core_technical_ok': core_technical_ok,
        'is_squeeze_fired': is_sq_fired,
        'is_squeeze_energy': is_sq_energy,
        'squeeze_label': squeeze_label,
        'sl_price': round(cur_p * (1.0 - INITIAL_SL_PCT), 6),
        'tp1_price': round(cur_p * (1.0 + TP1_PCT), 6)
    }

def scan_market():
    btc_status = check_btc_regime()
    is_btc_bull = btc_status.get('is_bull', False)
    
    # Scan all watchlist coins
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        scan_res = executor.map(analyze_coin, WATCHLIST)
        for r in scan_res:
            if r is not None:
                results.append(r)
                
    buy_signals = []
    
    for r in results:
        if r['core_technical_ok']:
            has_squeeze = r['is_squeeze_fired'] or r['is_squeeze_energy']
            
            # Smart 3-Tier Classification
            if has_squeeze and is_btc_bull:
                r['tier'] = 1
                r['tier_badge'] = "💎🚀 سوبر صاروخ (المستوى الأول)"
                r['tier_desc'] = "انفجار سكويز + بيتكوين صاعد فوق EMA50 (أعلى أولوية)"
                r['is_buy_signal'] = True
                buy_signals.append(r)
            elif has_squeeze and not is_btc_bull:
                r['tier'] = 2
                r['tier_badge'] = "⚡🚀 صاروخ مستقل (المستوى الثاني)"
                r['tier_desc'] = "انفجار سكويز ذاتي (تتجاوز شرط البيتكوين بنجاح 80%+)"
                r['is_buy_signal'] = True
                buy_signals.append(r)
            elif not has_squeeze and is_btc_bull:
                r['tier'] = 3
                r['tier_badge'] = "🟢 كلاسيكية معتمدة (المستوى الثالث)"
                r['tier_desc'] = "شروط فنية كاملة مدعومة بصعود البيتكوين (بدون سكويز)"
                r['is_buy_signal'] = True
                buy_signals.append(r)
            else:
                # No squeeze AND BTC is bearish -> Strictly Forbidden!
                r['tier'] = 0
                r['is_buy_signal'] = False
                
    # Sort signals by Tier (Tier 1 first, then Tier 2, then Tier 3)
    buy_signals.sort(key=lambda x: x['tier'])
    
    reason = ""
    if len(buy_signals) == 0:
        if not is_btc_bull:
            reason = f"🛡️ البيتكوين تحت Daily EMA50 ({btc_status['price']:,.1f} $ < {btc_status['ema50']:,.1f} $)، ولم يتم رصد أي عملة في وضع انفجار سكويز مستقل اليوم."
        else:
            reason = "ℹ️ البيتكوين في وضع صاعد، ولكن لم تكتمل شروط الشمعة والدعم والماكد معاً في أي عملة اليوم."
            
    return {
        'btc_status': btc_status,
        'signals': buy_signals,
        'all_scanned_count': len(results),
        'reason': reason
    }
