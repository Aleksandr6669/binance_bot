import os
import json
import time
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sock import Sock
import simple_websocket

import db
import indicators
import trading_engine
from translations import TRANSLATIONS

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secure-key-998877")
sock = Sock(app)

@app.context_processor
def inject_translation_helper():
    def translate(key, **kwargs):
        lang = session.get("lang", "en")
        if lang not in TRANSLATIONS:
            lang = "en"
        val = TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
        return val.format(**kwargs) if kwargs else val
    cur_lang = session.get("lang", "en")
    if cur_lang not in TRANSLATIONS:
        cur_lang = "en"
    return dict(_t=translate, current_lang=cur_lang)

import requests

def get_public_ip():
    """Определяет внешний публичный IP-адрес сервера для Binance whitelist."""
    try:
        res = requests.get("https://api.ipify.org?format=json", timeout=3)
        if res.status_code == 200:
            return res.json().get("ip", "Unknown")
    except Exception:
        pass
    try:
        res = requests.get("https://ifconfig.me/ip", timeout=3)
        if res.status_code == 200:
            return res.text.strip()
    except Exception:
        pass
    return "Unknown"

# --- Startup Hooks ---

def initialize_application():
    """Initializes the database and launches background loops."""
    # 1. Init Database
    db.init_db()
    
    # Note: starting background schedulers is done in the main process only
    # to avoid duplicate threads when the Flask reloader spawns a child process.

# --- Decorators / Auth Utilities ---

def get_current_user():
    if "user_id" not in session:
        return None
    return db.get_user_by_id(session["user_id"])

# --- Web Routes ---

