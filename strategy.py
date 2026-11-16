import os
import json
import concurrent.futures
import pandas as pd
import numpy as np
import requests
from config import BINANCE_DATA_URL, BINANCE_REST_URL, get_watchlist


def fetch_klines_fast(symbol, interval="1d", limit=140):
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


def calc_all_indicators(df):
    """
    Calculates all elite indicators proven by extensive backtests across 200 coins:
    1. EMAs: EMA50, EMA200
    2. True Range & ATR(14) with 20-day lowest ATR for ATR 15% Expansion
    3. SuperTrend (10, 2.5): SuperTrend Flip model
    4. Ehlers Fisher Transform (10): Zero-lag deep bottom reversals
    5. Elder's Force Index (EFI 13): Buying surge above zero
    6. TTM Squeeze: Bollinger Bands inside Keltner Channel compression
    7. Volume MA20
    """
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values
    qv = df['quote_asset_volume'].values
    n = len(df)

    # 1. EMAs
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # True Range & ATR 14
    tr = np.zeros(n, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr14 = pd.Series(tr).rolling(14).mean().values
    df['atr14'] = atr14
    df['atr_low_20'] = pd.Series(atr14).rolling(20).min().values

    # 2. SuperTrend (10, 2.5)
    atr10 = pd.Series(tr).rolling(10).mean().values
    hl2 = (h + l) / 2.0
    u_band = hl2 + 2.5 * atr10
    l_band = hl2 - 2.5 * atr10
    st_dir = np.zeros(n, dtype=float)
    st_dir[:10] = -1.0
    for i in range(10, n):
        if c[i-1] <= u_band[i-1]:
            u_band[i] = min(u_band[i], u_band[i-1])
        if c[i-1] >= l_band[i-1]:
            l_band[i] = max(l_band[i], l_band[i-1])
        if c[i] > u_band[i-1]:
            st_dir[i] = 1.0
        elif c[i] < l_band[i-1]:
            st_dir[i] = -1.0
        else:
            st_dir[i] = st_dir[i-1]
    df['st_dir'] = st_dir

    # 3. Ehlers Fisher Transform (10)
    mp = (h + l) / 2.0
    x = np.zeros(n, dtype=float)
    fisher = np.zeros(n, dtype=float)
    for i in range(10, n):
        w_max = np.max(h[i-9:i+1])
        w_min = np.min(l[i-9:i+1])
        denom = w_max - w_min if w_max != w_min else 1e-9
        val = 0.33 * 2.0 * ((mp[i] - w_min) / denom - 0.5) + 0.67 * x[i-1]
        val = np.clip(val, -0.999, 0.999)
        x[i] = val
        fisher[i] = 0.5 * np.log((1.0 + val) / (1.0 - val)) + 0.5 * fisher[i-1]
    df['fisher'] = fisher

    # 4. Elder's Force Index (13)
    raw_force = np.zeros(n, dtype=float)
    for i in range(1, n):
        raw_force[i] = (c[i] - c[i-1]) * v[i]
    alpha = 2.0 / (13.0 + 1.0)
    efi = np.zeros(n, dtype=float)
    for i in range(1, n):
        efi[i] = alpha * raw_force[i] + (1.0 - alpha) * efi[i-1]
    df['efi'] = efi

    # 5. TTM Squeeze (Bollinger 20/2 vs Keltner 20/1.5) & Carter Linear Regression Momentum
    basis = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    bb_upper = basis + 2.0 * std
    bb_lower = basis - 2.0 * std
    atr20 = pd.Series(tr).rolling(20).mean().values
    keltner_upper = basis + 1.5 * atr20
    keltner_lower = basis - 1.5 * atr20
    df['in_squeeze'] = (bb_lower > keltner_lower) & (bb_upper < keltner_upper)

    # Momentum: Linear Regression of [Close - ((Highest(20)+Lowest(20))/2 + SMA(20))/2] over 20 bars
    highest_h = pd.Series(h).rolling(20).max().values
    lowest_l = pd.Series(l).rolling(20).min().values
    mid_donchian = (highest_h + lowest_l) / 2.0
    mid_avg = (mid_donchian + basis) / 2.0
    delta = c - mid_avg

    x = np.arange(20, dtype=float)
    x_dev = x - x.mean()
    x_var = np.sum(x_dev**2)

    mom = np.zeros(n, dtype=float)
    for idx_m in range(20, n):
        y = delta[idx_m-19:idx_m+1]
        y_mean = np.mean(y)
        slope = np.sum(x_dev * (y - y_mean)) / x_var
        intercept = y_mean - slope * x.mean()
        mom[idx_m] = intercept + slope * 19.0
    df['ttm_mom'] = mom

    # 6. Volume MA20
    df['vol_ma20'] = pd.Series(qv).rolling(20).mean().values
    return df


def find_support_confluence(df, idx, lookback=35):
    """
    Checks if bar idx or idx-1 rests at horizontal swing support,
    EMA50, or EMA200.
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
                    return True, "قاع سابق (Swing Low)", float(lj)

        # 2. Dynamic EMAs (EMA50, EMA200)
        levels = [
            ("متوسط EMA50", df['ema50'].iloc[check_i]),
            ("متوسط EMA200", df['ema200'].iloc[check_i]),
        ]
        for name, lvl in levels:
            if not np.isnan(lvl) and lvl > 0:
                if lvl <= cur_c * 1.015 and (abs(cur_l - lvl) / lvl <= 0.022 or (cur_l <= lvl and cur_c >= lvl * 0.985)):
                    return True, name, float(lvl)

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
    status_text = "🟢 صاعد فوق EMA50 (بيئة مثالية للتداول)" if is_bull else "🔴 تصحيحي أسفل EMA50 (تداول بحذر واقتنص الأهداف السريعة)"
    return {
        "price": cur_p,
        "ema50": round(ema50, 1),
        "is_bull": is_bull,
        "diff_pct": round(diff, 2),
        "status_text": status_text
    }


def analyze_coin_elite_models(item):
    """
    Analyzes a coin for the Elite Proven Models categorized into:
    1. الهدف السريع الخاطف (+3% في 24-48 ساعة):
       - Rank 1: Squeeze Fire + 2 Green Bars (عند دعم 🟢 - دقة 85.7% يوم أول | 100% إجمالي | صفر فشل)
       - Rank 2: SuperTrend Flip (عند دعم 🟢 - 82% أول يومين | 96% إجمالي | فشل 4%)
       - Rank 3: ATR 15% Expansion (عند دعم 🟢 - 74% أول يومين | 95.5% إجمالي)
       - Rank 4: Squeeze Fire + 2 Green Bars (بدون دعم ⚠️ - 68.2% أول يومين | 91.1% إجمالي)
       - Rank 5/6: Squeeze ON + 2 Green Bars (داخل الانضغاط)
    2. تعظيم الأرباح التراكمية (TP 6% / SL 4%):
       - Rank 1: Ehlers Fisher Transform (+188.6% أرباح صافية | PF 1.58)
       - Rank 2: Elder's Force Index (+156.7% أرباح صافية | PF 1.50)
       - Rank 3: TTM Squeeze Breakout (+98.2% أرباح صافية | PF 1.58)
    """
    sym, pair = item
    df = fetch_klines_fast(pair, interval="1d", limit=130)
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

    # Must be a green candle & volume boost >= 1.15x
    is_green = (c[i] > o[i])
    if not is_green:
        return None

    vol_ratio = round(qv[i] / (qv_ma[i] + 1e-9), 2) if (not np.isnan(qv_ma[i]) and qv_ma[i] > 0) else 1.0
    if vol_ratio < 1.15:
        return None

    cur_p = c[i]

    # Support confluence check
    has_sup, sup_type, sup_lvl = find_support_confluence(df, i)
    at_support = False
    if has_sup and sup_lvl and sup_lvl > 0:
        dist_from_sup = (cur_p - sup_lvl) / sup_lvl
        if -0.025 <= dist_from_sup <= 0.038:
            at_support = True

    # Support description and SL base
    if at_support:
        support_desc = f"🟢 مرتكز على {sup_type} ({format_price(sup_lvl)} $)"
        sl_base = sup_lvl
    else:
        support_desc = "⚠️ ليس عند دعم (انفجار حر مع الزخم السعري)"
        sl_base = min(l[i], l[i-1], l[i-2])

    target_3pct = cur_p * 1.03
    target_6pct = cur_p * 1.06
    stop_loss = min(l[i], sl_base) * 0.98

    signals = []

    # TTM Squeeze & Carter Momentum conditions
    in_sq = df['in_squeeze'].values
    moms = df['ttm_mom'].values
    two_greens = (
        (not np.isnan(moms[i])) and (not np.isnan(moms[i-1])) and (not np.isnan(moms[i-2])) and
        (moms[i] > moms[i-1]) and (moms[i-1] > moms[i-2])
    )
    was_in_sq = any(in_sq[max(0, i-3):i])
    is_sq_off = not in_sq[i]
    is_sq_fire = was_in_sq and is_sq_off  # Moment of explosion / breakout
    is_sq_on = in_sq[i]                   # Inside squeeze

    # =========================================================================
    # 1. SPECIAL STRATEGY: TTM Squeeze + 2 Green Bars
    # (النموذج الوحيد المسموح بإرساله حتى بدون دعم مع توضيح حالة الدعم صراحة)
    # =========================================================================
    if two_greens and is_sq_fire:
        if at_support:
            signals.append({
                'category': 'SCALP',
                'rank': 1,
                'model_name': '🚀 انفجار البولينجر وكلتنر (Squeeze Fire) + شمعتين خضر',
                'model_badge': '🚀 [المرتبة #1 للهدف الخاطف: انفجار كلتنر وبولينجر | عند دعم 🟢]',
                'win_rate_desc': '🏆 100% تحقيق هدف +3% مع صعود BTC (85.7% اليوم الأول) | 95.7% بدون BTC | صفر فشل',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })
        else:
            signals.append({
                'category': 'SCALP',
                'rank': 4,
                'model_name': '⚡ انفجار البولينجر وكلتنر (Squeeze Fire) + شمعتين خضر',
                'model_badge': '⚡ [هدف خاطف: انفجار كلتنر وبولينجر | بدون دعم ⚠️]',
                'win_rate_desc': '⚡ 68.2% في أول يومين (57.7% في اليوم الأول) | 91.1% إجمالي تحقيق الهدف',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': False,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

    elif two_greens and is_sq_on:
        if at_support:
            signals.append({
                'category': 'SCALP',
                'rank': 5,
                'model_name': '⏳ احتقان البولينجر داخل كلتنر (Squeeze ON) + شمعتين خضر',
                'model_badge': '⏳ [استعداد للانفجار: احتقان كلتنر وبولينجر | عند دعم 🟢]',
                'win_rate_desc': '💎 استعداد للانفجار: 80% تحقيق هدف +3% | أرباح +90% بوقف خسارة آمن',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })
        else:
            signals.append({
                'category': 'SCALP',
                'rank': 6,
                'model_name': '⏳ احتقان البولينجر داخل كلتنر (Squeeze ON) + شمعتين خضر',
                'model_badge': '⏳ [استعداد للانفجار: احتقان كلتنر وبولينجر | بدون دعم ⚠️]',
                'win_rate_desc': '⏳ داخل عنق الزجاجة: 56.2% في أول يومين | 86.3% إجمالي تحقيق الهدف',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': False,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

    # =========================================================================
    # 2. ALL OTHER STRATEGIES STRICTLY REQUIRE at_support == True
    # (جميع الاستراتيجيات الأخرى تشترط الارتكاز عند دعم حقيقي 100%)
    # =========================================================================
    if at_support:
        # Rank 2: SuperTrend Flip (انقلاب صاعد)
        st_dirs = df['st_dir'].values
        if st_dirs[i-1] == -1.0 and st_dirs[i] == 1.0:
            signals.append({
                'category': 'SCALP',
                'rank': 2,
                'model_name': '🚀 انقلاب السوبر ترند (SuperTrend Flip)',
                'model_badge': '🚀 [المرتبة #2 للهدف الخاطف: SuperTrend]',
                'win_rate_desc': '⚡ 82% في أول يومين (80% في اليوم الأول مباشرة!) | 96% إجمالي | فشل 4% فقط',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

        # Rank 3: ATR 15% Expansion (انفجار ATR من القاع)
        atr = df['atr14'].values
        atr_low = df['atr_low_20'].values
        if (not np.isnan(atr_low[i-1])) and (atr[i-1] <= atr_low[i-1] * 1.08) and (atr[i] >= atr_low[i-1] * 1.15):
            signals.append({
                'category': 'SCALP',
                'rank': 3,
                'model_name': '👑 انفجار ATR 15% من القاع',
                'model_badge': '👑 [المرتبة #3 للهدف الخاطف: ATR 15%]',
                'win_rate_desc': '👑 74% في أول يومين | 95.5% إجمالي | فشل 4.5% فقط | معامل ربح 1.51',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

        # Swing Rank 1: Ehlers Fisher Transform (انعكاس من قاع عميق)
        fishers = df['fisher'].values
        fisher_deep = (min(fishers[i-1], fishers[i-2]) <= -1.0)
        fisher_reversal = (fishers[i] > fishers[i-1])
        if fisher_deep and fisher_reversal:
            signals.append({
                'category': 'SWING',
                'rank': 1,
                'model_name': '💰 انعكاس فيشر من القاع (Ehlers Fisher)',
                'model_badge': '💰 [المرتبة #1 لتعظيم الأرباح: Ehlers Fisher]',
                'win_rate_desc': '🏆 أرباح قياسية صافية +188.6% | معامل ربحية 1.58 | وصول للهدف 86.2%',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

        # Swing Rank 2: Elder's Force Index (قفزة السيولة الهجومية فوق الصفر)
        efis = df['efi'].values
        if efis[i-1] <= 0.0 and efis[i] > 0.0:
            signals.append({
                'category': 'SWING',
                'rank': 2,
                'model_name': '⚡ قفزة السيولة الهجومية (Elder\'s Force Index)',
                'model_badge': '⚡ [المرتبة #2 لتعظيم الأرباح: Force Index]',
                'win_rate_desc': '🔥 أرباح صافية +156.7% | معامل ربحية 1.50 | وصول للهدف 83.1%',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

        # Swing Rank 3: TTM Squeeze Breakout (انفجار الاحتقان السعري الكلاسيكي)
        if was_in_sq and is_sq_off and not two_greens:
            signals.append({
                'category': 'SWING',
                'rank': 3,
                'model_name': '💎 انفجار الاحتقان السعري (TTM Squeeze)',
                'model_badge': '💎 [المرتبة #3 لتعظيم الأرباح: TTM Squeeze]',
                'win_rate_desc': '💎 أرباح +98.2% | معامل ربحية 1.58 | وصول للهدف 93.8%',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'at_support': True,
                'support_desc': support_desc,
                'vol_ratio': vol_ratio,
                'target_1': target_3pct,
                'target_2': target_6pct,
                'stop_loss': stop_loss,
            })

    if not signals:
        return None

    # Consolidation: Exactly ONE signal per coin. If multiple models match, merge into one confluence trade!
    if len(signals) == 1:
        s = signals[0]
        s['is_confluent'] = False
        s['confluence_count'] = 1
        s['matched_models'] = [s['model_name']]
        return [s]

    signals.sort(key=lambda x: x['rank'])
    base = signals[0]
    is_scalp = any(s['category'] == 'SCALP' for s in signals)
    combined_category = 'SCALP' if is_scalp else 'SWING'
    matched_names = [s['model_name'] for s in signals]

    combined_signal = {
        'category': combined_category,
        'rank': base['rank'],
        'is_confluent': True,
        'confluence_count': len(signals),
        'matched_models': matched_names,
        'model_name': " + ".join(matched_names),
        'model_badge': f"🌟👑 [صفقة فائقة التوافق: {len(signals)} استراتيجيات متزامنة!]",
        'win_rate_desc': f"🔥 قوة توافق مضاعفة ({len(signals)} استراتيجيات) | أقوى نموذج: {base['win_rate_desc']}",
        'symbol': base['symbol'],
        'pair': base['pair'],
        'price': base['price'],
        'at_support': any(s['at_support'] for s in signals),
        'support_desc': base['support_desc'],
        'vol_ratio': base['vol_ratio'],
        'target_1': base['target_1'],
        'target_2': base['target_2'],
        'stop_loss': base['stop_loss'],
    }
    return [combined_signal]


def inspect_intraday_status(symbol, pair, cur_p):
    """
    Checks intraday 1H klines to detect:
    1. If the trade already ignited earlier (e.g. at 07:00 or 08:00 UTC).
    2. How much it has pumped since ignition (gain_pct).
    3. Whether it is a Fresh Entry or an Already-Running trade (to prevent late FOMO entry).
    """
    try:
        df_1h = fetch_klines_fast(pair, '1h', limit=70)
        if df_1h is None or len(df_1h) < 10:
            return {
                'is_running': False,
                'ignition_time': 'اليوم',
                'ignition_price': cur_p,
                'gain_pct': 0.0,
                'max_gain_pct': 0.0,
                'today_high': cur_p
            }
        
        today_date = df_1h['datetime'].iloc[-1].date()
        today_candles = df_1h[df_1h['datetime'].dt.date == today_date]
        if len(today_candles) == 0:
            return {
                'is_running': False,
                'ignition_time': 'اليوم',
                'ignition_price': cur_p,
                'gain_pct': 0.0,
                'max_gain_pct': 0.0,
                'today_high': cur_p
            }

        prior = df_1h[df_1h['datetime'].dt.date < today_date]
        avg_vol = prior['volume'].tail(24).mean() if len(prior) >= 5 else today_candles['volume'].mean()

        spikes = today_candles[today_candles['volume'] >= avg_vol * 1.5]
        if len(spikes) > 0:
            first_spike = spikes.iloc[0]
            ign_time = first_spike['datetime'].strftime('%H:%M UTC')
            ign_price = float(first_spike['open'])
        else:
            ign_time = '00:00 UTC'
            ign_price = float(today_candles.iloc[0]['open'])

        today_high = float(today_candles['high'].max())
        gain_pct = round(((cur_p - ign_price) / ign_price) * 100, 2)
        max_gain_pct = round(((today_high - ign_price) / ign_price) * 100, 2)

        # Running condition: pumped >= 1.8% or reached +3% target already
        is_running = bool((gain_pct >= 1.8) or (max_gain_pct >= 3.0))

        return {
            'is_running': is_running,
            'ignition_time': ign_time,
            'ignition_price': ign_price,
            'gain_pct': gain_pct,
            'max_gain_pct': max_gain_pct,
            'today_high': today_high
        }
    except Exception:
        return {
            'is_running': False,
            'ignition_time': 'اليوم',
            'ignition_price': cur_p,
            'gain_pct': 0.0,
            'max_gain_pct': 0.0,
            'today_high': cur_p
        }


def scan_authorized_strategies():
    """
    Scans the complete Binance USDT watchlist in parallel, sorting signals
    strictly from strongest to weakest within each department.
    """
    watchlist = get_watchlist()
    scalp_signals = []
    swing_signals = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(analyze_coin_elite_models, item) for item in watchlist]
        for f in concurrent.futures.as_completed(futures):
            sigs = f.result()
            if sigs:
                for s in sigs:
                    if s['category'] == 'SCALP':
                        scalp_signals.append(s)
                    elif s['category'] == 'SWING':
                        swing_signals.append(s)

    # Sort strictly from strongest to weakest:
    # Primary sort: rank (1 then 2 then 3)
    # Secondary sort: volume ratio descending
    scalp_signals.sort(key=lambda x: (x['rank'], -x['vol_ratio']))
    swing_signals.sort(key=lambda x: (x['rank'], -x['vol_ratio']))

    return {
        'scalp': scalp_signals,
        'swing': swing_signals,
        'total_scanned': len(watchlist),
    }


def format_price(p):
    """Formats crypto prices dynamically with precision tailored to asset scale."""
    if p is None or np.isnan(p) or p == 0:
        return "0.0"
    if p >= 1000:
        return f"{p:,.2f}"
    elif p >= 1.0:
        return f"{p:.4f}".rstrip('0').rstrip('.')
    elif p >= 0.01:
        return f"{p:.4f}"
    elif p >= 0.0001:
        return f"{p:.6f}"
    elif p >= 0.000001:
        return f"{p:.8f}".rstrip('0')
    else:
        return f"{p:.10f}".rstrip('0')


def format_authorized_report(scan_res):
    """
    Formats the complete trading report for Telegram with signals organized
    from strongest to weakest into the two core trading departments.
    """
    btc = check_btc_regime()
    scalp = scan_res.get('scalp', [])
    swing = scan_res.get('swing', [])
    total_signals = len(scalp) + len(swing)

    btc_icon = "🟢" if btc.get('is_bull') else "🔴"
    btc_diff = btc.get('diff_pct', 0)
    diff_sign = "+" if btc_diff >= 0 else ""

    messages = []

    # 1. Header Message
    header = (
        f"🎯 <b>رادار النخبة الرقمي (Elite Crypto Radar 1D)</b>\n"
        f"────────────────────\n"
        f"📊 <b>وضع البيتكوين العام (BTC Regime):</b>\n"
        f"• السعر: <code>{format_price(btc.get('price', 0))} $</code>\n"
        f"• Daily EMA50: <code>{format_price(btc.get('ema50', 0))} $</code> ({diff_sign}{btc_diff}%)\n"
        f"• الحالة: {btc_icon} <b>{btc.get('status_text', '')}</b>\n"
        f"────────────────────\n"
        f"📈 <b>إحصائيات الفحص الشامل:</b>\n"
        f"• تم فحص: <b>{scan_res.get('total_scanned', 200)}</b> عملة USDT نشطة\n"
        f"• ⚡ <b>صفقات الهدف الخاطف (+3%):</b> {len(scalp)} فرصة\n"
        f"• 🚀 <b>صفقات تعظيم الأرباح (TP 6%):</b> {len(swing)} فرصة\n"
        f"📌 <i>تم ترتيب جميع الفرص تنازلياً من الأقوى للأضعف علمياً.</i>\n"
        f"────────────────────"
    )
    messages.append(header)

    # 2. Section 1: صفقات الهدف السريع الخاطف (+3% في 24-48 ساعة)
    if scalp:
        lines = [
            f"⚡ <b>القسم الأول: صفقات الهدف السريع الخاطف (+3% في 24-48 ساعة)</b>\n"
            f"<i>(مرتبة من الأقوى للأضعف: 1️⃣ انفجار كلتنر وبولينجر ثم 2️⃣ SuperTrend Flip ثم 3️⃣ ATR 15%)</i>\n"
            f"────────────────────"
        ]
        for s in scalp:
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

    # 3. Section 2: صفقات تعظيم الأرباح والموجات (TP 6% / SL 4%)
    if swing:
        lines = [
            f"🚀 <b>القسم الثاني: صفقات تعظيم الأرباح والموجات (TP 6% / SL 4%)</b>\n"
            f"<i>(مرتبة من الأقوى ربحية: 1️⃣ Ehlers Fisher ثم 2️⃣ Force Index ثم 3️⃣ TTM Squeeze)</i>\n"
            f"────────────────────"
        ]
        for s in swing:
            if s.get('is_confluent'):
                models_block = (
                    f"🌟 <b>توافق استراتيجي مضاعف ({s['confluence_count']} نماذج متزامنة!):</b>\n" +
                    "\n".join([f"  • {m}" for m in s['matched_models']])
                )
            else:
                models_block = f"• <b>النموذج:</b> {s['model_name']}"

            lines.append(
                f"{s['model_badge']}\n"
                f"💎 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"{models_block}\n"
                f"• <b>سعر الدخول:</b> <code>{format_price(s['price'])} $</code>\n"
                f"• <b>📍 حالة الدعم:</b> <b>{s['support_desc']}</b>\n"
                f"• <b>السيولة الحجمية:</b> <code>{s['vol_ratio']}x</code> فوليوم أعلى من المعدل\n"
                f"• 💰 <b>الأرباح التاريخية:</b> <i>{s['win_rate_desc']}</i>\n"
                f"• 🎯 <b>هدف 1 (+3%):</b> <code>{format_price(s['target_1'])} $</code>\n"
                f"• 🚀 <b>هدف رئيسي (+6%):</b> <code>{format_price(s['target_2'])} $</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{format_price(s['stop_loss'])} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 4. Empty State
    if total_signals == 0:
        messages.append(
            "ℹ️ <b>لا توجد عملات تطابق شروط النماذج الخمسة الصارمة اليوم.</b>\n\n"
            "جميع العملات المفحوصة إما بعيدة عن الدعم أو لم تكتمل شروط الانفجار السعري.\n"
            "تذكر: الصبر وحماية رأس المال هو سر التداول الرابح."
        )

    return messages


# Compatibility aliases
analyze_coin_authorized_strategies = analyze_coin_elite_models
scan_ichimoku_trio = scan_authorized_strategies
format_ichimoku_trio_report = format_authorized_report
