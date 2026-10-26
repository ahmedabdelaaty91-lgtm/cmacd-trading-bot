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
        entry_date TEXT,
        status TEXT, -- 'OPEN', 'TP1_HIT', 'CLOSED'
        tp1_price REAL,
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
    conn.commit()
    conn.close()

def add_trade(symbol, pair, entry_price, quantity, tp1_price, sl_price):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT INTO trades (symbol, pair, entry_price, current_price, quantity, entry_date, status, tp1_price, sl_price)
    VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
    """, (symbol, pair, entry_price, entry_price, quantity, now_str, tp1_price, sl_price))
    conn.commit()
    conn.close()

def get_open_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE status IN ('OPEN', 'TP1_HIT')")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_tp1_hit(trade_id, new_sl_price):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    UPDATE trades 
    SET status = 'TP1_HIT', sl_price = ?
    WHERE id = ?
    """, (new_sl_price, trade_id))
    conn.commit()
    conn.close()

def close_trade(trade_id, exit_price, pnl_pct, reason):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    UPDATE trades 
    SET status = 'CLOSED', exit_price = ?, exit_date = ?, pnl_pct = ?, exit_reason = ?
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

# Initialize tables
init_db()