@app.route("/set_lang/<lang>")
def set_lang(lang):
    if lang in ["en", "ru", "uk"]:
        session["lang"] = lang
        user = get_current_user()
        if user:
            settings = db.get_user_settings(user["id"])
            if settings:
                ui_auto_center = dict(settings).get("ui_auto_center", 1)
                db.save_ui_settings(user["id"], lang.upper(), ui_auto_center)
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")
            
        hashed_password = generate_password_hash(password)
        user_id = db.register_user(username, hashed_password)
        
        if user_id:
            flash("Registration successful! Please login below.", "success")
            return redirect(url_for("login"))
        else:
            flash("Username already exists. Please choose a different one.", "error")
            
    return render_template("register.html", active_page="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        user = db.get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            settings = db.get_user_settings(user["id"])
            if settings and dict(settings).get("ui_language"):
                session["lang"] = dict(settings).get("ui_language").lower()
            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")
            
    return render_template("login.html", active_page="login")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    settings = db.get_user_settings(user["id"])
    active_orders = db.get_active_orders(user["id"])
    history = db.get_order_history(user["id"])
    latest_log = db.get_latest_analysis_log(user["id"], settings["trading_pair"])
    
    logs_history = db.get_all_analysis_logs(user["id"])
    formatted_logs = []
    for l in logs_history[:30]:
        log_dict = dict(l)
        action = "HOLD"
        prob = 0.0
        reason = "No details"
        order_type = "None"
        try:
            import json
            s3 = json.loads(l["stage3_output"])
            action = s3.get("action", "HOLD")
            prob = s3.get("probability", 0.0)
            reason = s3.get("reason", "No details")
            order_type = s3.get("order_type", "None")
            if order_type == "None" and action != "HOLD":
                settings_dict = dict(db.get_user_settings(user["id"])) if user else {}
                use_limit = settings_dict.get("use_limit_orders", 1)
                order_type = "LIMIT" if use_limit else "MARKET"
        except Exception:
            pass
        log_dict["action"] = action
        log_dict["probability"] = prob
        log_dict["reason"] = reason
        log_dict["order_type"] = order_type
        formatted_logs.append(log_dict)
    
    trading_mode = settings["trading_mode"] or "DEMO"
    is_live = (trading_mode == "LIVE")
    market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
    futures_leverage = dict(settings).get("futures_leverage", 10) or 10
    
    display_balance = user["demo_balance"]
    balance_error = None
    
    if is_live:
        live_bal = trading_engine.fetch_binance_balance(user["id"], market_type)
        if live_bal is not None:
            # Fetch real positions and open orders from Binance
            live_positions = trading_engine.fetch_live_positions(user["id"], market_type)
            live_open_orders = trading_engine.fetch_live_open_orders(user["id"], market_type)
            
            # Fetch local pending virtual limit orders
            local_active = db.get_active_orders(user["id"])
            local_pending = [o for o in local_active if (o["trading_mode"] or "DEMO") == "LIVE" and o["status"] == "PENDING"]
            
            # Merge them as active orders to display
            active_orders = []
            unrealized_pnl = 0.0
            
            # Pre-fetch current prices for all relevant pairs to calculate PnL on backend
            active_pairs = {settings["trading_pair"].upper()}
            for pos in live_positions:
                active_pairs.add(pos["pair"].upper())
            for o in local_pending:
                active_pairs.add(o["pair"].upper())
            for ord_info in live_open_orders:
                active_pairs.add(ord_info["pair"].upper())
                
            current_prices = {}
            for p in active_pairs:
                try:
                    current_prices[p] = trading_engine.fetch_current_price(p, market_type)
                except Exception:
                    pass
            
            # 1. Real positions
            for pos in live_positions:
                # Calculate real-time PnL on backend using live price
                pos_pair = pos["pair"].upper()
                curr_price = current_prices.get(pos_pair)
                if curr_price:
                    if pos["side"] == "BUY":
                        pnl_val = (curr_price - pos["entry_price"]) * pos["amount"]
                    else:
                        pnl_val = (pos["entry_price"] - curr_price) * pos["amount"]
                else:
                    pnl_val = pos.get("unrealized_pnl", 0.0)
                    
                unrealized_pnl += pnl_val
                
                # Find matching local active order in DB to fetch SL/TP
                matching_local = None
                for lo in local_active:
                    if lo["pair"].upper() == pos["pair"].upper() and lo["status"] == "ACTIVE":
                        matching_local = lo
                        break
                
                sl_val = matching_local["stop_loss"] if matching_local else None
                tp_val = matching_local["take_profit"] if matching_local else None
                created_at_val = matching_local["created_at"] if matching_local else "N/A"
                
                active_orders.append({
                    "id": pos["id"],
                    "pair": pos["pair"],
                    "side": pos["side"],
                    "entry_price": pos["entry_price"],
                    "stop_loss": sl_val,
                    "take_profit": tp_val,
                    "amount": pos["amount"],
                    "size_usdt": pos["amount"] * pos["entry_price"],
                    "status": "ACTIVE",
                    "trading_mode": "LIVE",
                    "market_type": pos["market_type"],
                    "unrealized_pnl": pnl_val,
                    "created_at": created_at_val,
                    "leverage": pos.get("leverage", 10)
                })
                
            # 2. Local pending limit orders
            for o in local_pending:
                active_orders.append({
                    "id": o["id"],
                    "pair": o["pair"],
                    "side": o["side"],
                    "entry_price": o["entry_price"],
                    "stop_loss": o["stop_loss"],
                    "take_profit": o["take_profit"],
                    "amount": o["amount"],
                    "size_usdt": o["size_usdt"],
                    "status": "PENDING",
                    "trading_mode": "LIVE",
                    "market_type": dict(o).get("market_type", "SPOT") or "SPOT",
                    "unrealized_pnl": 0.0,
                    "created_at": o["created_at"],
                    "leverage": futures_leverage if (dict(o).get("market_type", "SPOT") or "SPOT") == "FUTURES" else 1
                })
                
            # 3. Real open limit orders on Binance
            for ord_info in live_open_orders:
                # Avoid duplicates if they happen to overlap
                if any(str(x["id"]) == str(ord_info["id"]) for x in active_orders):
                    continue
                active_orders.append({
                    "id": ord_info["id"],
                    "pair": ord_info["pair"],
                    "side": ord_info["side"],
                    "entry_price": ord_info["entry_price"],
                    "stop_loss": None,
                    "take_profit": None,
                    "amount": ord_info["amount"],
                    "size_usdt": ord_info["amount"] * ord_info["entry_price"],
                    "status": "PENDING",
                    "trading_mode": "LIVE",
                    "market_type": ord_info["market_type"],
                    "unrealized_pnl": 0.0,
                    "created_at": "N/A",
                    "leverage": futures_leverage if ord_info["market_type"] == "FUTURES" else 1
                })
            
            display_balance = live_bal # Wallet balance
            equity = live_bal + unrealized_pnl # Margin balance
        else:
            balance_error = "Failed to fetch live balance from Binance"
    else:
        free_balance = user["demo_balance"]
        locked_collateral = sum(o["size_usdt"] for o in active_orders if (o["trading_mode"] or "DEMO") == "DEMO" and (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE")
        
        # Calculate unrealized PnL from active orders
        current_prices = {}
        active_pairs = set(o["pair"].upper() for o in active_orders)
        for p in active_pairs:
            order_m_type = market_type
            for o in active_orders:
                if o["pair"].upper() == p:
                    order_m_type = dict(o).get("market_type", "SPOT") or "SPOT"
                    break
            try:
                current_prices[p] = trading_engine.fetch_current_price(p, order_m_type)
            except Exception:
                pass
                
        unrealized_pnl = 0.0
        for o in active_orders:
            if (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE":
                opair = o["pair"].upper()
                if opair in current_prices:
                    cp = current_prices[opair]
                    amount = float(o["amount"])
                    entry = float(o["entry_price"])
                    if o["side"].upper() == "BUY":
                        pnl = (cp - entry) * amount
                    else:
                        pnl = (entry - cp) * amount
                    unrealized_pnl += pnl
                    
        display_balance = free_balance + locked_collateral + unrealized_pnl
            
    # Fetch live price & calculate indicators
    try:
        klines = trading_engine.fetch_binance_klines(settings["trading_pair"], settings["timeframe"], limit=100, market_type=market_type)
        indicator_data = indicators.get_latest_indicators(klines)
    except Exception as e:
        indicator_data = {"error": f"Failed to fetch market data: {str(e)}"}
        
    bot_earnings = 0.0
    bot_started_text = None
    if settings["bot_enabled"]:
        bot_started_at = settings["bot_started_at"]
        if bot_started_at:
            bot_earnings = db.get_bot_pnl_since(user["id"], bot_started_at)
            bot_earnings += unrealized_pnl
            try:
                dt = datetime.datetime.strptime(bot_started_at, "%Y-%m-%d %H:%M:%S")
                bot_started_text = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                bot_started_text = bot_started_at

    active_tab = request.args.get("tab", "terminal")
    return render_template(
        "dashboard.html",
        user=user,
        settings=settings,
        active_orders=active_orders,
        history=history,
        indicators=indicator_data,
        log=latest_log,
        logs_history=formatted_logs,
        display_balance=display_balance,
        is_live=is_live,
        balance_error=balance_error,
        bot_earnings=bot_earnings,
        bot_started_text=bot_started_text,
        active_page="dashboard",
        active_tab=active_tab
    )

@app.route("/settings")
def settings():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    server_ip = get_public_ip()
    settings = db.get_user_settings(user["id"])
    return render_template(
        "settings.html",
        user=user,
        settings=settings,
        server_ip=server_ip,
        active_page="settings"
    )

# --- Action API & Form Endpoints ---

@app.route("/save_api_settings", methods=["POST"])
def save_api_settings():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    gemini_key = request.form.get("gemini_api_key", "").strip()
    binance_key = request.form.get("binance_api_key", "").strip()
    binance_secret = request.form.get("binance_api_secret", "").strip()
    tg_chat = request.form.get("telegram_chat_id", "").strip()
    tg_token = request.form.get("telegram_bot_token", "").strip()
    
    db.update_user_api_keys(user["id"], gemini_key, binance_key, binance_secret, tg_chat, tg_token)
    msg = "API credentials and Telegram settings saved successfully."
    flash(msg, "success")
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({"success": True, "message": msg})
    return redirect(url_for("settings"))

@app.route("/save_trading_settings", methods=["POST"])
def save_trading_settings():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    pair = request.form.get("trading_pair", "BTCUSDT").upper().strip()
    timeframe = request.form.get("timeframe", "15m").strip()
    order_size_input = request.form.get("order_size_usdt", "100").strip()
    if "%" in order_size_input:
        order_size = order_size_input
    else:
        try:
            order_size = float(order_size_input)
        except ValueError:
            order_size = 100.0
    trading_mode = request.form.get("trading_mode", "DEMO").upper().strip()
    market_type = request.form.get("market_type", "SPOT").upper().strip()
    futures_leverage = int(request.form.get("futures_leverage", 10))
    min_probability_threshold = float(request.form.get("min_probability_threshold", 0.88))
    invert_signal = 1 if request.form.get("invert_signal") in ["on", "1", "true", "yes"] else 0
    use_limit_orders = 1 if request.form.get("use_limit_orders") in ["on", "1", "true", "yes"] else 0
    use_trailing_stop = 1 if request.form.get("use_trailing_stop") in ["on", "1", "true", "yes"] else 0
    use_ai_limit_price = 1 if request.form.get("use_ai_limit_price") in ["on", "1", "true", "yes"] else 0
    use_ai_exit = 1 if request.form.get("use_ai_exit") in ["on", "1", "true", "yes"] else 0
    use_ai_trailing = 1 if request.form.get("use_ai_trailing") in ["on", "1", "true", "yes"] else 0
    
    trailing_activation_pct = float(request.form.get("trailing_activation_pct", 0.5))
    trailing_step_pct = float(request.form.get("trailing_step_pct", 0.2))
    
    settings = db.get_user_settings(user["id"])
    
    # Save parameters (preserve bot status)
    db.save_user_settings(user["id"], pair, timeframe, order_size, settings["bot_enabled"], trading_mode, market_type, futures_leverage, min_probability_threshold, invert_signal, settings["bot_started_at"], use_limit_orders, use_trailing_stop, use_ai_limit_price, trailing_activation_pct, trailing_step_pct, use_ai_exit, use_ai_trailing)
    msg = "Trading parameters updated successfully."
    flash(msg, "success")
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({
            "success": True,
            "message": msg,
            "settings": {
                "trading_pair": pair,
                "timeframe": timeframe,
                "order_size_usdt": order_size,
                "trading_mode": trading_mode,
                "market_type": market_type,
                "futures_leverage": futures_leverage,
                "min_probability_threshold": min_probability_threshold,
                "invert_signal": bool(invert_signal),
                "use_limit_orders": bool(use_limit_orders),
                "use_trailing_stop": bool(use_trailing_stop),
                "use_ai_limit_price": bool(use_ai_limit_price),
                "use_ai_exit": bool(use_ai_exit),
                "use_ai_trailing": bool(use_ai_trailing)
            }
        })
    return redirect(url_for("settings"))

@app.route("/toggle_bot", methods=["POST"])
def toggle_bot():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    action = request.form.get("action", "stop")
    settings = db.get_user_settings(user["id"])
    
    bot_enabled = 1 if action == "start" else 0
    bot_started_at = None
    if action == "start":
        bot_started_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    db.save_user_settings(
        user["id"], 
        settings["trading_pair"], 
        settings["timeframe"], 
        settings["order_size_usdt"], 
        bot_enabled,
        settings["trading_mode"],
        dict(settings).get("market_type", "SPOT") or "SPOT",
        dict(settings).get("futures_leverage", 10) or 10,
        dict(settings).get("min_probability_threshold", 0.88) or 0.88,
        dict(settings).get("invert_signal", 0) or 0,
        bot_started_at,
        dict(settings).get("use_limit_orders", 1),
        dict(settings).get("use_trailing_stop", 1),
        dict(settings).get("use_ai_limit_price", 0),
        dict(settings).get("trailing_activation_pct", 0.5),
        dict(settings).get("trailing_step_pct", 0.2),
        dict(settings).get("use_ai_exit", 0) or 0,
        dict(settings).get("use_ai_trailing", 0) or 0
    )
    
    status_str = "started" if bot_enabled else "stopped"
    bot_earnings = 0.0
    if action == "stop" and settings["bot_started_at"]:
        bot_earnings = db.get_bot_pnl_since(user["id"], settings["bot_started_at"])

    flash(f"Automated trading bot has been {status_str}.", "success")
    # If called via AJAX, return JSON so frontend can update dynamically
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({
            "success": True,
            "bot_enabled": bool(bot_enabled),
            "bot_started_at": bot_started_at,
            "bot_earnings": bot_earnings,
            "message": f"Automated trading bot has been {status_str}."
        })
    return redirect(url_for("dashboard"))

@app.route("/reset_balance", methods=["POST"])
def reset_balance():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    
    # Use the user-specified initial deposit, or default to 10000
    try:
        initial_deposit = float(request.form.get("initial_deposit", 10000.0))
        if initial_deposit < 10:
            initial_deposit = 10000.0
    except (ValueError, TypeError):
        initial_deposit = 10000.0
    
    db.update_user_demo_balance(user["id"], initial_deposit)
    
    # Clear orders and logs for this user to make it completely fresh
    conn = db.get_db_connection()
    conn.execute("DELETE FROM orders WHERE user_id = ?", (user["id"],))
    conn.execute("DELETE FROM analysis_logs WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    
    msg = f"Портфель сброшен. Начальный депозит: ${initial_deposit:,.2f}. Все ордера и логи очищены."
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({"success": True, "message": msg, "new_balance": initial_deposit})
    return redirect(url_for("settings"))

@app.route("/update_demo_balance", methods=["POST"])
def update_demo_balance():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
        
    try:
        new_balance = float(request.form.get("balance", 10000.0))
        if new_balance < 0:
            return jsonify({"success": False, "error": "Balance cannot be negative"}), 400
            
        db.update_user_demo_balance(user["id"], new_balance)
        return jsonify({"success": True, "new_balance": new_balance})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/close_order/<order_id>", methods=["POST"])
def close_order(order_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    # Check if this order exists in our local SQLite database first
    order = None
    try:
        order_id_int = int(order_id)
        conn = db.get_db_connection()
        order = conn.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id_int, user["id"])).fetchone()
        conn.close()
    except ValueError:
        pass
        
    if not order:
        # Close a real-time position or cancel open limit order directly on Binance
        try:
            settings = db.get_user_settings(user["id"])
            market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
            
            # Fetch active positions to get current size/side
            live_positions = trading_engine.fetch_live_positions(user["id"], market_type)
            target_pos = None
            for pos in live_positions:
                if pos["pair"].upper() == order_id.upper():
                    target_pos = pos
                    break
                    
            if not target_pos:
                # Let's check live open limit orders (maybe they wanted to cancel a pending order)
                live_open_orders = trading_engine.fetch_live_open_orders(user["id"], market_type)
                target_order = None
                for o in live_open_orders:
                    if str(o["id"]) == order_id or o["pair"].upper() == order_id.upper():
                        target_order = o
                        break
                        
                if target_order:
                    # Cancel the open limit order on Binance
                    api_key = user["binance_api_key"]
                    api_secret = user["binance_api_secret"]
                    endpoint = "/fapi/v1/order" if market_type.upper() == "FUTURES" else "/api/v3/order"
                    params = {
                        "symbol": target_order["pair"].upper(),
                        "orderId": target_order["id"]
                    }
                    trading_engine.send_signed_binance_request(api_key, api_secret, "DELETE", endpoint, params, market_type)
                    
                    # Also update local database order if it is PENDING
                    conn = db.get_db_connection()
                    local_pending_order = conn.execute(
                        "SELECT id FROM orders WHERE user_id = ? AND pair = ? AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1",
                        (user["id"], target_order["pair"])
                    ).fetchone()
                    conn.close()
                    if local_pending_order:
                        db.close_order(local_pending_order["id"], "CANCELLED", target_order["entry_price"], 0.0)
                    
                    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
                        return jsonify({
                            "success": True,
                            "order_id": order_id,
                            "pair": target_order["pair"],
                            "status": "CANCELLED",
                            "pnl": 0.0,
                            "created_at": "N/A"
                        })
                    return redirect(url_for("dashboard"))
                
                flash("Active position or open order not found.", "error")
                return redirect(url_for("dashboard"))
                
            # Close the real position on Binance
            amount = target_pos["amount"]
            side = target_pos["side"]
            entry_price = target_pos["entry_price"]
            
            trading_engine.close_live_position(user["id"], target_pos["pair"], amount, market_type, order_side=side)
            
            # Fetch current closing price
            curr_price = trading_engine.fetch_current_price(target_pos["pair"], market_type)
            
            # Calculate final realized PnL based on execution price
            if side == "BUY":
                pnl = (curr_price - entry_price) * amount
            else:
                pnl = (entry_price - curr_price) * amount
            
            # Update local SQLite active order to CLOSED_MANUAL with correct PnL
            conn = db.get_db_connection()
            local_active_order = conn.execute(
                "SELECT id FROM orders WHERE user_id = ? AND pair = ? AND status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1",
                (user["id"], target_pos["pair"])
            ).fetchone()
            conn.close()
            if local_active_order:
                db.close_order(local_active_order["id"], "CLOSED_MANUAL", curr_price, pnl)
            
            pnl_sign = "+" if pnl >= 0 else ""
            trading_engine.send_telegram_notification(
                user["id"],
                f"👤 <b>[LIVE Mode] Позиция закрыта вручную (веб-панель)</b>\n\n"
                f"Пара: <b>{target_pos['pair']}</b>\n"
                f"Сделка: {side}\n"
                f"Цена входа: ${entry_price:,.4f}\n"
                f"Цена закрытия: ${curr_price:,.4f}\n"
                f"Чистый PnL: <b>{pnl_sign}${pnl:,.2f}</b>"
            )
            
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
                return jsonify({
                    "success": True,
                    "order_id": order_id,
                    "pair": target_pos["pair"],
                    "side": side,
                    "entry_price": entry_price,
                    "status": "CLOSED_MANUAL",
                    "pnl": pnl,
                    "created_at": "N/A"
                })
            return redirect(url_for("dashboard"))
        except Exception as e:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
                return jsonify({"success": False, "error": str(e)}), 500
            flash(f"Error closing position: {e}", "error")
            return redirect(url_for("dashboard"))
    
    if not order or (order["status"] != "ACTIVE" and order["status"] != "PENDING"):
        flash("Order not found or already closed/cancelled.", "error")
        return redirect(url_for("dashboard"))
        
    try:
        market_type = dict(order).get("market_type", "SPOT") or "SPOT"
        curr_price = trading_engine.fetch_current_price(order["pair"], market_type)
        
        # Calculate PnL
        amount = order["amount"]
        side = order["side"]
        
        if side == "BUY":
            pnl = (curr_price - order["entry_price"]) * amount
        else:
            pnl = (order["entry_price"] - curr_price) * amount
            
        trading_mode = order["trading_mode"] if "trading_mode" in order.keys() else "DEMO"
        order_status = order["status"]
        
        if order_status == "PENDING":
            # Просто меняем статус на CANCELLED, PnL = 0
            db.close_order(order_id, "CANCELLED", curr_price, 0.0)
            # Баланс не возвращаем, так как он не списывался при PENDING ордере
        else:
            # Close active order in database
            db.close_order(order_id, "CLOSED_MANUAL", curr_price, pnl)
            
            if trading_mode == "DEMO":
                # Return initial size_usdt back to demo balance (db.close_order only adds PnL)
                user_updated = db.get_user_by_id(user["id"])
                db.update_user_demo_balance(user["id"], user_updated["demo_balance"] + order["size_usdt"])
            else:
                # For live orders, place market sell on Binance to close position
                trading_engine.close_live_position(user["id"], order["pair"], amount, market_type, order_side=side)
                
            pnl_sign = "+" if pnl >= 0 else ""
            trading_engine.send_telegram_notification(
                user["id"],
                f"👤 <b>[{trading_mode} Mode] Позиция закрыта вручную (веб-панель)</b>\n\n"
                f"Пара: <b>{order['pair']}</b>\n"
                f"Сделка: {side}\n"
                f"Цена входа: ${order['entry_price']:,.4f}\n"
                f"Цена закрытия: ${curr_price:,.4f}\n"
                f"Чистый PnL: <b>{pnl_sign}${pnl:,.2f}</b>"
            )
            
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
            return jsonify({
                "success": True,
                "order_id": order_id,
                "pair": order["pair"],
                "side": order["side"],
                "entry_price": order["entry_price"],
                "status": "CANCELLED" if order_status == "PENDING" else "CLOSED_MANUAL",
                "pnl": 0.0 if order_status == "PENDING" else pnl,
                "created_at": order["created_at"]
            })
        flash(f"Order on {order['pair']} closed manually. Profit/Loss: ${pnl:+.2f} USDT.", "success")
    except Exception as e:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Failed to fetch market price to close order: {str(e)}", "error")
        
    return redirect(url_for("dashboard"))

@app.route("/run_analysis", methods=["POST"])
def run_analysis():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    res = trading_engine.run_user_analysis_cycle(user["id"])
    if "error" in res:
        return jsonify({"success": False, "error": res["error"]}), 500
        
    # Query latest analysis log to update the stages UI dynamically
    settings = db.get_user_settings(user["id"])
    latest_log = db.get_latest_analysis_log(user["id"], settings["trading_pair"])
    if latest_log:
        res["latest_log"] = {
            "stage1_output": latest_log["stage1_output"],
            "stage2_output": latest_log["stage2_output"],
            "stage3_output": latest_log["stage3_output"],
            "created_at": latest_log["created_at"]
        }
        
    return jsonify(res)

@app.route("/export_orders")
def export_orders():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    import csv
    import io
    from flask import Response
    
    conn = db.get_db_connection()
    orders = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "ID", "Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
        "Amount", "Size USDT", "Leverage", "Status", "PnL", "Trading Mode",
        "Market Type", "Created At", "Closed At"
    ])
    
    for o in orders:
        writer.writerow([
            o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"], o["take_profit"],
            o["amount"], o["size_usdt"], o["leverage"], o["status"], o["pnl"], o["trading_mode"],
            o["market_type"], o["created_at"], o["closed_at"]
        ])
        
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=orders_history.csv"
    return response

@app.route("/export_analysis")
def export_analysis():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    import csv
    import io
    from flask import Response
    
    logs = db.get_all_analysis_logs(user["id"])
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "ID", "Pair", "Created At", "Indicators Summary",
        "Stage 1: Sentiment & Context", 
        "Stage 2: Strategy Planner (Thoughts)", 
        "Stage 3: Execution Config (Actions)"
    ])
    
    for l in logs:
        writer.writerow([
            l["id"], l["pair"], l["created_at"], l["indicators_summary"],
            l["stage1_output"], l["stage2_output"], l["stage3_output"]
        ])
        
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=ai_analysis_logs.csv"
    return response

