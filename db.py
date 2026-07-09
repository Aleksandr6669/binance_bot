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
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        gemini_api_key TEXT,
        binance_api_key TEXT,
        binance_api_secret TEXT,
        telegram_chat_id TEXT,
        telegram_bot_token TEXT,
        demo_balance REAL DEFAULT 10000.0
    )
    """)
    
    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER PRIMARY KEY,
        trading_pair TEXT DEFAULT 'BTCUSDT',
        timeframe TEXT DEFAULT '15m',
        order_size_usdt REAL DEFAULT 100.0,
        bot_enabled INTEGER DEFAULT 0,
        trading_mode TEXT DEFAULT 'DEMO',
        market_type TEXT DEFAULT 'SPOT',
        futures_leverage INTEGER DEFAULT 10,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pair TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        amount REAL NOT NULL,
        size_usdt REAL NOT NULL,
        leverage INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, CLOSED_TP, CLOSED_SL, CLOSED_MANUAL
        pnl REAL DEFAULT 0.0,
        trading_mode TEXT DEFAULT 'DEMO',
        market_type TEXT DEFAULT 'SPOT',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # Analysis Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS analysis_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pair TEXT NOT NULL,
        indicators_summary TEXT,
        stage1_output TEXT,
        stage2_output TEXT,
        stage3_output TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # Dynamic migration to add telegram_bot_token if it doesn't exist in existing database
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN telegram_bot_token TEXT")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add trading_mode if it doesn't exist in existing database
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN trading_mode TEXT DEFAULT 'DEMO'")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add trading_mode to orders table
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN trading_mode TEXT DEFAULT 'DEMO'")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration for UI settings
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN ui_language TEXT DEFAULT 'RU'")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN ui_auto_center INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add market_type to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN market_type TEXT DEFAULT 'SPOT'")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add futures_leverage to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN futures_leverage INTEGER DEFAULT 10")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add market_type to orders table
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN market_type TEXT DEFAULT 'SPOT'")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add leverage to orders table
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN leverage INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add min_probability_threshold to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN min_probability_threshold REAL DEFAULT 0.88")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add bot start timestamp to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN bot_started_at TEXT")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add invert signal flag to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN invert_signal INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add use_limit_orders flag to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN use_limit_orders INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migration to add use_trailing_stop flag to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN use_trailing_stop INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add use_ai_limit_price flag to settings table
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN use_ai_limit_price INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Dynamic migration to add trailing_distance to orders table
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN trailing_distance REAL")
    except sqlite3.OperationalError:
        pass
        
    # Dynamic migrations for trailing configuration in settings
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN trailing_activation_pct REAL DEFAULT 0.5")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN trailing_step_pct REAL DEFAULT 0.2")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN use_ai_exit INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN use_ai_trailing INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN telegram_notifications INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Table to store real market candlesticks for dynamic training (self-learning)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_history (
        pair TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        open_time INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        PRIMARY KEY(pair, timeframe, open_time)
    )
    """)
    
    conn.commit()
    conn.close()

# --- Market History Helpers (Self-Learning) ---

def save_market_candle(pair, timeframe, open_time, o, h, l, c, v):
    conn = get_db_connection()
    conn.execute(
        """INSERT OR REPLACE INTO market_history (pair, timeframe, open_time, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (pair.upper(), timeframe, open_time, float(o), float(h), float(l), float(c), float(v))
    )
    conn.commit()
    conn.close()

def get_market_history(pair, timeframe, limit=3000):
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT * FROM market_history 
           WHERE pair = ? AND timeframe = ? 
           ORDER BY open_time DESC LIMIT ?""",
        (pair.upper(), timeframe, limit)
    )
    results = rows.fetchall()
    conn.close()
    # Reverse so it's in chronological order
    results.reverse()
    return results

# --- User Helpers ---

