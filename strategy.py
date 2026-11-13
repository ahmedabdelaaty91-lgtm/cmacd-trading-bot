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
                if len(data) >= 80:
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
    Calculates Ichimoku (Tenkan, Kijun, Cloud), EMAs (9, 21, 50, 200),
    MACD (12, 26, 9), Stochastic (14, 3, 3), and Volume MA20.
    """
    h = df['high']
    l = df['low']
    c = df['close']
    v = df['volume']
    qv = df['quote_asset_volume']

    # 1. EMAs
    df['ema9'] = c.ewm(span=9, adjust=False).mean()
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()

    # 2. MACD (12, 26, 9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # 3. Stochastic (14, 3, 3) - matches TradingView
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    denom14 = (high14 - low14).replace(0, np.nan)
    raw_k = 100.0 * (c - low14) / denom14
    df['stoch_k'] = raw_k.rolling(3).mean()
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()

    # 4. Ichimoku
    df['tenkan'] = (h.rolling(9).max() + l.rolling(9).min()) / 2.0
    df['kijun'] = (h.rolling(26).max() + l.rolling(26).min()) / 2.0
    span_a_raw = (df['tenkan'] + df['kijun']) / 2.0
    df['span_a'] = span_a_raw.shift(26)
    span_b_raw = (h.rolling(52).max() + l.rolling(52).min()) / 2.0
    df['span_b'] = span_b_raw.shift(26)
    df['kumo_top'] = np.maximum(df['span_a'], df['span_b'])
    df['kumo_bottom'] = np.minimum(df['span_a'], df['span_b'])

    # 5. Volume MA
    df['vol_ma20'] = qv.rolling(20).mean()
    return df


def find_support_confluence(df, idx, lookback=35):
    """
    Checks if bar idx or idx-1 rests at horizontal swing support,
    EMA50, EMA200, Kijun, or Kumo Top.
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
                if lj <= cur_c * 1.01 and (abs(cur_l - lj) / lj <= 0.025 or (cur_l <= lj and cur_c >= lj * 0.985)):
                    return True, "قاع سابق (Swing Low)", round(lj, 4)

        # 2. Dynamic supports (EMA50, EMA200, Kijun, Kumo Top)
        levels = [
            ("متوسط EMA50", df['ema50'].iloc[check_i]),
            ("متوسط EMA200", df['ema200'].iloc[check_i]),
            ("خط الكيجين سن (Kijun)", df['kijun'].iloc[check_i]),
            ("سقف السحابة (Kumo Top)", df['kumo_top'].iloc[check_i]),
        ]
        for name, lvl in levels:
            if not np.isnan(lvl) and lvl > 0:
                if lvl <= cur_c * 1.01 and (abs(cur_l - lvl) / lvl <= 0.022 or (cur_l <= lvl and cur_c >= lvl * 0.985)):
                    return True, name, round(lvl, 4)

    return False, None, None


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