@app.route("/download_combined")
def download_combined():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
        
    import csv
    import io
    from flask import Response
    
    conn = db.get_db_connection()
    conn.row_factory = db.sqlite3.Row
    orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    writer.writerow([
        "Order ID", "Symbol / Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
        "Amount (Qty)", "Margin Size (USDT)", "Leverage", "Order Status", "Trading Mode", "Market Type",
        "Order Created At", "Order Closed At", "Realized PnL (USDT)",
        "AI Signal Action", "AI Confidence / Probability", "AI Stage 3 Reason", "AI Technical Indicators"
    ])
    
    for o in orders:
        # Find the closest AI log for this order
        log = conn.execute("""
            SELECT * FROM analysis_logs 
            WHERE user_id = ? AND pair = ? AND created_at <= ? 
            ORDER BY created_at DESC LIMIT 1
        """, (user["id"], o["pair"], o["created_at"])).fetchone()
        
        ai_action = "N/A"
        ai_prob = "N/A"
        ai_reason = "N/A"
        ai_indicators = "N/A"
        
        if log:
            ai_indicators = log["indicators_summary"] or "N/A"
            try:
                import json
                s3 = json.loads(log["stage3_output"])
                ai_action = s3.get("action", "HOLD")
                ai_prob = f"{s3.get('probability', 0.0) * 100:.2f}%"
                ai_reason = s3.get("reason", "N/A")
            except Exception:
                pass
                
        writer.writerow([
            o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"], o["take_profit"],
            o["amount"], o["size_usdt"], o["leverage"], o["status"], o["trading_mode"], o["market_type"],
            o["created_at"], o["closed_at"], o["pnl"],
            ai_action, ai_prob, ai_reason, ai_indicators
        ])
        
    conn.close()
    
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=combined_trading_history.csv"
    return response

