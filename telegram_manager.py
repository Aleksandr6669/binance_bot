import time
import threading
import telebot
from telebot import types
import db
import trading_engine

# Map of token -> TeleBot instance
_bots = {}
_bot_offsets = {}

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📊 Статус", "📋 Активный ордер")
    markup.row("▶️ Запустить бота", "⏸ Остановить бота")
    markup.row("💰 Баланс", "⚙️ Настройки")
    markup.row("⚡️ Закрыть все позиции")
    return markup

def make_settings_markup(settings):
    pair = settings.get("trading_pair", "N/A")
    mode = settings.get("trading_mode", "DEMO")
    limit = "ВКЛ" if settings.get("use_limit_orders", 1) else "ВЫКЛ"
    invert = "ВКЛ" if settings.get("invert_signal", 0) else "ВЫКЛ"
    notifications = "ВКЛ" if settings.get("telegram_notifications", 1) else "ВЫКЛ"
    
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton(text=f"Пара: {pair} 🔄", callback_data="settings_pair"))
    markup.row(types.InlineKeyboardButton(text=f"Режим: {mode} 🔀", callback_data="settings_mode"))
    markup.row(types.InlineKeyboardButton(text=f"Лимитные ордера: {limit} 🔀", callback_data="settings_limit"))
    markup.row(types.InlineKeyboardButton(text=f"Инверсия: {invert} 🔀", callback_data="settings_invert"))
    markup.row(types.InlineKeyboardButton(text=f"Уведомления о сделках: {notifications} 🔔", callback_data="settings_notifications"))
    return markup