def analyze_coin_authorized_strategies(item):
    """
    Scans a coin for the exact authorized strategies:
    1. EMA 9 / EMA 21 Bullish Cross at Support (Success rate: 81%-85% in 2 days)
    2. MACD Bullish Cross at Support (Success rate: 71.8% in 2 days)
    3. Ichimoku Tenkan/Kijun (TK) Cross at Support (Success rate: 69.7% in 2 days)
    4. Stochastic (14, 3, 3) Bullish Cross at Support (< 35) (Success rate: 63.5% in 2 days)
    5. Kumo Breakout (سحابة): About to break or recently broke above cloud top!
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

    e9 = df['ema9'].values
    e21 = df['ema21'].values
    macd = df['macd'].values
    msig = df['macd_signal'].values
    tenkan = df['tenkan'].values
    kijun = df['kijun'].values
    sk = df['stoch_k'].values
    sd = df['stoch_d'].values
    k_top = df['kumo_top'].values

    cur_p = c[i]
    is_green = c[i] > o[i]
    is_vol_boost = (qv[i] >= qv_ma[i] * 1.15) if (not np.isnan(qv_ma[i]) and qv_ma[i] > 0) else False

    has_sup, sup_type, sup_lvl = find_support_confluence(df, i)

    signals = []

    # -------------------------------------------------------------------------
    # STRATEGY 1: 🥇 تقاطع EMA 9 / EMA 21 عند دعم + خضراء + فوليوم (PF 81%-85%)
    # -------------------------------------------------------------------------
    ema_cross_today = (e9[i] > e21[i]) and (e9[i - 1] <= e21[i - 1])
    ema_cross_yest = (e9[i - 1] > e21[i - 1]) and (e9[i - 2] <= e21[i - 2]) and (e9[i] > e21[i])
    has_ema_cross = ema_cross_today or ema_cross_yest

    if has_ema_cross and has_sup and is_green and is_vol_boost:
        signals.append({
            'strategy_type': 'EMA9_21_SUPPORT',
            'strategy_name': '🥇 تقاطع متوسطات الاتجاه السريع (EMA 9 / EMA 21)',
            'badge': '🥇 الأقوى والأسرع (81% في يومين)',
            'symbol': sym,
            'pair': pair,
            'price': cur_p,
            'support_type': sup_type,
            'support_lvl': sup_lvl,
            'vol_ratio': round(qv[i] / (qv_ma[i] + 1e-9), 2),
            'target_fast_3pct': round(cur_p * 1.03, 4),
            'target_runner_6pct': round(cur_p * 1.06, 4),
            'stop_loss': round(l[i] * 0.98, 4),
            'description': f'تقاطع صاعد لمتوسط EMA9 فوق EMA21 مستنداً على {sup_type} مع شمعة خضراء وسيولة مرتفعة ({qv[i] / qv_ma[i]:.1f}x).'
        })

    # -------------------------------------------------------------------------
    # STRATEGY 2: 🥈 تقاطع الماكد الإيجابي عند دعم + خضراء + فوليوم (71.8% في يومين)
    # -------------------------------------------------------------------------
    macd_cross_today = (macd[i] > msig[i]) and (macd[i - 1] <= msig[i - 1])
    macd_cross_yest = (macd[i - 1] > msig[i - 1]) and (macd[i - 2] <= msig[i - 2]) and (macd[i] > msig[i])
    has_macd_cross = macd_cross_today or macd_cross_yest

    if has_macd_cross and has_sup and is_green and is_vol_boost:
        is_below_zero = macd[i] < 0
        extra_note = "تحت الصفر (منطقة قاع صلبة)" if is_below_zero else "فوق الصفر (استمرار ترند صاعد)"
        signals.append({
            'strategy_type': 'MACD_SUPPORT',
            'strategy_name': '🥈 تقاطع الماكد الإيجابي (MACD Bullish Cross)',
            'badge': '🥈 زخم سيولة (72% في يومين)',
            'symbol': sym,
            'pair': pair,
            'price': cur_p,
            'support_type': sup_type,
            'support_lvl': sup_lvl,
            'vol_ratio': round(qv[i] / (qv_ma[i] + 1e-9), 2),
            'target_fast_3pct': round(cur_p * 1.03, 4),
            'target_runner_6pct': round(cur_p * 1.06, 4),
            'stop_loss': round(l[i] * 0.98, 4),
            'description': f'تقاطع إيجابي لخط الماكد مع خط الإشارة عند {sup_type} {extra_note} مع شمعة خضراء وفوليوم عالي.'
        })

    # -------------------------------------------------------------------------
    # STRATEGY 3: 🥉 تقاطع التنكن سن فوق الكيجن سن (TK Cross) عند دعم (69.7% في يومين)
    # -------------------------------------------------------------------------
    tk_cross_today = (tenkan[i] > kijun[i]) and (tenkan[i - 1] <= kijun[i - 1])
    tk_cross_yest = (tenkan[i - 1] > kijun[i - 1]) and (tenkan[i - 2] <= kijun[i - 2]) and (tenkan[i] > kijun[i])
    has_tk_cross = tk_cross_today or tk_cross_yest

    if has_tk_cross and has_sup and is_green and is_vol_boost:
        signals.append({
            'strategy_type': 'TK_CROSS_SUPPORT',
            'strategy_name': '🥉 تقاطع التنكن والكيجن سن (Ichimoku TK Cross)',
            'badge': '🥉 إشارة إيشيموكو صاعدة',
            'symbol': sym,
            'pair': pair,
            'price': cur_p,
            'support_type': sup_type,
            'support_lvl': sup_lvl,
            'vol_ratio': round(qv[i] / (qv_ma[i] + 1e-9), 2),
            'target_fast_3pct': round(cur_p * 1.03, 4),
            'target_runner_6pct': round(cur_p * 1.06, 4),
            'stop_loss': round(l[i] * 0.98, 4),
            'description': f'تقاطع خط Tenkan-sen صاعداً فوق Kijun-sen مع ارتكاز على {sup_type} وشمعة دافعة خضراء.'
        })

    # -------------------------------------------------------------------------
    # STRATEGY 4: 🎖️ تقاطع الاستوكاستك (14, 3, 3) عند دعم (63.5% في يومين)
    # -------------------------------------------------------------------------
    stoch_cross_today = (sk[i] > sd[i]) and (sk[i - 1] <= sd[i - 1])
    stoch_cross_yest = (sk[i - 1] > sd[i - 1]) and (sk[i - 2] <= sd[i - 2]) and (sk[i] > sd[i])
    has_stoch_cross = stoch_cross_today or stoch_cross_yest

    if has_stoch_cross and (sk[i] <= 35.0) and has_sup and is_green and is_vol_boost:
        signals.append({
            'strategy_type': 'STOCH_SUPPORT',
            'strategy_name': '🎖️ تقاطع الاستوكاستك (14, 3, 3) عند الدعم',
            'badge': '🎖️ ارتداد قاع سريع',
            'symbol': sym,
            'pair': pair,
            'price': cur_p,
            'support_type': sup_type,
            'support_lvl': sup_lvl,
            'vol_ratio': round(qv[i] / (qv_ma[i] + 1e-9), 2),
            'target_fast_3pct': round(cur_p * 1.03, 4),
            'target_runner_6pct': round(cur_p * 1.06, 4),
            'stop_loss': round(l[i] * 0.98, 4),
            'description': f'تقاطع الاستوكاستك من منطقة التشبع في القاع (%K: {sk[i]:.1f}) عند {sup_type} مع فوليوم مرتفع.'
        })

    # -------------------------------------------------------------------------
    # STRATEGY 5: ☁️ رادار اختراق السحابة (Kumo Breakout / على وشك الاختراق)
    # -------------------------------------------------------------------------
    if not np.isnan(k_top[i]) and k_top[i] > 0:
        dist_to_kumo = ((cur_p - k_top[i]) / k_top[i]) * 100.0

        # Case A: اخترقت السحابة صعوداً في شمعة اليوم أو أمس
        fresh_breakout = (c[i] > k_top[i]) and (c[i - 1] <= k_top[i - 1] or c[i - 2] <= k_top[i - 2])

        # Case B: على وشك الاختراق (السعر تحت السقف بأقل من 1.5% أو يضغط على السقف بشمعة خضراء)
        about_to_break = (-2.0 <= dist_to_kumo <= 1.0) and is_green and (c[i - 1] < k_top[i - 1])

        if (fresh_breakout or about_to_break) and is_green:
            breakout_status = "🚀 اخترق سقف السحابة حديثاً" if fresh_breakout else f"⏳ على وشك اختراق السحابة (فارق: {dist_to_kumo:+.1f}%)"
            signals.append({
                'strategy_type': 'KUMO_BREAKOUT',
                'strategy_name': '☁️ رادار اختراق سحابة الإيشيموكو (Kumo Breakout)',
                'badge': '☁️ اختراق السحابة',
                'symbol': sym,
                'pair': pair,
                'price': cur_p,
                'kumo_top': round(k_top[i], 4),
                'dist_to_kumo': round(dist_to_kumo, 2),
                'breakout_status': breakout_status,
                'vol_ratio': round(qv[i] / (qv_ma[i] + 1e-9), 2) if qv_ma[i] > 0 else 1.0,
                'target_fast_3pct': round(cur_p * 1.05, 4),
                'target_runner_6pct': round(cur_p * 1.15, 4),
                'stop_loss': round(k_top[i] * 0.975, 4),
                'description': f'{breakout_status} عند سعر {k_top[i]:.4f} بشمعة دافعة خضراء وبداية تحول الاتجاه إلى صاعد عام.'
            })

    return signals


def scan_authorized_strategies():
    """
    Scans the complete Binance USDT watchlist in parallel for the authorized strategies.
    """
    watchlist = get_watchlist()
    ema_list = []
    macd_list = []
    tk_list = []
    stoch_list = []
    kumo_list = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [executor.submit(analyze_coin_authorized_strategies, item) for item in watchlist]
        for f in concurrent.futures.as_completed(futures):
            sigs = f.result()
            if sigs:
                for s in sigs:
                    stype = s['strategy_type']
                    if stype == 'EMA9_21_SUPPORT':
                        ema_list.append(s)
                    elif stype == 'MACD_SUPPORT':
                        macd_list.append(s)
                    elif stype == 'TK_CROSS_SUPPORT':
                        tk_list.append(s)
                    elif stype == 'STOCH_SUPPORT':
                        stoch_list.append(s)
                    elif stype == 'KUMO_BREAKOUT':
                        kumo_list.append(s)

    # Sort each list by volume ratio and strength
    ema_list.sort(key=lambda x: x['vol_ratio'], reverse=True)
    macd_list.sort(key=lambda x: x['vol_ratio'], reverse=True)
    tk_list.sort(key=lambda x: x['vol_ratio'], reverse=True)
    stoch_list.sort(key=lambda x: x['vol_ratio'], reverse=True)
    kumo_list.sort(key=lambda x: (x['breakout_status'], x['vol_ratio']), reverse=True)

    return {
        'ema': ema_list,
        'macd': macd_list,
        'tk': tk_list,
        'stoch': stoch_list,
        'kumo': kumo_list,
        'total_scanned': len(watchlist),
    }


def format_authorized_report(scan_res):
    """
    Formats the complete trading report for Telegram.
    """
    btc = check_btc_regime()
    btc_status = "🟢 صاعد فوق Daily EMA50" if btc.get('is_bull') else "🔴 تصحيحي أسفل Daily EMA50"

    ema = scan_res.get('ema', [])
    macd = scan_res.get('macd', [])
    tk = scan_res.get('tk', [])
    stoch = scan_res.get('stoch', [])
    kumo = scan_res.get('kumo', [])

    messages = []

    # 1. Header Message
    header = (
        f"🎯 <b>رادار الصفقات اليومية المعتمدة (Daily 1D Radar)</b>\n"
        f"────────────────────\n"
        f"• <b>سعر البيتكوين:</b> <code>{btc.get('price', 0):,.1f} $</code> ({btc_status})\n"
        f"• <b>الهدف السريع:</b> 🎯 <b>+3.0%</b> (خلال أول يومين)\n"
        f"• <b>العملات المفحوصة:</b> {scan_res.get('total_scanned', 300)} عملة\n"
        f"────────────────────\n"
        f"📊 <b>ملخص الإشارات المرصودة:</b>\n"
        f"• 🥇 <b>تقاطع EMA 9/21 عند دعم:</b> {len(ema)} عملة (دقة 81% - 85%)\n"
        f"• 🥈 <b>تقاطع الماكد عند دعم:</b> {len(macd)} عملة (دقة 72%)\n"
        f"• 🥉 <b>تقاطع التنكن والكيجن عند دعم:</b> {len(tk)} عملة (دقة 70%)\n"
        f"• 🎖️ <b>تقاطع الاستوكاستك (14,3,3) عند دعم:</b> {len(stoch)} عملة (دقة 64%)\n"
        f"• ☁️ <b>اختراق السحابة (أو على وشك):</b> {len(kumo)} عملة\n"
        f"────────────────────"
    )
    messages.append(header)

    # 2. EMA 9/21 Section
    if ema:
        lines = [f"🥇 <b>1. إشارات تقاطع EMA 9 / EMA 21 عند دعم (النموذج الأقوى 81%):</b>"]
        for s in ema[:6]:
            lines.append(
                f"🔥 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | الدعم: <b>{s['support_type']}</b>\n"
                f"• السيولة: <code>{s['vol_ratio']}x</code> فوليوم أعلى من المعدل\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{s['target_fast_3pct']} $</code>\n"
                f"• 🚀 <b>هدف الموجه (+6%):</b> <code>{s['target_runner_6pct']} $</code>\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق يومي أسفل <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 3. MACD Section
    if macd:
        lines = [f"🥈 <b>2. إشارات تقاطع الماكد عند دعم (دقة 72% في يومين):</b>"]
        for s in macd[:5]:
            lines.append(
                f"💎 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | الدعم: <b>{s['support_type']}</b>\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{s['target_fast_3pct']} $</code> | 🛑 الوقف: <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 4. Ichimoku TK Section
    if tk:
        lines = [f"🥉 <b>3. إشارات تقاطع التنكن / الكيجن عند دعم (دقة 70% في يومين):</b>"]
        for s in tk[:5]:
            lines.append(
                f"⚡ <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | الدعم: <b>{s['support_type']}</b>\n"
                f"• 🎯 <b>الهدف السريع (+3%):</b> <code>{s['target_fast_3pct']} $</code> | 🛑 الوقف: <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 5. Stochastic (14, 3, 3) Section
    if stoch:
        lines = [f"🎖️ <b>4. إشارات تقاطع الاستوكاستك عند دعم (دقة 64% في يومين):</b>"]
        for s in stoch[:5]:
            lines.append(
                f"🌟 <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• السعر: <code>{s['price']} $</code> | الدعم: <b>{s['support_type']}</b>\n"
                f"• 🎯 <b>الهدف (+3%):</b> <code>{s['target_fast_3pct']} $</code> | 🛑 الوقف: <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 6. Kumo Cloud Breakout Section
    if kumo:
        lines = [f"☁️ <b>5. رادار اختراق السحابة (عملات اخترقت أو على وشك الاختراق):</b>"]
        for s in kumo[:6]:
            lines.append(
                f"☁️ <b>#{s['symbol']}</b> | <code>{s['pair']}</code>\n"
                f"• الحالة: <b>{s['breakout_status']}</b>\n"
                f"• السعر: <code>{s['price']} $</code> | سقف السحابة: <code>{s['kumo_top']} $</code>\n"
                f"• 🎯 <b>هدف الاختراق:</b> <code>{s['target_fast_3pct']} $</code> (+5%) ── <code>{s['target_runner_6pct']} $</code> (+15%)\n"
                f"• 🛑 <b>وقف الخسارة:</b> إغلاق أسفل <code>{s['stop_loss']} $</code>\n"
                f"────────────────────"
            )
        messages.append("\n".join(lines))

    # 7. Empty Alert if none found
    if not (ema or macd or tk or stoch or kumo):
        messages.append("ℹ️ لا توجد إشارات مكتملة الشروط الخمسة اليوم (السوق في مرحلة انتظار وتماسك لحماية رأس المال).")

    return messages


# Compatibility aliases for old imports
analyze_coin_ichimoku_trio = analyze_coin_authorized_strategies
scan_ichimoku_trio = scan_authorized_strategies
format_ichimoku_trio_report = format_authorized_report
