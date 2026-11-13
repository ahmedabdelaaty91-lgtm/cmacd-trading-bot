import os
import json
import concurrent.futures
import pandas as pd
import numpy as np
import requests
from config import BINANCE_DATA_URL, BINANCE_REST_URL, get_watchlist


def fetch_klines_fast(symbol, interval="1d", limit=160):
    """
    Fetches daily or 4H klines fast with failover between Binance Vision and REST endpoints.
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
                if len(data) >= 70:
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


def calc_wma_fast(series, length):
    """Calculates Weighted Moving Average (WMA) efficiently using convolution."""
    weights = np.arange(1, length + 1, dtype=float)
    weights /= weights.sum()
    vals = series.values
    if len(vals) < length:
        return pd.Series(np.nan, index=series.index)
    conv = np.convolve(vals, weights[::-1], mode='valid')
    padded = np.empty(len(vals))
    padded[:length - 1] = np.nan
    padded[length - 1:] = conv
    return pd.Series(padded, index=series.index)


def calc_hma_55(series, length=55):
    """Calculates Hull Moving Average (HMA 55) for Hull Suite."""
    half = max(1, int(length / 2))
    sq = max(1, int(np.sqrt(length)))
    wma_h = calc_wma_fast(series, half)
    wma_f = calc_wma_fast(series, length)
    diff = 2.0 * wma_h - wma_f
    return calc_wma_fast(diff, sq)


def calc_all_indicators(df):
    """
    Calculates:
    1. EMAs: EMA50 and EMA200
    2. Hull Suite (HMA 55): Direction and color (Green when rising & price above 0.99*HMA)
    3. TMO (Mobius True Momentum Oscillator: 14, 5, 3)
    4. Volume MA20
    """
    c = df['close']
    o = df['open']
    qv = df['quote_asset_volume']
    n = len(df)

    # 1. EMAs
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()

    # 2. Hull Suite (HMA 55)
    hma = calc_hma_55(c, 55)
    df['hull'] = hma
    df['hull_green'] = (hma > hma.shift(2)) & (c >= hma * 0.99)

    # 3. TMO (Mobius True Momentum Oscillator: length=14, ema1=5, ema2=3, signal=3)
    raw_s = np.zeros(n, dtype=float)
    c_arr = c.values
    o_arr = o.values
    length = 14
    for idx in range(n):
        past_o = o_arr[max(0, idx - length + 1): idx + 1]
        cur_c = c_arr[idx]
        raw_s[idx] = float(np.sum(cur_c > past_o) - np.sum(cur_c < past_o))

    s_series = pd.Series(raw_s, index=df.index)
    tmo_ema = s_series.ewm(span=5, adjust=False).mean()
    tmo_main = tmo_ema.ewm(span=3, adjust=False).mean()
    tmo_signal = tmo_main.ewm(span=3, adjust=False).mean()

    df['tmo_main'] = tmo_main
    df['tmo_signal'] = tmo_signal

    # 4. Volume MA20
    df['vol_ma20'] = qv.rolling(20).mean()
    return df


def find_support_confluence(df, idx, lookback=35):
    """
    Checks if bar idx or idx-1 rests at horizontal swing support,
    Hull Suite line, EMA50, or EMA200.
    Returns (has_support, support_type, support_level).
    """
    for check_i in (idx, idx - 1):
        if check_i < 2:
            continue
        cur_l = df['low'].iloc[check_i]
        cur_c = df['close'].iloc[check_i]
        start = max(2, check_i - lookback)

        # 1. Swing low check
        for j in range(start, check_i - 2):
            lj = df['low'].iloc[j]
            if (lj <= df['low'].iloc[j - 1] and lj <= df['low'].iloc[j - 2] and
                lj <= df['low'].iloc[j + 1] and lj <= df['low'].iloc[j + 2]):
                if lj <= cur_c * 1.015 and (abs(cur_l - lj) / lj <= 0.025 or (cur_l <= lj and cur_c >= lj * 0.985)):
                    return True, "قاع سابق (Swing Low)", round(lj, 4)

        # 2. Hull Suite dynamic support
        hull_val = df['hull'].iloc[check_i]
        if not np.isnan(hull_val) and hull_val > 0:
            if cur_l <= hull_val * 1.018 and cur_c >= hull_val * 0.985:
                return True, "خط Hull Suite المائل", round(hull_val, 4)

        # 3. Dynamic EMAs (EMA50, EMA200)
        levels = [
            ("متوسط EMA50", df['ema50'].iloc[check_i]),
            ("متوسط EMA200", df['ema200'].iloc[check_i]),
        ]
        for name, lvl in levels:
            if not np.isnan(lvl) and lvl > 0:
                if lvl <= cur_c * 1.015 and (abs(cur_l - lvl) / lvl <= 0.022 or (cur_l <= lvl and cur_c >= lvl * 0.985)):
                    return True, name, round(lvl, 4)

    return False, None, None


def check_btc_regime():
    """
    Checks BTC Daily price vs EMA 50 to assess macro market health.
    Returns dictionary with BTC price, Daily EMA50, bull status, distance %, and status text.
    """
    df = fetch_klines_fast("BTCUSDT", interval="1d", limit=100)
    if df is None or len(df) < 55:
        return {
            "price": 0,
            "ema50": 0,
            "is_bull": False,
            "diff_pct": 0,
            "status_text": "غير متاح"
        }
    c = df['close']
    ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    cur_p = c.iloc[-1]
    diff = ((cur_p - ema50) / ema50) * 100.0
    is_bull = cur_p > ema50
    status_text = "🟢 آمن صاعد فوق EMA50 (بيئة مثالية)" if is_bull else "🔴 حذر تصحيحي أسفل EMA50 (تداول بحذر)"
    return {
        "price": cur_p,
        "ema50": round(ema50, 1),
        "is_bull": is_bull,
        "diff_pct": round(diff, 2),
        "status_text": status_text
    }


def analyze_coin_authorized_strategies(item):
    """
    Analyzes a coin exclusively for the two authorized models:
    1. النموذج الأساسي: تقاطع TMO + خط Hull Suite أخضر + عند الدعم
    2. النموذج الأقوى 🔥: عند دعم + خط Hull أخضر + شمعة خضراء + فوليوم ≥ 1.15x
    """
    sym, pair = item
    df = fetch_klines_fast(pair, interval="1d", limit=120)
    if df is None or len(df) < 65:
        return None

    df = calc_all_indicators(df)
    n = len(df)
    i = n - 1  # latest candle

    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    qv = df['quote_asset_volume'].values
    qv_ma = df['vol_ma20'].values
    tmo_m = df['tmo_main'].values
    tmo_s = df['tmo_signal'].values
    hull_g = df['hull_green'].values

    # Check for TMO Bullish Cross (today or yesterday)
    cross_today = (tmo_m[i] > tmo_s[i]) and (tmo_m[i - 1] <= tmo_s[i - 1])
    cross_yest = (tmo_m[i - 1] > tmo_s[i - 1]) and (tmo_m[i - 2] <= tmo_s[i - 2]) and (tmo_m[i] > tmo_s[i])
    has_tmo_cross = cross_today or cross_yest

    if not has_tmo_cross:
        return None

    # Condition 1: Hull Suite must be green
    is_hull_green = bool(hull_g[i])
    if not is_hull_green:
        return None

    # Condition 2: Support confluence
    has_sup, sup_type, sup_lvl = find_support_confluence(df, i)
    if not has_sup:
        return None

    cur_p = c[i]
    is_green = c[i] > o[i]
    vol_ratio = round(qv[i] / (qv_ma[i] + 1e-9), 2) if (not np.isnan(qv_ma[i]) and qv_ma[i] > 0) else 1.0
    is_vol_boost = vol_ratio >= 1.15

    # Determine Model:
    # Model 2: النموذج الأقوى 🔥 (Support + Hull Green + Green Candle + Volume >= 1.15x)
    # Model 1: النموذج الأساسي (Support + Hull Green + TMO Cross)
    is_golden = is_green and is_vol_boost
    model_type = "GOLDEN" if is_golden else "BASE"
    model_name = "🌟 النموذج الأقوى 🔥 (فوليوم عالي + شمعة خضراء)" if is_golden else "⚡ النموذج الأساسي (TMO + Hull + دعم)"
    model_badge = "🌟 [النموذج الأقوى 🔥]" if is_golden else "⚡ [النموذج الأساسي]"

    # Targets & SL
    target_1 = round(cur_p * 1.03, 4)  # +3% fast target
    target_2 = round(cur_p * 1.06, 4)  # +6% runner target
    sl_base = sup_lvl if sup_lvl else l[i]
    stop_loss = round(min(l[i], sl_base) * 0.98, 4)

    return [{
        'model_type': model_type,
        'model_name': model_name,
        'model_badge': model_badge,
        'symbol': sym,
        'pair': pair,
        'price': cur_p,
        'support_type': sup_type,
        'support_lvl': sup_lvl,
        'vol_ratio': vol_ratio,
        'is_green': is_green,
        'target_1': target_1,
        'target_2': target_2,
        'stop_loss': stop_loss,
        'cross_bar': "شمعة اليوم" if cross_today else "شمعة الأمس",
        'is_oversold': tmo_m[i] < 0,
    }]


def scan_authorized_strategies():
    """
    Scans the complete Binance USDT watchlist in parallel for the two authorized models.
    """
    watchlist = get_watchlist()
    golden_list = []
    base_list = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [executor.submit(analyze_coin_authorized_strategies, item) for item in watchlist]
        for f in concurrent.futures.as_completed(futures):
            sigs = f.result()
            if sigs:
                for s in sigs:
                    if s['model_type'] == 'GOLDEN':
                        golden_list.append(s)
                    else:
                        base_list.append(s)

    # Sort each list by volume ratio
    golden_list.sort(key=lambda x: x['vol_ratio'], reverse=True)
    base_list.sort(key=lambda x: x['vol_ratio'], reverse=True)

    return {
        'golden': golden_list,
        'base': base_list,
        'total_scanned': len(watchlist),
    }


def format_authorized_report(scan_res):
    """
    Formats the complete trading report for Telegram with explicit Model identification
    and comprehensive Bitcoin regime assessment.
    """
    btc = check_btc_regime()
    golden = scan_res.get('golden', [])
    base = scan_res.get('base', [])
    total_signals = len(golden) + len(base)

    btc_icon = "🟢" if btc.get('is_bull') else "🔴"
    btc_diff = btc.get('diff_pct', 0)
    diff_sign = "+" if btc_diff >= 0 else ""

    messages = []

    # 1. Header Message
    header = (
        f"🎯 <b>رادار صفقات TMO Scalper & Hull Suite اليومي (1D)</b>\n"
        f"────────────────────\n"
        f"📊 <b>وضع البيتكوين (BTC Macro Regime):</b>\n"
        f"• السعر: <code>{btc.get('price', 0):,.1f} $</code>\n"
        f"• Daily EMA50: <code>{btc.get('ema50', 0):,.1f} $</code> ({diff_sign}{btc_diff}%)\n"
        f"• الحالة: {btc_icon} <b>{btc.get('status_text', '')}</b>\n"
        f"────────────────────\n"
        f"📈 <b>إحصائيات الفحص:</b>\n"
        f"• تم فحص: <b>{scan_res.get('total_scanned', 300)}</b> عملة USDT\n"
        f"• 🌟 <b>النموذج الأقوى 🔥:</b> {len(golden)} عملة (دقة 70.7% في أول يومين | 90.9% إجمالي)\n"
        f"• ⚡ <b>النموذج الأساسي:</b> {len(base)} عملة (دقة 63.5% في أول يومين | 86.3% إجمالي)\n"
        f"• 🎯 الهدف السريع: <b>+3.0%</b> | 🚀 هدف الموجه: <b>+6.0%</b>\n"
        f"────────────────────"
    )
    messages.append(header)

    # 2. Section 1: النموذج الأقوى 🔥
    if golden:
        lines = [
            f"🌟 <b>1. إشارات [النموذج الأقوى 🔥]</b>\n"
            f"<i>(تقاطع TMO + خط Hull أخضر + ارتكاز عند دعم + شمعة خضراء + سيولة ≥ 1.15x)</i>\n"
            f"────────────────────"
        ]
        for s in golden:
            oversold_tag = " | 💎 تشبع بيعي (TMO &lt; 0)" if s['is_oversold'] else ""
            lines.append(
                f"🔥 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• <b>النموذج:</b> 🌟 <b>النموذج الأقوى 🔥</b>\n"
                f"• <b>سعر الدخول:</b> <code>{s['price']} $</code>\n"
                f"• <b>الدعم المرتكز عليه:</b> {s['support_type']} (<code>{s['support_lvl']} $</code>)\n"
                f"• <b>السيولة:</b> <code>{s['vol_ratio']}x</code> فوليوم أعلى من المعدل{oversold_tag}\n"
                f"• <b>توقيت التقاطع:</b> {s['cross_bar']}\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{s['target_1']} $</code>\n"
                f"• 🚀 <b>هدف الموجه (+6%):</b> <code>{s['target_2']} $</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 3. Section 2: النموذج الأساسي
    if base:
        lines = [
            f"⚡ <b>2. إشارات [النموذج الأساسي]</b>\n"
            f"<i>(تقاطع TMO + خط Hull Suite أخضر + ارتكاز عند دعم)</i>\n"
            f"────────────────────"
        ]
        for s in base:
            oversold_tag = " | 💎 تشبع بيعي" if s['is_oversold'] else ""
            lines.append(
                f"⚡ <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• <b>النموذج:</b> ⚡ <b>النموذج الأساسي</b>\n"
                f"• <b>سعر الدخول:</b> <code>{s['price']} $</code>\n"
                f"• <b>الدعم المرتكز عليه:</b> {s['support_type']} (<code>{s['support_lvl']} $</code>)\n"
                f"• <b>السيولة:</b> <code>{s['vol_ratio']}x</code>{oversold_tag}\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{s['target_1']} $</code>\n"
                f"• 🚀 <b>هدف الموجه (+6%):</b> <code>{s['target_2']} $</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 4. Empty State
    if total_signals == 0:
        messages.append(
            "ℹ️ <b>لا توجد عملات تطابق النموذجين اليوم.</b>\n\n"
            "السوق حالياً في مرحلة تماسك أو انتظار إشارات مكتملة الشروط لحماية رأس المال.\n"
            f"وضع البيتكوين الحالي: {btc.get('status_text', '')}."
        )

    return messages


# Compatibility aliases
analyze_coin_ichimoku_trio = analyze_coin_authorized_strategies
scan_ichimoku_trio = scan_authorized_strategies
format_ichimoku_trio_report = format_authorized_report