def setup_bot(bot, user_id, chat_id):
    @bot.message_handler(func=lambda msg: str(msg.chat.id) == str(chat_id))
    def handle_message(message):
        text = message.text.strip() if message.text else ""
        command = text.split("@")[0].lower() if text else ""
        
        settings = db.get_user_settings(user_id)
        user_info = db.get_user_by_id(user_id)
        
        response = ""
        
        if command == "/start_bot" or text == "▶️ Запустить бота":
            db.update_user_settings(user_id, "bot_enabled", 1)
            response = "✅ <b>Авто-торговля ВКЛЮЧЕНА</b>\nБот переведен в активный режим и начал поиск точек входа."
            bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        elif command == "/stop_bot" or text == "⏸ Остановить бота":
            db.update_user_settings(user_id, "bot_enabled", 0)
            response = "⏸ <b>Авто-торговля ОСТАНОВЛЕНА</b>\nНовые позиции открываться не будут."
            bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        elif command == "/status" or text == "📊 Статус":
            settings_dict = dict(settings) if settings else {}
            enabled = settings_dict.get("bot_enabled", 0)
            status_text = "🟢 ВКЛЮЧЕН" if enabled else "🔴 ВЫКЛЮЧЕН"
            pair = settings_dict.get("trading_pair", "N/A")
            mode = settings_dict.get("trading_mode", "DEMO")
            
            active_orders = db.get_active_orders()
            user_active = [o for o in active_orders if o["user_id"] == user_id]
            
            response = f"📊 <b>Текущий статус</b>\n\n" \
                       f"Бот: {status_text}\n" \
                       f"Режим: <b>{mode}</b>\n" \
                       f"Торговая пара: <b>{pair}</b>\n\n" \
                       f"Открытых позиций: <b>{len(user_active)}</b>"
            bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        elif command == "/balance" or text == "💰 Баланс":
            settings_dict = dict(settings) if settings else {}
            trading_mode = settings_dict.get("trading_mode", "DEMO") or "DEMO"
            market_type = settings_dict.get("market_type", "SPOT") or "SPOT"
            is_live = (trading_mode == "LIVE")
            
            if is_live:
                live_bal = trading_engine.fetch_binance_balance(user_id, market_type)
                if live_bal is not None:
                    live_positions = trading_engine.fetch_live_positions(user_id, market_type)
                    unrealized_pnl = 0.0
                    locked_collateral = 0.0
                    
                    # Fetch current prices for active pairs to calculate PnL on backend
                    active_pairs = {settings_dict.get("trading_pair", "ETHUSDC").upper()}
                    for pos in live_positions:
                        active_pairs.add(pos["pair"].upper())
                        
                    current_prices = {}
                    for p in active_pairs:
                        try:
                            current_prices[p] = trading_engine.fetch_current_price(p, market_type)
                        except Exception:
                            pass
                            
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
                        lev = pos.get("leverage", 10)
                        size_usdt = pos["amount"] * pos["entry_price"]
                        locked_collateral += (size_usdt / lev) if market_type.upper() == "FUTURES" else size_usdt
                        
                    free_balance = live_bal
                    total_balance = live_bal + unrealized_pnl
                    
                    # Session earnings
                    bot_earnings = 0.0
                    if settings_dict.get("bot_enabled"):
                        bot_started_at = settings_dict.get("bot_started_at")
                        if bot_started_at:
                            bot_earnings = db.get_bot_pnl_since(user_id, bot_started_at)
                            bot_earnings += unrealized_pnl
                            
                    starting_bal = total_balance - bot_earnings
                    pct = (bot_earnings / starting_bal * 100) if starting_bal != 0 else 0.0
                    
                    pnl_sign = "+" if bot_earnings >= 0 else ""
                    pct_sign = "+" if pct >= 0 else ""
                    earnings_text = f"{pnl_sign}${bot_earnings:,.2f} ({pct_sign}{pct:,.2f}%)"
                    
                    unrealized_sign = "+" if unrealized_pnl >= 0 else ""
                    unrealized_text = f"{unrealized_sign}${unrealized_pnl:,.2f}"
                    
                    response = f"💰 <b>Баланс (LIVE - {market_type})</b>\n\n" \
                               f"Общий баланс (Equity): <b>${total_balance:,.2f}</b>\n" \
                               f"Депозит (Wallet): <b>${free_balance:,.2f}</b>\n" \
                               f"Маржа в сделках: <b>${locked_collateral:,.2f}</b>\n" \
                               f"Нереализованный PnL: <b>{unrealized_text}</b>\n" \
                               f"Доход сессии: <b>{earnings_text}</b>"
                else:
                    response = "⚠️ Не удалось получить баланс с Binance. Проверьте API-ключи."
                bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            else:
                user_info_dict = dict(user_info) if user_info else {}
                free_balance = user_info_dict.get("demo_balance", 0)
                
                # Calculate total balance (free + locked collateral + unrealized PnL)
                active_orders = db.get_active_orders(user_id)
                locked_collateral = sum(o["size_usdt"] for o in active_orders if (o["trading_mode"] or "DEMO") == "DEMO" and (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE")
                
                unrealized_pnl = 0.0
                current_prices = {}
                for o in active_orders:
                    if (o["trading_mode"] or "DEMO") == "DEMO" and (dict(o).get("status", "ACTIVE")).upper() == "ACTIVE":
                        pair = o["pair"].upper()
                        market_type = dict(o).get("market_type", "SPOT") or "SPOT"
                        if pair not in current_prices:
                            try:
                                current_prices[pair] = trading_engine.fetch_current_price(pair, market_type)
                            except Exception:
                                pass
                        
                        if pair in current_prices:
                            cp = current_prices[pair]
                            amount = float(o["amount"])
                            entry = float(o["entry_price"])
                            if o["side"].upper() == "BUY":
                                pnl = (cp - entry) * amount
                            else:
                                pnl = (entry - cp) * amount
                            unrealized_pnl += pnl
                            
                total_balance = free_balance + locked_collateral + unrealized_pnl
                
                # Calculate session earnings (pnl + unrealized PnL since bot started)
                bot_earnings = 0.0
                if settings_dict.get("bot_enabled"):
                    bot_started_at = settings_dict.get("bot_started_at")
                    if bot_started_at:
                        bot_earnings = db.get_bot_pnl_since(user_id, bot_started_at)
                        bot_earnings += unrealized_pnl
                
                starting_bal = total_balance - bot_earnings
                pct = (bot_earnings / starting_bal * 100) if starting_bal != 0 else 0.0
                
                pnl_sign = "+" if bot_earnings >= 0 else ""
                pct_sign = "+" if pct >= 0 else ""
                
                earnings_text = f"{pnl_sign}${bot_earnings:,.2f} ({pct_sign}{pct:,.2f}%)"
                
                unrealized_sign = "+" if unrealized_pnl >= 0 else ""
                unrealized_text = f"{unrealized_sign}${unrealized_pnl:,.2f}"
                
                response = f"💰 <b>Баланс (DEMO)</b>\n\n" \
                           f"Общий баланс: <b>${total_balance:,.2f}</b>\n" \
                           f"Свободно: <b>${free_balance:,.2f}</b>\n" \
                           f"Залог в сделках: <b>${locked_collateral:,.2f}</b>\n" \
                           f"Нереализованный PnL: <b>{unrealized_text}</b>\n" \
                           f"Доход сессии: <b>{earnings_text}</b>"
                bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        elif command == "/active_order" or text == "📋 Активный ордер":
            active_orders = db.get_active_orders(user_id)
            if not active_orders:
                response = "Нет открытых позиций."
            else:
                o = active_orders[0]
                market_type = dict(o).get("market_type", "SPOT") or "SPOT"
                try:
                    curr_price = trading_engine.fetch_current_price(o["pair"], market_type)
                    side = o["side"]
                    amount = o["amount"]
                    entry = o["entry_price"]
                    pnl = (curr_price - entry) * amount if side == "BUY" else (entry - curr_price) * amount
                    pnl_sign = "+" if pnl >= 0 else ""
                    sl_val = f"${o['stop_loss']:,.4f}" if o['stop_loss'] is not None else "Не установлен"
                    tp_val = f"${o['take_profit']:,.4f}" if o['take_profit'] is not None else "Не установлен"
                    response = f"📋 <b>Активный ордер</b>\n\n" \
                               f"Пара: <b>{o['pair']}</b> ({market_type})\n" \
                               f"Режим: {o['trading_mode'] or 'DEMO'}\n" \
                               f"Тип: <b>{side}</b>\n" \
                               f"Вход: ${entry:,.4f}\n" \
                               f"Текущая цена: ${curr_price:,.4f}\n" \
                               f"PnL: <b>{pnl_sign}${pnl:,.2f}</b>\n" \
                               f"Stop Loss: <b>{sl_val}</b>\n" \
                               f"Take Profit: <b>{tp_val}</b>"
                except Exception as e:
                    response = f"Ошибка получения данных: {e}"
            bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        elif command == "/settings" or text == "⚙️ Настройки":
            settings_dict = dict(settings) if settings else {}
            markup = make_settings_markup(settings_dict)
            bot.send_message(chat_id, "⚙️ <b>Настройки бота</b>", parse_mode="HTML", reply_markup=markup)
            
        elif command == "/close_all" or text == "⚡️ Закрыть все позиции":
            active_orders = db.get_active_orders()
            user_active = [o for o in active_orders if o["user_id"] == user_id]
            
            if not user_active:
                response = "Нет открытых позиций."
            else:
                closed_count = 0
                for order in user_active:
                    pair = order["pair"].upper()
                    market_type = dict(order).get("market_type", "SPOT") or "SPOT"
                    try:
                        price = trading_engine.fetch_current_price(pair, market_type)
                        side = order["side"]
                        entry = order["entry_price"]
                        amount = order["amount"]
                        trading_mode = dict(order).get("trading_mode", "DEMO")
                        order_id = order["id"]
                        
                        pnl = (price - entry) * amount if side == "BUY" else (entry - price) * amount
                        
                        if trading_mode == "LIVE":
                            success = trading_engine.close_live_position(user_id, pair, amount, market_type, order_side=side)
                            if success:
                                db.close_order(order_id, "CLOSED_MANUAL", price, pnl)
                                closed_count += 1
                        else:
                            db_closed = db.close_order(order_id, "CLOSED_MANUAL", price, pnl)
                            if db_closed:
                                size_usdt = order["size_usdt"]
                                new_balance = user_info["demo_balance"] + size_usdt
                                db.update_user_demo_balance(user_id, new_balance)
                                user_info = db.get_user_by_id(user_id)
                                closed_count += 1
                    except Exception as e:
                        print(f"Failed to close order {order['id']}: {e}")
                response = f"⚡️ <b>Экстренное закрытие</b>\nУспешно закрыто позиций: <b>{closed_count}</b>"
            bot.send_message(chat_id, response, parse_mode="HTML", reply_markup=get_main_keyboard())
            
        else:
            bot.send_message(chat_id, "Главное меню. Выберите действие на клавиатуре ниже 👇", reply_markup=get_main_keyboard())

    @bot.callback_query_handler(func=lambda call: str(call.message.chat.id) == str(chat_id))
    def handle_callback(call):
        data = call.data
        settings = dict(db.get_user_settings(user_id))
        
        if data == "settings_menu":
            pass
        elif data == "settings_mode":
            new_mode = "LIVE" if settings.get("trading_mode") == "DEMO" else "DEMO"
            db.update_user_settings(user_id, "trading_mode", new_mode)
            settings["trading_mode"] = new_mode
        elif data == "settings_limit":
            new_limit = 0 if settings.get("use_limit_orders", 1) else 1
            db.update_user_settings(user_id, "use_limit_orders", new_limit)
            settings["use_limit_orders"] = new_limit
        elif data == "settings_invert":
            new_invert = 0 if settings.get("invert_signal", 0) else 1
            db.update_user_settings(user_id, "invert_signal", new_invert)
            settings["invert_signal"] = new_invert
        elif data == "settings_notifications":
            new_notifications = 0 if settings.get("telegram_notifications", 1) else 1
            db.update_user_settings(user_id, "telegram_notifications", new_notifications)
            settings["telegram_notifications"] = new_notifications
        elif data == "settings_pair":
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton(text="BTCUSDT", callback_data="set_pair_BTCUSDT"),
                       types.InlineKeyboardButton(text="ETHUSDT", callback_data="set_pair_ETHUSDT"))
            markup.row(types.InlineKeyboardButton(text="SOLUSDT", callback_data="set_pair_SOLUSDT"),
                       types.InlineKeyboardButton(text="BNBUSDT", callback_data="set_pair_BNBUSDT"))
            markup.row(types.InlineKeyboardButton(text="DOGEUSDT", callback_data="set_pair_DOGEUSDT"),
                       types.InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_menu"))
            bot.edit_message_text("Выбор торговой пары:", chat_id, call.message.message_id, reply_markup=markup)
            return
        elif data.startswith("set_pair_"):
            new_pair = data.split("_")[2]
            db.update_user_settings(user_id, "trading_pair", new_pair)
            settings["trading_pair"] = new_pair
            
        markup = make_settings_markup(settings)
        bot.edit_message_text("⚙️ <b>Настройки бота</b>", chat_id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

def process_telegram_updates():
    print("Telegram Bot Manager started (using telebot).")
    
    while True:
        try:
            conn = db.get_db_connection()
            users = conn.execute("SELECT id, telegram_bot_token, telegram_chat_id FROM users").fetchall()
            conn.close()
            
            for user in users:
                user_id = user["id"]
                token = user["telegram_bot_token"]
                chat_id = user["telegram_chat_id"]
                
                if not token or not chat_id:
                    continue
                    
                # Create/Get bot instance
                if token not in _bots:
                    bot = telebot.TeleBot(token, threaded=False)
                    setup_bot(bot, user_id, chat_id)
                    _bots[token] = bot
                else:
                    bot = _bots[token]
                    
                if token not in _bot_offsets:
                    _bot_offsets[token] = 0
                    
                try:
                    # Get updates and process them using telebot handlers
                    # Increase timeout to 3 seconds for slower server networks (e.g. Hugging Face in US)
                    updates = bot.get_updates(offset=_bot_offsets[token], timeout=3)
                    if updates:
                        _bot_offsets[token] = updates[-1].update_id + 1
                        bot.process_new_updates(updates)
                except Exception as ex:
                    # Suppress normal read timeouts to avoid spamming the log console
                    if "Read timed out" not in str(ex):
                        print(f"Error fetching updates for user {user_id}: {ex}")
                    
        except Exception as e:
            print(f"Error in Telegram manager loop: {e}")
            
        time.sleep(2)

_telegram_thread = None

def start_telegram_manager():
    global _telegram_thread
    if _telegram_thread is None or not _telegram_thread.is_alive():
        _telegram_thread = threading.Thread(target=process_telegram_updates, daemon=True)
        _telegram_thread.start()
