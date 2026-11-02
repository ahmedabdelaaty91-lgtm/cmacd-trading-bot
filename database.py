import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        pair TEXT,
        entry_price REAL,
        current_price REAL,
        quantity REAL,
        initial_quantity REAL,
        remaining_quantity REAL,
        entry_date TEXT,
        status TEXT, -- 'OPEN', 'TP1_HIT', 'TP2_HIT', 'CLOSED'
        tp1_price REAL,
        tp2_price REAL,
        sl_price REAL,
        exit_price REAL,
        exit_date TEXT,
        pnl_pct REAL,
        exit_reason TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        pair TEXT,
        alert_date TEXT,
        tier INTEGER,
        price REAL,
        details TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS signal_states (
        pair TEXT PRIMARY KEY,
        symbol TEXT,
        date_str TEXT,
        strategy_name TEXT,
        tier_badge TEXT,
        price REAL,
        tp_price REAL,
        sl_price REAL,
        be_price REAL,
        tp_pct REAL,
        sl_pct REAL,
        be_pct REAL,
        mtf_confirmed INTEGER,
        mtf_notified INTEGER,
        last_updated TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_signal_state(pair, date_str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM signal_states WHERE pair = ? AND date_str = ?", (pair, date_str))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def save_or_update_signal_state(pair, symbol, date_str, sig, mtf_notified=0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT INTO signal_states (
        pair, symbol, date_str, strategy_name, tier_badge, price,
        tp_price, sl_price, be_price, tp_pct, sl_pct, be_pct,
        mtf_confirmed, mtf_notified, last_updated
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(pair) DO UPDATE SET
        date_str = excluded.date_str,
        strategy_name = excluded.strategy_name,
        tier_badge = excluded.tier_badge,
        price = excluded.price,
        tp_price = excluded.tp_price,
        sl_price = excluded.sl_price,
        be_price = excluded.be_price,
        tp_pct = excluded.tp_pct,
        sl_pct = excluded.sl_pct,
        be_pct = excluded.be_pct,
        mtf_confirmed = excluded.mtf_confirmed,
        mtf_notified = CASE WHEN excluded.mtf_notified = 1 THEN 1 ELSE signal_states.mtf_notified END,
        last_updated = excluded.last_updated
    """, (
        pair, symbol, date_str, sig['strategy_name'], sig['tier_badge'], sig['current_price'],
        sig['tp_price'], sig['sl_price'], sig['be_price'], sig['tp_pct'], sig['sl_pct'], sig['be_pct'],
        1 if sig.get('mtf_confirmed') else 0, mtf_notified, now_str
    ))
    conn.commit()
    conn.close()

def mark_mtf_notified(pair, date_str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE signal_states SET mtf_confirmed = 1, mtf_notified = 1 WHERE pair = ? AND date_str = ?", (pair, date_str))
    conn.commit()
    conn.close()

def clean_old_signal_states(current_date_str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM signal_states WHERE date_str != ?", (current_date_str,))
    conn.commit()
    conn.close()

def was_alerted_today(symbol, date_str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM alerts WHERE symbol = ? AND alert_date = ?", (symbol, date_str))
    res = cur.fetchone()
    conn.close()
    return res is not None

def record_alert(symbol, pair, date_str, tier, price, details):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO alerts (symbol, pair, alert_date, tier, price, details)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (symbol, pair, date_str, tier, price, details))
    conn.commit()
    conn.close()

init_db()