def register_user(username, password_hash):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        user_id = cursor.lastrowid
        # Initialize default settings for user
        cursor.execute(
            "INSERT INTO settings (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()
        upload_db_to_hf_async()
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_username(username):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user

def update_user_api_keys(user_id, gemini_api_key, binance_api_key, binance_api_secret, telegram_chat_id, telegram_bot_token):
    conn = get_db_connection()
    conn.execute(
        """UPDATE users 
           SET gemini_api_key = ?, binance_api_key = ?, binance_api_secret = ?, telegram_chat_id = ?, telegram_bot_token = ? 
           WHERE id = ?""",
         (gemini_api_key, binance_api_key, binance_api_secret, telegram_chat_id, telegram_bot_token, user_id)
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def update_user_demo_balance(user_id, balance):
    conn = get_db_connection()
    conn.execute("UPDATE users SET demo_balance = ? WHERE id = ?", (balance, user_id))
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

# --- Settings Helpers ---

def save_ui_settings(user_id, ui_language, ui_auto_center):
    conn = get_db_connection()
    ui_auto_center = 1 if bool(ui_auto_center) else 0
    # Update UI settings, if row doesn't exist, it won't do anything (row created on registration)
    conn.execute(
        "UPDATE settings SET ui_language = ?, ui_auto_center = ? WHERE user_id = ?",
        (ui_language, ui_auto_center, user_id)
    )
    conn.commit()
    conn.close()

def get_user_settings(user_id):
    conn = get_db_connection()
    settings = conn.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return settings

def save_user_settings(user_id, trading_pair, timeframe, order_size_usdt, bot_enabled, trading_mode, market_type="SPOT", futures_leverage=10, min_probability_threshold=0.88, invert_signal=0, bot_started_at=None, use_limit_orders=1, use_trailing_stop=1, use_ai_limit_price=0, trailing_activation_pct=0.5, trailing_step_pct=0.2, use_ai_exit=0, use_ai_trailing=0):
    conn = get_db_connection()
    futures_leverage = max(1, min(125, int(futures_leverage)))  # clamp 1-125
    invert_signal = 1 if bool(invert_signal) else 0
    use_limit_orders = 1 if bool(use_limit_orders) else 0
    use_trailing_stop = 1 if bool(use_trailing_stop) else 0
    use_ai_limit_price = 1 if bool(use_ai_limit_price) else 0
    use_ai_exit = 1 if bool(use_ai_exit) else 0
    use_ai_trailing = 1 if bool(use_ai_trailing) else 0
    trailing_activation_pct = float(trailing_activation_pct)
    trailing_step_pct = float(trailing_step_pct)
    conn.execute(
        """INSERT INTO settings (user_id, trading_pair, timeframe, order_size_usdt, bot_enabled, trading_mode, market_type, futures_leverage, min_probability_threshold, invert_signal, bot_started_at, use_limit_orders, use_trailing_stop, use_ai_limit_price, trailing_activation_pct, trailing_step_pct, use_ai_exit, use_ai_trailing)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             trading_pair = excluded.trading_pair,
             timeframe = excluded.timeframe,
             order_size_usdt = excluded.order_size_usdt,
             bot_enabled = excluded.bot_enabled,
             trading_mode = excluded.trading_mode,
             market_type = excluded.market_type,
             futures_leverage = excluded.futures_leverage,
             min_probability_threshold = excluded.min_probability_threshold,
             invert_signal = excluded.invert_signal,
             bot_started_at = excluded.bot_started_at,
             use_limit_orders = excluded.use_limit_orders,
             use_trailing_stop = excluded.use_trailing_stop,
             use_ai_limit_price = excluded.use_ai_limit_price,
             trailing_activation_pct = excluded.trailing_activation_pct,
             trailing_step_pct = excluded.trailing_step_pct,
             use_ai_exit = excluded.use_ai_exit,
             use_ai_trailing = excluded.use_ai_trailing""",
        (user_id, trading_pair.upper(), timeframe, order_size_usdt, int(bot_enabled), trading_mode, market_type, futures_leverage, float(min_probability_threshold), invert_signal, bot_started_at, use_limit_orders, use_trailing_stop, use_ai_limit_price, trailing_activation_pct, trailing_step_pct, use_ai_exit, use_ai_trailing)
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def get_all_active_bot_settings():
    conn = get_db_connection()
    # Join with users to get keys and chat IDs
    rows = conn.execute(
        """SELECT s.*, u.gemini_api_key, u.binance_api_key, u.binance_api_secret, u.telegram_chat_id, u.telegram_bot_token, u.demo_balance 
           FROM settings s 
           JOIN users u ON s.user_id = u.id 
           WHERE s.bot_enabled = 1"""
    ).fetchall()
    conn.close()
    return rows

# --- Orders Helpers ---

def create_order(user_id, pair, side, entry_price, stop_loss, take_profit, amount, size_usdt, trading_mode="DEMO", market_type="SPOT", leverage=1, status="ACTIVE", trailing_distance=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO orders (user_id, pair, side, entry_price, stop_loss, take_profit, amount, size_usdt, status, trading_mode, market_type, leverage, trailing_distance) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, pair.upper(), side.upper(), float(entry_price), float(stop_loss) if stop_loss else None, float(take_profit) if take_profit else None, float(amount), float(size_usdt), status, trading_mode, market_type, leverage, float(trailing_distance) if trailing_distance else None)
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    upload_db_to_hf_async()
    return order_id

def get_active_orders(user_id=None):
    conn = get_db_connection()
    if user_id:
        rows = conn.execute("SELECT * FROM orders WHERE user_id = ? AND (status = 'ACTIVE' OR status = 'PENDING') ORDER BY created_at DESC", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders WHERE status = 'ACTIVE' OR status = 'PENDING'").fetchall()
    conn.close()
    return rows

def get_order_history(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? AND status NOT IN ('ACTIVE', 'PENDING') ORDER BY closed_at DESC", 
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_bot_pnl_since(user_id, since_timestamp):
    conn = get_db_connection()
    settings_row = conn.execute("SELECT trading_mode FROM settings WHERE user_id = ?", (user_id,)).fetchone()
    trading_mode = "DEMO"
    if settings_row and settings_row["trading_mode"]:
        trading_mode = settings_row["trading_mode"]
        
    row = conn.execute(
        "SELECT SUM(pnl) AS total FROM orders WHERE user_id = ? AND trading_mode = ? AND status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_MANUAL')",
        (user_id, trading_mode)
    ).fetchone()
    conn.close()
    return float(row["total"] or 0.0)


def clear_demo_orders(user_id):
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM orders WHERE user_id = ? AND trading_mode = 'DEMO'",
        (user_id,)
    )
    conn.commit()
    conn.close()
    upload_db_to_hf_async()

def activate_pending_order(order_id):
    conn = get_db_connection()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return False

        # Only activate if currently PENDING
        if (order["status"] or "").upper() != "PENDING":
            return False

        user_id = order["user_id"]
        trading_mode = order["trading_mode"] or "DEMO"

        # Списываем залог (коллатерал) при активации ордера — делаем проверку баланса
        if trading_mode == "DEMO":
            # Atomically deduct collateral only if sufficient balance remains,
            # then mark order ACTIVE. Use conditional UPDATEs to avoid TOCTOU races.
            cursor = conn.cursor()
            # Try to deduct collateral only when demo_balance >= size_usdt
            cursor.execute(
                "UPDATE users SET demo_balance = demo_balance - ? WHERE id = ? AND demo_balance >= ?",
                (order["size_usdt"], user_id, order["size_usdt"]) 
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False

            # Now activate the order only if still pending
            cursor.execute("UPDATE orders SET status = 'ACTIVE' WHERE id = ? AND status = 'PENDING'", (order_id,))
            if cursor.rowcount == 0:
                conn.rollback()
                return False

            conn.commit()
            return True
        else:
            # LIVE: simply flip status to ACTIVE if it is still PENDING
            cursor = conn.cursor()
            cursor.execute("UPDATE orders SET status = 'ACTIVE' WHERE id = ? AND status = 'PENDING'", (order_id,))
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            conn.commit()
            return True
    finally:
        conn.close()

def close_order(order_id, status, close_price, pnl):
    conn = get_db_connection()
    # Get the order details to update user's balance
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return False
        
    user_id = order["user_id"]
    trading_mode = order["trading_mode"] if "trading_mode" in order.keys() else "DEMO"
    
    # CRITICAL: Prevent double closing and double balance updates
    if (order["status"] or "").upper() not in ["ACTIVE", "PENDING"]:
        conn.close()
        return False
    
    # Update order
    conn.execute(
        """UPDATE orders 
           SET status = ?, pnl = ?, closed_at = CURRENT_TIMESTAMP 
           WHERE id = ?""",
        (status, pnl, order_id)
    )
    
    # Update user's demo balance ONLY if it was a DEMO order
    if trading_mode == "DEMO":
        conn.execute(
            "UPDATE users SET demo_balance = demo_balance + ? WHERE id = ?",
            (pnl, user_id)
        )
    
    conn.commit()
    conn.close()
    upload_db_to_hf_async()
    return True

def update_order_sl(order_id, new_stop_loss):
    conn = get_db_connection()
    conn.execute(
        "UPDATE orders SET stop_loss = ? WHERE id = ?",
        (float(new_stop_loss), order_id)
    )
    conn.commit()
    conn.close()
    return True

# --- Analysis Log Helpers ---

def add_analysis_log(user_id, pair, indicators_summary, stage1, stage2, stage3):
    conn = get_db_connection()
    conn.execute(
        """INSERT INTO analysis_logs (user_id, pair, indicators_summary, stage1_output, stage2_output, stage3_output)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, pair, indicators_summary, stage1, stage2, stage3)
    )
    conn.commit()
    conn.close()

def get_latest_analysis_log(user_id, pair):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM analysis_logs WHERE user_id = ? AND pair = ? ORDER BY created_at DESC LIMIT 1",
        (user_id, pair)
    ).fetchone()
    conn.close()
    return row

def get_all_analysis_logs(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM analysis_logs WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def should_persist_analysis_log(user_id, pair, stage3_output, min_interval_seconds=30):
    """
    Determines whether a new analysis log should be persisted.
    - If there is no previous log -> True
    - If the stage3_output differs from last -> True
    - If identical and last log is older than min_interval_seconds -> True
    - Otherwise -> False (skip writing duplicate logs)
    """
    from datetime import datetime
    latest = get_latest_analysis_log(user_id, pair)
    if not latest:
        return True

    # Compare stage3 text
    last_stage3 = latest["stage3_output"] or ""
    if last_stage3 != stage3_output:
        return True

    # If identical, check timestamp recency
    try:
        last_time = datetime.strptime(latest["created_at"], "%Y-%m-%d %H:%M:%S")
        now = datetime.utcnow()
        if (now - last_time).total_seconds() >= min_interval_seconds:
            return True
        return False
    except Exception:
        # If parsing fails conservatively persist
        return True


def add_analysis_log_if_needed(user_id, pair, indicators_summary, stage1, stage2, stage3, min_interval_seconds=30):
    """
    Adds an analysis log only when `should_persist_analysis_log` returns True.
    Returns True if a new record was inserted, False if skipped.
    """
    if should_persist_analysis_log(user_id, pair, stage3, min_interval_seconds=min_interval_seconds):
        add_analysis_log(user_id, pair, indicators_summary, stage1, stage2, stage3)
        return True
    return False

def update_user_settings(user_id, key, value):
    conn = get_db_connection()
    allowed_keys = ["bot_enabled", "trading_pair", "trading_mode", "use_limit_orders", "invert_signal", "timeframe", "telegram_notifications"]
    if key in allowed_keys:
        conn.execute(f"UPDATE settings SET {key} = ? WHERE user_id = ?", (value, user_id))
        conn.commit()
    conn.close()
    upload_db_to_hf_async()

def get_filtered_orders(user_id, pair=None, trading_mode=None, side=None, status=None, start_date=None, end_date=None):
    conn = get_db_connection()
    query = "SELECT * FROM orders WHERE user_id = ?"
    params = [user_id]
    
    if pair:
        query += " AND UPPER(pair) = ?"
        params.append(pair.upper())
    if trading_mode:
        query += " AND UPPER(trading_mode) = ?"
        params.append(trading_mode.upper())
    if side:
        query += " AND UPPER(side) = ?"
        params.append(side.upper())
    if status:
        query += " AND UPPER(status) = ?"
        params.append(status.upper())
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date + " 23:59:59")
        
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows

def get_filtered_analysis_logs(user_id, pair=None, start_date=None, end_date=None):
    conn = get_db_connection()
    query = "SELECT * FROM analysis_logs WHERE user_id = ?"
    params = [user_id]
    
    if pair:
        query += " AND UPPER(pair) = ?"
        params.append(pair.upper())
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date + " 23:59:59")
        
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows
