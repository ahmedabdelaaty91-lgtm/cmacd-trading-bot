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
    CREATE TABLE IF NOT EXISTS balance_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        total_balance REAL,
        cash REAL
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
    conn.commit()
    
    # Ensure newly added columns exist in older database files
    cur.execute("PRAGMA table_info(trades)")
    cols = [c[1] for c in cur.fetchall()]
    if 'tp2_price' not in cols:
        cur.execute("ALTER TABLE trades ADD COLUMN tp2_price REAL")
    if 'initial_quantity' not in cols:
        cur.execute("ALTER TABLE trades ADD COLUMN initial_quantity REAL")
    if 'remaining_quantity' not in cols:
        cur.execute("ALTER TABLE trades ADD COLUMN remaining_quantity REAL")
    conn.commit()
    conn.close()

def add_trade(symbol, pair, entry_price, quantity, tp1_price, tp2_price, sl_price):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT INTO trades (
        symbol, pair, entry_price, current_price, quantity, initial_quantity, remaining_quantity, 
        entry_date, status, tp1_price, tp2_price, sl_price
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
    """, (symbol, pair, entry_price, entry_price, quantity, quantity, quantity, now_str, tp1_price, tp2_price, sl_price))
    conn.commit()
    conn.close()

def get_open_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE status IN ('OPEN', 'TP1_HIT', 'TP2_HIT')")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_tp1_hit(trade_id, remaining_qty, new_sl_price):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    UPDATE trades 
    SET status = 'TP1_HIT', remaining_quantity = ?, sl_price = ?
    WHERE id = ?
    """, (remaining_qty, new_sl_price, trade_id))
    conn.commit()
    conn.close()

def update_tp2_hit(trade_id, remaining_qty, new_sl_price):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    UPDATE trades 
    SET status = 'TP2_HIT', remaining_quantity = ?, sl_price = ?
    WHERE id = ?
    """, (remaining_qty, new_sl_price, trade_id))
    conn.commit()
    conn.close()

def close_trade(trade_id, exit_price, pnl_pct, reason):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    UPDATE trades 
    SET status = 'CLOSED', remaining_quantity = 0, exit_price = ?, exit_date = ?, pnl_pct = ?, exit_reason = ?
    WHERE id = ?
    """, (exit_price, now_str, pnl_pct, reason, trade_id))
    conn.commit()
    conn.close()

def get_closed_trades(limit=10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

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

# Initialize tables
init_db()
