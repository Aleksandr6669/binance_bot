import sqlite3
import os
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_bot.db")

def download_db_from_hf():
    return False

def upload_db_to_hf():
    return False

def upload_db_to_hf_async():
    pass

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    download_db_from_hf()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Settings table (now holds everything including API keys and balance)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        gemini_api_key TEXT,
        binance_api_key TEXT,
        binance_api_secret TEXT,
        telegram_chat_id TEXT,
        telegram_bot_token TEXT,
        demo_balance REAL DEFAULT 10000.0,
        trading_pair TEXT DEFAULT 'BTCUSDT',
        timeframe TEXT DEFAULT '15m',
        order_size_usdt REAL DEFAULT 100.0,
        bot_enabled INTEGER DEFAULT 0,
        trading_mode TEXT DEFAULT 'DEMO',
        market_type TEXT DEFAULT 'SPOT',
        futures_leverage INTEGER DEFAULT 10,
        ui_language TEXT DEFAULT 'RU',
        ui_auto_center INTEGER DEFAULT 1,
        min_probability_threshold REAL DEFAULT 0.65,
        bot_started_at TEXT,
        invert_signal INTEGER DEFAULT 0,
        use_limit_orders INTEGER DEFAULT 1,
        use_trailing_stop INTEGER DEFAULT 1,
        use_ai_limit_price INTEGER DEFAULT 0,
        trailing_activation_pct REAL DEFAULT 0.5,
        trailing_step_pct REAL DEFAULT 0.2,
        use_ai_trailing INTEGER DEFAULT 0,
        use_ai_exit INTEGER DEFAULT 0,
        daily_loss_limit REAL DEFAULT 0.0,
        daily_profit_target REAL DEFAULT 0.0
    )
    ''')
    # Add columns if they don't exist (for older databases)
    migrations = [
        "ALTER TABLE settings ADD COLUMN daily_loss_limit REAL DEFAULT 0.0",
        "ALTER TABLE settings ADD COLUMN daily_profit_target REAL DEFAULT 0.0",
        "ALTER TABLE settings ADD COLUMN use_ai_exit INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN use_ai_trailing INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN use_ai_limit_price INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN trailing_activation_pct REAL DEFAULT 0.5",
        "ALTER TABLE settings ADD COLUMN trailing_step_pct REAL DEFAULT 0.2",
        "ALTER TABLE settings ADD COLUMN invert_signal INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN use_limit_orders INTEGER DEFAULT 1",
        "ALTER TABLE settings ADD COLUMN use_trailing_stop INTEGER DEFAULT 1",
        "ALTER TABLE settings ADD COLUMN min_probability_threshold REAL DEFAULT 0.88",
        "ALTER TABLE settings ADD COLUMN market_type TEXT DEFAULT 'SPOT'",
        "ALTER TABLE settings ADD COLUMN futures_leverage INTEGER DEFAULT 10",
        "ALTER TABLE settings ADD COLUMN use_proxy INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN proxy_url TEXT",
        "ALTER TABLE orders ADD COLUMN user_id INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN trailing_distance REAL",
        "ALTER TABLE orders ADD COLUMN leverage INTEGER DEFAULT 1",
        "ALTER TABLE orders ADD COLUMN market_type TEXT DEFAULT 'SPOT'",
        "ALTER TABLE orders ADD COLUMN trading_mode TEXT DEFAULT 'DEMO'",
        "ALTER TABLE orders ADD COLUMN timeframe TEXT",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except Exception:
            pass  # Column already exists

    # Market candles table for model retraining
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS market_candles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        open_time INTEGER UNIQUE,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Insert default settings row if it doesn't exist
    cursor.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
    
    # Orders table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 0,
        pair TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        amount REAL NOT NULL,
        size_usdt REAL NOT NULL,
        leverage INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        pnl REAL DEFAULT 0.0,
        close_price REAL,
        trading_mode TEXT DEFAULT 'DEMO',
        market_type TEXT DEFAULT 'SPOT',
        trailing_distance REAL,
        timeframe TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMP
    )
    ''')
    
    # Analysis Logs table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT NOT NULL,
        indicators_summary TEXT,
        stage1_output TEXT,
        stage2_output TEXT,
        stage3_output TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Symbol Cache table to persist downloaded Binance trading pairs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS symbol_cache (
        market_type TEXT PRIMARY KEY,
        symbols_json TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Migration: check if close_price exists in orders table
    try:
        cursor.execute("SELECT close_price FROM orders LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE orders ADD COLUMN close_price REAL")
        
    conn.commit()
    conn.close()

def update_api_keys(gemini_api_key, binance_api_key, binance_api_secret, use_proxy, proxy_url):
    conn = get_db_connection()
    conn.execute(
        '''UPDATE settings 
           SET gemini_api_key = ?, binance_api_key = ?, binance_api_secret = ?, use_proxy = ?, proxy_url = ? 
           WHERE id = 1''',
         (gemini_api_key, binance_api_key, binance_api_secret, int(use_proxy), proxy_url)
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def update_demo_balance(balance):
    conn = get_db_connection()
    conn.execute("UPDATE settings SET demo_balance = ? WHERE id = 1", (balance,))
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def save_ui_settings(ui_language, ui_auto_center):
    conn = get_db_connection()
    conn.execute(
        "UPDATE settings SET ui_language = ?, ui_auto_center = ? WHERE id = 1",
        (ui_language, ui_auto_center)
    )
    conn.commit()
    conn.close()

def get_settings():
    conn = get_db_connection()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    return dict(settings) if settings else None

def save_settings(trading_pair, timeframe, order_size_usdt, bot_enabled, trading_mode, market_type="SPOT", futures_leverage=10, min_probability_threshold=0.88, invert_signal=0, bot_started_at=None, use_limit_orders=1, use_trailing_stop=1, use_ai_limit_price=0, trailing_activation_pct=0.5, trailing_step_pct=0.2, use_ai_exit=0, use_ai_trailing=0, daily_loss_limit=0.0, daily_profit_target=0.0):
    conn = get_db_connection()
    conn.execute(
        '''UPDATE settings SET trading_pair = ?, timeframe = ?, order_size_usdt = ?, bot_enabled = ?, trading_mode = ?, market_type = ?, futures_leverage = ?, min_probability_threshold = ?, invert_signal = ?, bot_started_at = ?, use_limit_orders = ?, use_trailing_stop = ?, use_ai_limit_price = ?, trailing_activation_pct = ?, trailing_step_pct = ?, use_ai_exit = ?, use_ai_trailing = ?, daily_loss_limit = ?, daily_profit_target = ? WHERE id = 1''',
        (trading_pair.upper(), timeframe, order_size_usdt, int(bot_enabled), trading_mode, market_type, futures_leverage, float(min_probability_threshold), invert_signal, bot_started_at, use_limit_orders, use_trailing_stop, use_ai_limit_price, trailing_activation_pct, trailing_step_pct, use_ai_exit, use_ai_trailing, float(daily_loss_limit), float(daily_profit_target))
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def get_all_active_bot_settings():
    s = get_settings()
    if s and s.get("bot_enabled"):
        return [(1, s)]
    return []

def create_order(pair, side, entry_price, stop_loss, take_profit, amount, size_usdt, trading_mode="DEMO", market_type="SPOT", leverage=1, status="ACTIVE", trailing_distance=None, timeframe=None):
    conn = get_db_connection()
    conn.execute(
        '''INSERT INTO orders (pair, side, entry_price, stop_loss, take_profit, amount, size_usdt, status, trading_mode, market_type, leverage, trailing_distance, timeframe) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (pair.upper(), side.upper(), float(entry_price), float(stop_loss) if stop_loss else None, float(take_profit) if take_profit else None, float(amount), float(size_usdt), status, trading_mode, market_type, leverage, float(trailing_distance) if trailing_distance else None, timeframe)
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def get_active_orders():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM orders WHERE (status = 'ACTIVE' OR status = 'PENDING') ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_order_history():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status NOT IN ('ACTIVE', 'PENDING') ORDER BY closed_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_bot_pnl_since(since_timestamp):
    conn = get_db_connection()
    settings_row = conn.execute("SELECT trading_mode FROM settings WHERE id = 1").fetchone()
    if not settings_row:
        conn.close()
        return 0.0
    trading_mode = settings_row["trading_mode"]
    row = conn.execute(
        "SELECT SUM(pnl) AS total FROM orders WHERE trading_mode = ? AND status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_MANUAL')",
        (trading_mode,)
    ).fetchone()
    conn.close()
    return row["total"] if row["total"] else 0.0

def clear_demo_orders():
    conn = get_db_connection()
    conn.execute("DELETE FROM orders WHERE trading_mode = 'DEMO'")
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def delete_order(order_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def activate_pending_order(order_id):
    conn = get_db_connection()
    conn.execute("UPDATE orders SET status = 'ACTIVE' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def save_market_candle(pair, timeframe, open_time, open_p, high, low, close, volume):
    """Save a market candle for model retraining history."""
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT OR IGNORE INTO market_candles (pair, timeframe, open_time, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (pair.upper(), timeframe, int(open_time), float(open_p), float(high), float(low), float(close), float(volume))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        pass  # Non-critical, don't break the main cycle

def close_order(order_id, status=None, close_price=None, pnl=None):
    conn = get_db_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return False
    
    # Default status if not provided
    _status = status or "CLOSED_MANUAL"
    _pnl = pnl if pnl is not None else 0.0
    _close_price = close_price if close_price is not None else None
    
    import datetime as _dt
    conn.execute(
        "UPDATE orders SET status = ?, pnl = ?, close_price = ?, closed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (_status, _pnl, _close_price, order_id)
    )
    
    # Only auto-update demo balance if pnl is explicitly provided (avoid double-counting)
    if pnl is not None and order["trading_mode"] == "DEMO":
        user_row = conn.execute("SELECT demo_balance FROM settings WHERE id = 1").fetchone()
        if user_row:
            new_balance = user_row["demo_balance"] + _pnl
            conn.execute("UPDATE settings SET demo_balance = ? WHERE id = 1", (new_balance,))
            
    conn.commit()
    conn.close()
    upload_db_to_hf_async()
    return True

def update_order_sl(order_id, new_stop_loss):
    conn = get_db_connection()
    conn.execute("UPDATE orders SET stop_loss = ? WHERE id = ?", (new_stop_loss, order_id))
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def add_analysis_log(pair, indicators_summary, stage1, stage2, stage3):
    conn = get_db_connection()
    conn.execute(
        '''INSERT INTO analysis_logs (pair, indicators_summary, stage1_output, stage2_output, stage3_output)
           VALUES (?, ?, ?, ?, ?)''',
        (pair, indicators_summary, stage1, stage2, stage3)
    )
    conn.commit()
    conn.close()

def get_latest_analysis_log(pair):
    conn = get_db_connection()
    log = conn.execute(
        "SELECT * FROM analysis_logs WHERE pair = ? ORDER BY created_at DESC LIMIT 1",
        (pair,)
    ).fetchone()
    conn.close()
    return dict(log) if log else None

def get_all_analysis_logs():
    conn = get_db_connection()
    logs = conn.execute(
        "SELECT * FROM analysis_logs ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(log) for log in logs]



def should_persist_analysis_log(pair, stage3_output, min_interval_seconds=30):
    import json
    from datetime import datetime
    latest = get_latest_analysis_log(pair)
    if not latest:
        return True
    
    try:
        latest_time = datetime.strptime(latest["created_at"], "%Y-%m-%d %H:%M:%S")
        if (datetime.utcnow() - latest_time).total_seconds() < min_interval_seconds:
            return False
    except Exception:
        pass
        
    try:
        latest_s3 = json.loads(latest["stage3_output"])
        new_s3 = json.loads(stage3_output)
        action_changed = latest_s3.get("action") != new_s3.get("action")
        
        if not action_changed:
            latest_time = datetime.strptime(latest["created_at"], "%Y-%m-%d %H:%M:%S")
            time_diff = (datetime.utcnow() - latest_time).total_seconds()
            if time_diff < 300:
                return False
    except Exception:
        pass
        
    return True

def add_analysis_log_if_needed(pair, indicators_summary, stage1, stage2, stage3, min_interval_seconds=30):
    if should_persist_analysis_log(pair, stage3, min_interval_seconds=min_interval_seconds):
        add_analysis_log(pair, indicators_summary, stage1, stage2, stage3)

def update_settings(key, value):
    conn = get_db_connection()
    try:
        conn.execute(f"UPDATE settings SET {key} = ? WHERE id = 1", (value,))
        conn.commit()
    except Exception as e:
        print(f"Error updating setting {key}: {e}")
    finally:
        conn.close()

def get_filtered_orders(pair=None, trading_mode=None, side=None, status=None, open_start=None, open_end=None, close_start=None, close_end=None, timeframe=None):
    """
    Все даты — локальные ('YYYY-MM-DD'). Конвертируем в UTC для сравнения с created_at/closed_at (UTC).
    """
    import datetime as _dt

    def local_date_to_utc(date_str, end_of_day=False):
        """Конвертирует локальную дату в UTC datetime строку."""
        try:
            local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
            d = _dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=local_tz)
            if end_of_day:
                d = d + _dt.timedelta(days=1)
            return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return date_str

    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    
    if pair:
        query += " AND pair = ?"
        params.append(pair)
    if timeframe:
        query += " AND timeframe = ?"
        params.append(timeframe)
    if trading_mode:
        query += " AND trading_mode = ?"
        params.append(trading_mode)
    if side:
        query += " AND side = ?"
        params.append(side)
    if status:
        query += " AND status = ?"
        params.append(status)
    if open_start:
        query += " AND created_at >= ?"
        params.append(local_date_to_utc(open_start, end_of_day=False))
    if open_end:
        query += " AND created_at < ?"
        params.append(local_date_to_utc(open_end, end_of_day=True))
    if close_start:
        query += " AND closed_at >= ?"
        params.append(local_date_to_utc(close_start, end_of_day=False))
    if close_end:
        query += " AND closed_at < ?"
        params.append(local_date_to_utc(close_end, end_of_day=True))
        
    query += " ORDER BY created_at DESC"
    
    conn = get_db_connection()
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_filtered_analysis_logs(pair=None, date=None, tz_offset_min=180):
    """
    date: локальная дата пользователя 'YYYY-MM-DD'.
    tz_offset_min: смещение часового пояса клиента в минутах от UTC (например 180 для UTC+3 MSK).
    Конвертирует локальную дату пользователя в точный UTC-диапазон для базы данных.
    """
    import datetime
    query = "SELECT * FROM analysis_logs WHERE 1=1"
    params = []
    
    if pair:
        query += " AND pair = ?"
        params.append(pair)
    if date:
        try:
            if tz_offset_min is not None:
                user_tz = datetime.timezone(datetime.timedelta(minutes=tz_offset_min))
            else:
                user_tz = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo or datetime.timezone.utc
            
            local_start = datetime.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=user_tz)
            local_end = local_start + datetime.timedelta(days=1)
            utc_start = local_start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            utc_end = local_end.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            query += " AND created_at >= ? AND created_at < ?"
            params.extend([utc_start, utc_end])
        except Exception:
            query += " AND date(created_at) = date(?)"
            params.append(date)
        
    query += " ORDER BY created_at DESC"
    
    conn = get_db_connection()
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_daily_pnl(trading_mode="DEMO"):
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT date(created_at) as day, SUM(pnl) as total_pnl 
        FROM orders 
        WHERE trading_mode = ? 
        GROUP BY day 
        ORDER BY day ASC
    ''', (trading_mode,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_cached_symbols(market_type, symbols):
    try:
        import json
        conn = get_db_connection()
        conn.execute(
            "INSERT OR REPLACE INTO symbol_cache (market_type, symbols_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (market_type.upper(), json.dumps(symbols))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving cached symbols to DB: {e}")

def get_cached_symbols(market_type):
    try:
        import json
        conn = get_db_connection()
        row = conn.execute(
            "SELECT symbols_json FROM symbol_cache WHERE market_type = ?",
            (market_type.upper(),)
        ).fetchone()
        conn.close()
        if row and row["symbols_json"]:
            return json.loads(row["symbols_json"])
    except Exception as e:
        print(f"Error reading cached symbols from DB: {e}")
    return None