@app.route("/save_ui_settings", methods=["POST"])
def save_ui_settings():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
        
    data = request.json
    ui_language = data.get("ui_language", "RU")
    ui_auto_center = 1 if data.get("ui_auto_center", True) else 0
    
    db.save_ui_settings(user["id"], ui_language, ui_auto_center)
    return jsonify({"success": True})

@app.route("/reset_demo_orders", methods=["POST"])
def reset_demo_orders():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    db.clear_demo_orders(user["id"])
    msg = "Все демо-ордера успешно сброшены."
    flash(msg, "success")
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({"success": True, "message": msg})
    return redirect(url_for("dashboard"))

@app.route("/api/more_logs")
def get_more_logs():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 30, type=int)
    
    conn = db.get_db_connection()
    logs_rows = conn.execute(
        "SELECT * FROM analysis_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user["id"], limit, offset)
    ).fetchall()
    conn.close()
    
    formatted_logs = []
    for l in logs_rows:
        log_dict = dict(l)
        action = "HOLD"
        prob = 0.0
        reason = "No details"
        order_type = "None"
        try:
            import json
            s3 = json.loads(l["stage3_output"])
            action = s3.get("action", "HOLD")
            prob = s3.get("probability", 0.0)
            reason = s3.get("reason", "No details")
            order_type = s3.get("order_type", "None")
            if order_type == "None" and action != "HOLD":
                settings_dict = dict(db.get_user_settings(user["id"])) if user else {}
                use_limit = settings_dict.get("use_limit_orders", 1)
                order_type = "MARKET" if (prob >= 0.95 or not use_limit) else "LIMIT"
        except Exception:
            pass
        log_dict["action"] = action
        log_dict["probability"] = prob
        log_dict["reason"] = reason
        log_dict["order_type"] = order_type
        formatted_logs.append(log_dict)
        
    return jsonify({"logs": formatted_logs})

@app.route("/api/more_orders")
def get_more_orders():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 30, type=int)
    
    conn = db.get_db_connection()
    rows = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? AND status NOT IN ('ACTIVE', 'PENDING') ORDER BY closed_at DESC LIMIT ? OFFSET ?",
        (user["id"], limit, offset)
    ).fetchall()
    conn.close()
    
    orders = []
    for r in rows:
        orders.append(dict(r))
        
    return jsonify({"orders": orders})

@app.route("/api/market_data")
def api_market_data():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    settings = db.get_user_settings(user["id"])
    pair = settings["trading_pair"]
    timeframe = settings["timeframe"]
    market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
    futures_leverage = dict(settings).get("futures_leverage", 10) or 10
    
    try:
        # Fetch 500 klines to ensure indicators are calculated accurately and chart has history
        klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=500, market_type=market_type)
        indicator_data = indicators.get_latest_indicators(klines)
        
        # Format the klines for the frontend chart
        formatted_klines = []
        for k in klines:
            formatted_klines.append({
                "time": k[0],  # Open time in ms
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            })
            
        # Format active orders
        active_orders = db.get_active_orders(user["id"])
        formatted_orders = []
        for o in active_orders:
            formatted_orders.append({
                "id": o["id"],
                "pair": o["pair"],
                "side": o["side"],
                "entry_price": o["entry_price"],
                "stop_loss": o["stop_loss"],
                "take_profit": o["take_profit"],
                "amount": o["amount"],
                "size_usdt": o["size_usdt"],
                "trading_mode": o["trading_mode"] or "DEMO",
                "market_type": dict(o).get("market_type", "SPOT") or "SPOT",
                "status": o["status"],
                "created_at": o["created_at"],
                "leverage": futures_leverage if (dict(o).get("market_type", "SPOT") or "SPOT") == "FUTURES" else 1
            })
            
        # Get current prices of all active pairs to calculate PnL
        active_pairs = set(o["pair"].upper() for o in active_orders)
        active_pairs.add(pair.upper())
        current_prices = {}
        for p in active_pairs:
            order_m_type = market_type
            for o in active_orders:
                if o["pair"].upper() == p:
                    order_m_type = dict(o).get("market_type", "SPOT") or "SPOT"
                    break
            try:
                current_prices[p] = trading_engine.fetch_current_price(p, order_m_type)
            except Exception:
                pass
                
        # Get dynamic balance based on active mode
        trading_mode = dict(settings).get("trading_mode", "DEMO") or "DEMO"
        is_live = (trading_mode == "LIVE")
        user_refreshed = db.get_user_by_id(user["id"])
        free_balance = user_refreshed["demo_balance"]
        unrealized_pnl = 0.0
        
        if is_live:
            live_bal = trading_engine.fetch_binance_balance(user["id"], market_type)
            live_positions = trading_engine.fetch_live_positions(user["id"], market_type)
            unrealized_pnl = sum(pos.get("unrealized_pnl", 0.0) for pos in live_positions)
            
            balance = live_bal if live_bal is not None else free_balance
            equity = (live_bal + unrealized_pnl) if live_bal is not None else free_balance
        else:
            locked_collateral = sum(o["size_usdt"] for o in active_orders if (o["trading_mode"] or "DEMO") == "DEMO" and (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE")
            
            # Calculate unrealized PnL only for ACTIVE orders
            for o in active_orders:
                if (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE":
                    opair = o["pair"].upper()
                    if opair in current_prices:
                        cp = current_prices[opair]
                        amount = float(o["amount"])
                        entry = float(o["entry_price"])
                        if o["side"].upper() == "BUY":
                            pnl = (cp - entry) * amount
                        else:
                            pnl = (entry - cp) * amount
                        unrealized_pnl += pnl
                        
            equity = free_balance + locked_collateral + unrealized_pnl
            balance = free_balance + locked_collateral
                
        return jsonify({
            "success": True,
            "pair": pair,
            "timeframe": timeframe,
            "market_type": market_type,
            "current_price": indicator_data.get("current_price"),
            "current_prices": current_prices,
            "klines": formatted_klines,
            "indicators": indicator_data,
            "active_orders": formatted_orders,
            "balance": balance,
            "free_balance": free_balance if not is_live else balance,
            "is_live": is_live,
            "unrealized_pnl": unrealized_pnl,
            "equity": equity
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/all_orders")
def api_all_orders():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    pair = request.args.get("pair", "")
    mode = request.args.get("mode", "")
    side = request.args.get("side", "")
    status = request.args.get("status", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    
    try:
        rows = db.get_filtered_orders(user["id"], pair, mode, side, status, start_date, end_date)
        orders = []
        for r in rows:
            orders.append({
                "id": r["id"],
                "pair": r["pair"],
                "side": r["side"],
                "entry_price": r["entry_price"],
                "stop_loss": r["stop_loss"],
                "take_profit": r["take_profit"],
                "amount": r["amount"],
                "size_usdt": (r["amount"] * r["entry_price"]) if (r["market_type"] or "SPOT") == "FUTURES" else r["size_usdt"],
                "leverage": r["leverage"],
                "status": r["status"],
                "pnl": r["pnl"],
                "trading_mode": r["trading_mode"],
                "market_type": r["market_type"],
                "created_at": r["created_at"],
                "closed_at": r["closed_at"]
            })
        return jsonify({"success": True, "orders": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/ai_decision_history")
def api_ai_decision_history():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
        
    pair = request.args.get("pair", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    
    try:
        rows = db.get_filtered_analysis_logs(user["id"], pair, start_date, end_date)
        logs = []
        for r in rows:
            logs.append({
                "id": r["id"],
                "pair": r["pair"],
                "indicators_summary": r["indicators_summary"],
                "stage1_output": r["stage1_output"],
                "stage2_output": r["stage2_output"],
                "stage3_output": r["stage3_output"],
                "created_at": r["created_at"]
            })
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


g_market_cache = {}
g_live_cache = {}
g_rec_cache = {}

@sock.route('/ws/market_data')
def ws_market_data(ws):
    user = get_current_user()
    if not user:
        try:
            ws.send(json.dumps({"success": False, "error": "Unauthorized"}))
            ws.close()
        except:
            pass
        return

    loop_counter = 0
    last_pair = None
    last_timeframe = None
    last_market_type = None
    
    while True:
        loop_start = time.time()
        try:
            settings = db.get_user_settings(user["id"])
            pair = settings["trading_pair"]
            timeframe = settings["timeframe"]
            market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
            futures_leverage = dict(settings).get("futures_leverage", 10) or 10
            
            # Check if timeframe/pair/market_type changed so we send fresh klines
            send_klines = (pair != last_pair or timeframe != last_timeframe or market_type != last_market_type)
            
            # Get klines & indicator data using a 3-second cache to avoid hitting Binance API rate limits
            cache_key = f"{pair}_{timeframe}_{market_type}"
            now = time.time()
            cached = g_market_cache.get(cache_key)
            if cached and (now - cached["time"] < 3.0):
                klines = cached["klines"]
                indicator_data = cached["indicator_data"]
            else:
                klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=500, market_type=market_type)
                indicator_data = indicators.get_latest_indicators(klines)
                g_market_cache[cache_key] = {"time": now, "klines": klines, "indicator_data": indicator_data}
            
            formatted_klines = []
            if send_klines:
                for k in klines[-500:]:
                    formatted_klines.append({
                        "time": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    })
                last_pair = pair
                last_timeframe = timeframe
                last_market_type = market_type
            else:
                # Omit full history, but send the latest candle to fallback update the chart in case WebSocket is dead
                if klines and len(klines) > 0:
                    k = klines[-1]
                    formatted_klines = [{
                        "time": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    }]
                else:
                    formatted_klines = None
                
            trading_mode = dict(settings).get("trading_mode", "DEMO") or "DEMO"
            is_live = (trading_mode == "LIVE")
            
            if is_live:
                live_cache_key = f"live_{user['id']}_{market_type}"
                now_live = time.time()
                cached_live = g_live_cache.get(live_cache_key)
                
                # Fetch local pending virtual limit orders
                local_active = db.get_active_orders(user["id"])
                local_pending = [o for o in local_active if (o["trading_mode"] or "DEMO") == "LIVE" and o["status"] == "PENDING"]
                
                if cached_live and (now_live - cached_live["time"] < 2.0):
                    live_bal = cached_live["balance"]
                    live_positions = cached_live["positions"]
                    live_open_orders = cached_live["open_orders"]
                    current_prices = cached_live["current_prices"]
                else:
                    live_bal = trading_engine.fetch_binance_balance(user["id"], market_type)
                    if live_bal is not None:
                        live_positions = trading_engine.fetch_live_positions(user["id"], market_type)
                        live_open_orders = trading_engine.fetch_live_open_orders(user["id"], market_type)
                        
                        active_pairs = {pair.upper()}
                        for pos in live_positions:
                            active_pairs.add(pos["pair"].upper())
                        for o in local_pending:
                            active_pairs.add(o["pair"].upper())
                        for ord_info in live_open_orders:
                            active_pairs.add(ord_info["pair"].upper())
                            
                        current_prices = {}
                        for p in active_pairs:
                            try:
                                current_prices[p] = trading_engine.fetch_current_price(p, market_type)
                            except Exception:
                                pass
                        g_live_cache[live_cache_key] = {
                            "time": now_live,
                            "balance": live_bal,
                            "positions": live_positions,
                            "open_orders": live_open_orders,
                            "current_prices": current_prices
                        }
                    else:
                        live_positions = []
                        live_open_orders = []
                        current_prices = {}
                
                unrealized_pnl = 0.0
                if live_bal is not None:
                    active_orders = []
                    
                    # 1. Real positions
                    for pos in live_positions:
                        pos_pair = pos["pair"].upper()
                        curr_price = current_prices.get(pos_pair)
                        if curr_price:
                            if pos["side"] == "BUY":
                                pnl_val = (curr_price - pos["entry_price"]) * pos["amount"]
                            else:
                                pnl_val = (pos["entry_price"] - curr_price) * pos["amount"]
                        else:
                            pnl_val = pos.get("unrealized_pnl", 0.0)
                            
                        unrealized_pnl += pnl_val
                        
                        matching_local = None
                        for lo in local_active:
                            if lo["pair"].upper() == pos["pair"].upper() and lo["status"] == "ACTIVE":
                                matching_local = lo
                                break
                                
                        sl_val = matching_local["stop_loss"] if matching_local else None
                        tp_val = matching_local["take_profit"] if matching_local else None
                        created_at_val = matching_local["created_at"] if matching_local else "N/A"
                        
                        active_orders.append({
                            "id": pos["id"],
                            "pair": pos["pair"],
                            "side": pos["side"],
                            "entry_price": pos["entry_price"],
                            "stop_loss": sl_val,
                            "take_profit": tp_val,
                            "amount": pos["amount"],
                            "size_usdt": pos["amount"] * pos["entry_price"],
                            "status": "ACTIVE",
                            "trading_mode": "LIVE",
                            "market_type": pos["market_type"],
                            "unrealized_pnl": pnl_val,
                            "created_at": created_at_val,
                            "leverage": pos.get("leverage", 10)
                        })
                        
                    # 2. Local pending limit orders
                    for o in local_pending:
                        active_orders.append({
                            "id": o["id"],
                            "pair": o["pair"],
                            "side": o["side"],
                            "entry_price": o["entry_price"],
                            "stop_loss": o["stop_loss"],
                            "take_profit": o["take_profit"],
                            "amount": o["amount"],
                            "size_usdt": o["size_usdt"],
                            "status": "PENDING",
                            "trading_mode": "LIVE",
                            "market_type": dict(o).get("market_type", "SPOT") or "SPOT",
                            "unrealized_pnl": 0.0,
                            "created_at": o["created_at"],
                            "leverage": futures_leverage if (dict(o).get("market_type", "SPOT") or "SPOT") == "FUTURES" else 1
                        })
                        
                    # 3. Real open limit orders on Binance
                    for ord_info in live_open_orders:
                        if any(str(x["id"]) == str(ord_info["id"]) for x in active_orders):
                            continue
                        active_orders.append({
                            "id": ord_info["id"],
                            "pair": ord_info["pair"],
                            "side": ord_info["side"],
                            "entry_price": ord_info["entry_price"],
                            "stop_loss": None,
                            "take_profit": None,
                            "amount": ord_info["amount"],
                            "size_usdt": ord_info["amount"] * ord_info["entry_price"],
                            "status": "PENDING",
                            "trading_mode": "LIVE",
                            "market_type": ord_info["market_type"],
                            "unrealized_pnl": 0.0,
                            "created_at": "N/A",
                            "leverage": futures_leverage if ord_info["market_type"] == "FUTURES" else 1
                        })
                        
                    balance = live_bal
                    equity = live_bal + unrealized_pnl
                else:
                    active_orders = []
                    balance = 0.0
                    equity = 0.0
                    
                formatted_orders = []
                for o in active_orders:
                    formatted_orders.append({
                        "id": o["id"],
                        "pair": o["pair"],
                        "side": o["side"],
                        "entry_price": o["entry_price"],
                        "stop_loss": o["stop_loss"],
                        "take_profit": o["take_profit"],
                        "amount": o["amount"],
                        "size_usdt": o["size_usdt"],
                        "trading_mode": o["trading_mode"],
                        "market_type": o["market_type"],
                        "status": o["status"],
                        "created_at": o["created_at"],
                        "unrealized_pnl": o.get("unrealized_pnl", 0.0),
                        "leverage": o.get("leverage", 10),
                        "is_trailing": bool(dict(settings).get("use_trailing_stop", 1))
                    })
                
                user_refreshed = db.get_user_by_id(user["id"])
                free_balance = user_refreshed["demo_balance"]
            else:
                # DEMO Mode
                active_orders = db.get_active_orders(user["id"])
                
                active_pairs = set(o["pair"].upper() for o in active_orders)
                active_pairs.add(pair.upper())
                
                # Fetch current prices using 2-second cache for DEMO mode
                now_demo = time.time()
                current_prices = {}
                for p in active_pairs:
                    demo_price_cache_key = f"demo_price_{p}_{market_type}"
                    cached_demo_price = g_live_cache.get(demo_price_cache_key)
                    if cached_demo_price and (now_demo - cached_demo_price["time"] < 2.0):
                        current_prices[p] = cached_demo_price["price"]
                    else:
                        try:
                            cp = trading_engine.fetch_current_price(p, market_type)
                            current_prices[p] = cp
                            g_live_cache[demo_price_cache_key] = {"time": now_demo, "price": cp}
                        except Exception:
                            if cached_demo_price:
                                current_prices[p] = cached_demo_price["price"]

                formatted_orders = []
                for o in active_orders:
                    o_pnl = 0.0
                    if (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE":
                        opair = o["pair"].upper()
                        if opair in current_prices:
                            cp = current_prices[opair]
                            amt = float(o["amount"])
                            ent = float(o["entry_price"])
                            if o["side"].upper() == "BUY":
                                o_pnl = (cp - ent) * amt
                            else:
                                o_pnl = (ent - cp) * amt
                                
                    formatted_orders.append({
                        "id": o["id"],
                        "pair": o["pair"],
                        "side": o["side"],
                        "entry_price": o["entry_price"],
                        "stop_loss": o["stop_loss"],
                        "take_profit": o["take_profit"],
                        "amount": o["amount"],
                        "size_usdt": (o["amount"] * o["entry_price"]) if (dict(o).get("market_type", "SPOT") or "SPOT") == "FUTURES" else o["size_usdt"],
                        "trading_mode": o["trading_mode"] or "DEMO",
                        "market_type": dict(o).get("market_type", "SPOT") or "SPOT",
                        "status": o["status"],
                        "created_at": o["created_at"],
                        "unrealized_pnl": o_pnl,
                        "leverage": futures_leverage if (dict(o).get("market_type", "SPOT") or "SPOT") == "FUTURES" else 1,
                        "is_trailing": bool(dict(settings).get("use_trailing_stop", 1))
                    })
                
                user_refreshed = db.get_user_by_id(user["id"])
                free_balance = user_refreshed["demo_balance"]
                unrealized_pnl = 0.0
                locked_collateral = sum(o["size_usdt"] for o in active_orders if (o["trading_mode"] or "DEMO") == "DEMO" and (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE")
                
                for o in active_orders:
                    if (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE":
                        opair = o["pair"].upper()
                        if opair in current_prices:
                            cp = current_prices[opair]
                            amount = float(o["amount"])
                            entry = float(o["entry_price"])
                            if o["side"].upper() == "BUY":
                                pnl = (cp - entry) * amount
                            else:
                                pnl = (entry - cp) * amount
                            unrealized_pnl += pnl
                            
                equity = free_balance + locked_collateral + unrealized_pnl
                balance = free_balance + locked_collateral
                    
            history = db.get_order_history(user["id"])
            formatted_history = []
            for h in history[:20]:
                formatted_history.append({
                    "id": h["id"],
                    "pair": h["pair"],
                    "side": h["side"],
                    "entry_price": h["entry_price"],
                    "status": h["status"],
                    "pnl": h["pnl"],
                    "created_at": h["created_at"],
                    "closed_at": h["closed_at"]
                })
                
            bot_earnings = 0.0
            if settings["bot_enabled"]:
                bot_started_at = settings["bot_started_at"]
                if bot_started_at:
                    bot_earnings = db.get_bot_pnl_since(user["id"], bot_started_at)
                    bot_earnings += unrealized_pnl
                    
            all_analysis_logs = db.get_all_analysis_logs(user["id"])
            formatted_analysis_history = []
            for l in all_analysis_logs[:30]:
                log_dict = {
                    "id": l["id"],
                    "pair": l["pair"],
                    "indicators_summary": l["indicators_summary"],
                    "stage1_output": l["stage1_output"],
                    "stage2_output": l["stage2_output"],
                    "stage3_output": l["stage3_output"],
                    "created_at": l["created_at"]
                }
                action = "HOLD"
                prob = 0.0
                reason = "No details"
                order_type = "None"
                try:
                    s3 = json.loads(l["stage3_output"])
                    action = s3.get("action", "HOLD")
                    prob = s3.get("probability", 0.0)
                    reason = s3.get("reason", "No details")
                    order_type = s3.get("order_type", "None")
                    if order_type == "None" and action != "HOLD":
                        settings_dict = dict(db.get_user_settings(user["id"])) if user else {}
                        use_limit = settings_dict.get("use_limit_orders", 1)
                        order_type = "LIMIT" if use_limit else "MARKET"
                except Exception:
                    pass
                log_dict["action"] = action
                log_dict["probability"] = prob
                log_dict["reason"] = reason
                log_dict["order_type"] = order_type
                formatted_analysis_history.append(log_dict)

            # Throttle or fetch cached model signal to prevent rendering lags
            now_rec = time.time()
            ws_session_key = f"ws_rec_{user['id']}_{pair}"
            if settings["bot_enabled"]:
                latest_log = db.get_latest_analysis_log(user["id"], pair)
                recommendation = None
                if latest_log:
                    try:
                        recommendation = json.loads(latest_log["stage3_output"])
                    except:
                        pass
            else:
                cached_rec = g_rec_cache.get(ws_session_key)
                if cached_rec and (now_rec - cached_rec["time"] < 15.0):
                    recommendation = cached_rec["data"]
                else:
                    recommendation = trading_engine.evaluate_market_signal(user["id"], persist_log=False, place_order=False)
                    g_rec_cache[ws_session_key] = {"data": recommendation, "time": now_rec}

            loop_counter += 1
            data = {
                "success": True,
                "pair": pair,
                "timeframe": timeframe,
                "market_type": market_type,
                "current_price": indicator_data.get("current_price"),
                "current_prices": current_prices,
                "klines": formatted_klines,
                "indicators": indicator_data,
                "active_orders": formatted_orders,
                "history": formatted_history,
                "analysis_history": formatted_analysis_history,
                "balance": balance,
                "free_balance": free_balance if not is_live else balance,
                "is_live": is_live,
                "recommendation": recommendation,
                "bot_earnings": bot_earnings,
                "bot_enabled": bool(settings["bot_enabled"]),
                "unrealized_pnl": unrealized_pnl,
                "equity": equity
            }
            ws.send(json.dumps(data))
            
            elapsed = time.time() - loop_start
            sleep_time = max(0.05, 0.5 - elapsed)
            time.sleep(sleep_time)
            
        except simple_websocket.ConnectionClosed:
            break
        except Exception as e:
            try:
                ws.send(json.dumps({"success": False, "error": str(e)}))
            except:
                pass
            
            elapsed = time.time() - loop_start
            sleep_time = max(0.5, 2.5 - elapsed)
            time.sleep(sleep_time)

if __name__ == "__main__":
    # Call initializer hooks before starting webserver
    initialize_application()
    
    import os
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    debug_mode = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    
    if debug_mode:
        app.debug = True
        
    try:
        is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    except Exception:
        is_reloader_child = False

    if is_reloader_child or not debug_mode:
        trading_engine.start_bot_scheduler()
        import telegram_manager
        telegram_manager.start_telegram_manager()

    app.run(debug=debug_mode, host=host, port=port)
