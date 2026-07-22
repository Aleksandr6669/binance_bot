import time
import json
import requests
import os
import threading
import math
import hmac
import hashlib
import pandas as pd
import numpy as np
from datetime import datetime

import db
import scalping_ensemble

# Глобальный флаг остановки фоновых потоков
_stop_event = threading.Event()
_simulator_thread = None
_bot_runner_thread = None
LATEST_LIVE_SIGNAL = None

# Хранилище буферов свечей для каждого пользователя: user_id -> deque(maxlen=100)
_user_buffers = {}

# Кеш фильтров символов Binance (LOT_SIZE, stepSize и т.д.)
_symbol_filters = {}

def get_binance_proxies():
    proxy = None
    try:
        settings = db.get_settings()
        if settings and settings.get("use_proxy") == 1 and settings.get("proxy_url"):
            proxy = settings["proxy_url"].strip()
    except Exception:
        pass

    if not proxy:
        proxy = os.environ.get("BINANCE_PROXY") or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")

    if proxy:
        proxy = proxy.strip()
        if not (proxy.startswith("http://") or proxy.startswith("https://") or proxy.startswith("socks5://")):
            proxy = "http://" + proxy

        # Устанавливаем системные переменные окружения, чтобы ВСЕ сетевые библиотеки
        # (requests, httpx, urllib3 и т.д.) автоматически использовали этот прокси
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["http_proxy"] = proxy
        os.environ["https_proxy"] = proxy
        os.environ["ALL_PROXY"] = proxy
        os.environ["all_proxy"] = proxy
        return {
            "http": proxy,
            "https": proxy
        }
    else:
        # Если прокси выключен, сбрасываем системные переменные
        for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
            if k in os.environ and k != "BINANCE_PROXY":
                os.environ.pop(k, None)
        return None

# Кэш свечей и цен для ускорения запросов
_klines_cache = {}
_price_cache = {}
_positions_cache = {}
_open_orders_cache = {}
_balance_cache = {}

# =====================================================================
# 1. ХЕЛПЕРЫ ДЛЯ РАБОТЫ С BINANCE API (ПОДПИСЬ И ФОРМАТИРОВАНИЕ)
# =====================================================================
def get_symbol_filters(symbol, market_type="SPOT"):
    """
    Получает информацию о шаге цены/количества (LOT_SIZE) с Binance и кеширует её.
    """
    symbol = symbol.upper()
    market_type = market_type.upper()
    cache_key = (symbol, market_type)
    if cache_key in _symbol_filters:
        return _symbol_filters[cache_key]
        
    try:
        # Hardcoded fallbacks for BTC and ETH to prevent precision errors
        if "BTC" in symbol:
            return {"stepSize": 0.001, "minQty": 0.001, "tickSize": 0.1}
        elif "ETH" in symbol:
            return {"stepSize": 0.001, "minQty": 0.001, "tickSize": 0.01}
    except Exception:
        pass

    try:
        use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo" if market_type == "FUTURES" else (
            "https://api.binance.us/api/v3/exchangeInfo" if use_us else "https://api.binance.com/api/v3/exchangeInfo"
        )
        res = requests.get(url, params={"symbol": symbol}, timeout=10, proxies=get_binance_proxies())
        if res.status_code == 200:
            data = res.json()
            sym_info = data["symbols"][0]
            filters = {}
            for f in sym_info["filters"]:
                if f["filterType"] in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                    filters["stepSize"] = float(f["stepSize"])
                    filters["minQty"] = float(f["minQty"])
                elif f["filterType"] == "PRICE_FILTER":
                    filters["tickSize"] = float(f["tickSize"])
            _symbol_filters[cache_key] = filters
            return filters
    except Exception as e:
        print(f"Error fetching exchange info for {symbol} ({market_type}): {e}")
    return None

def format_quantity(symbol, qty, market_type="SPOT"):
    """
    Форматирует количество актива в соответствии с шагом stepSize биржи Binance,
    чтобы избежать ошибок округления при отправке ордеров.
    """
    filters = get_symbol_filters(symbol, market_type)
    if not filters:
        return round(qty, 4)
    step_size = filters.get("stepSize", 0.0001)
    if step_size <= 0:
        return round(qty, 4)
    precision = int(round(-math.log10(step_size))) if step_size < 1.0 else 0
    factor = 10 ** precision
    # Округление вниз, чтобы не превысить лимиты баланса
    return math.floor(qty * factor) / factor

def format_price(symbol, price, market_type="SPOT"):
    """
    Форматирует цену актива в соответствии с шагом tickSize биржи Binance,
    чтобы избежать ошибок точности (например, -1111 Precision is over the maximum).
    """
    filters = get_symbol_filters(symbol, market_type)
    if not filters:
        return round(price, 4)
    tick_size = filters.get("tickSize", 0.01)
    if tick_size <= 0:
        return round(price, 4)
    precision = int(round(-math.log10(tick_size))) if tick_size < 1.0 else 0
    factor = 10 ** precision
    # Округление до ближайшего кратного tickSize
    return round(price * factor) / factor

def send_signed_binance_request(api_key, api_secret, method, endpoint, params=None, market_type="SPOT"):
    """
    Отправляет подписанный HMAC-SHA256 запрос к приватному API Binance.
    """
    if not params:
        params = {}
    params['timestamp'] = int(time.time() * 1000)
    
    # Сборка строки параметров для подписи
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    params['signature'] = signature
    
    use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
    base_url = "https://fapi.binance.com" if market_type.upper() == "FUTURES" else (
        "https://api.binance.us" if use_us else "https://api.binance.com"
    )
    url = f"{base_url}{endpoint}"
    headers = {
        'X-MBX-APIKEY': api_key
    }
    
    if method.upper() == 'POST':
        res = requests.post(url, headers=headers, params=params, timeout=10, proxies=get_binance_proxies())
    else:
        res = requests.get(url, headers=headers, params=params, timeout=10, proxies=get_binance_proxies())
        
    return res.json()

def set_futures_leverage(api_key, api_secret, symbol, leverage):
    """
    Устанавливает плечо (leverage) для фьючерсного контракта на Binance.
    Binance требует вызова /fapi/v1/leverage перед размещением ордера.
    leverage: целое число от 1 до 125.
    """
    leverage = max(1, min(125, int(leverage)))
    params = {
        "symbol": symbol.upper(),
        "leverage": leverage
    }
    try:
        res = send_signed_binance_request(api_key, api_secret, "POST", "/fapi/v1/leverage", params, "FUTURES")
        if "leverage" in res:
            print(f"[Leverage] Set {leverage}x for {symbol}: OK (maxNotionalValue: {res.get('maxNotionalValue', 'N/A')})")
            return True
        else:
            print(f"[Leverage] Failed to set leverage for {symbol}: {res}")
            return False
    except Exception as e:
        print(f"[Leverage] Error setting leverage for {symbol}: {e}")
        return False

def fetch_binance_balance(market_type="SPOT"):
    """
    Получает реальный баланс пользователя на Binance (в соответствии с котируемым активом, например USDT или USDC).
    Кэширует баланс на 4 секунды для предотвращения банов по лимитам запросов.
    """
    market_type = market_type.upper()
    cache_key = (market_type)
    now = time.time()
    if cache_key in _balance_cache:
        cached_time, cached_bal = _balance_cache[cache_key]
        if now - cached_time < 4.0:
            return cached_bal

    user = db.get_settings()
    if not user:
        return None
        
    api_key = user["binance_api_key"]
    api_secret = user["binance_api_secret"]
    if not api_key or not api_secret:
        return None
        
    # Определяем котируемый актив (по умолчанию USDT, но если пара ETHUSDC - то USDC)
    quote_asset = "USDT"
    settings = db.get_settings()
    if settings:
        pair = settings["trading_pair"].upper()
        if pair.endswith("USDC"):
            quote_asset = "USDC"
        elif pair.endswith("BUSD"):
            quote_asset = "BUSD"
        elif pair.endswith("BTC"):
            quote_asset = "BTC"
        
    try:
        balance_val = 0.0
        if market_type == "FUTURES":
            endpoint = "/fapi/v2/balance"
            res = send_signed_binance_request(api_key, api_secret, "GET", endpoint, {}, "FUTURES")
            if isinstance(res, list):
                for item in res:
                    if item.get("asset") == quote_asset:
                        balance_val = float(item.get("balance", 0.0))
                        break
        else:
            endpoint = "/api/v3/account"
            res = send_signed_binance_request(api_key, api_secret, "GET", endpoint, {}, "SPOT")
            balances = res.get("balances", [])
            for item in balances:
                if item.get("asset") == quote_asset:
                    balance_val = float(item.get("free", 0.0))
                    break
        
        _balance_cache[cache_key] = (now, balance_val)
        return balance_val
    except Exception as e:
        print(f"Error fetching Binance balance  ({quote_asset}): {e}")
        # Return last cached balance if available
        if cache_key in _balance_cache:
            return _balance_cache[cache_key][1]
        return None

def fetch_live_positions(market_type="SPOT"):
    """
    Получает активные позиции пользователя напрямую с Binance.
    Для FUTURES возвращает список открытых позиций с реальным PnL и ценой входа.
    Кэширует позиции на 3 секунды.
    """
    market_type = market_type.upper()
    cache_key = (market_type)
    now = time.time()
    if cache_key in _positions_cache:
        cached_time, cached_pos = _positions_cache[cache_key]
        if now - cached_time < 3.0:
            return cached_pos

    user = db.get_settings()
    if not user:
        return []
        
    api_key = user["binance_api_key"]
    api_secret = user["binance_api_secret"]
    if not api_key or not api_secret:
        return []
        
    try:
        positions = []
        if market_type == "FUTURES":
            endpoint = "/fapi/v2/positionRisk"
            res = send_signed_binance_request(api_key, api_secret, "GET", endpoint, {}, "FUTURES")
            if isinstance(res, list):
                for pos in res:
                    amt = float(pos.get("positionAmt", 0.0))
                    if amt != 0:
                        positions.append({
                            "id": pos.get("symbol"), # unique identifier
                            "pair": pos.get("symbol"),
                            "side": "BUY" if amt > 0 else "SELL",
                            "entry_price": float(pos.get("entryPrice", 0.0)),
                            "amount": abs(amt),
                            "unrealized_pnl": float(pos.get("unrealizedProfit", 0.0)),
                            "leverage": int(pos.get("leverage", 1)),
                            "status": "ACTIVE",
                            "trading_mode": "LIVE",
                            "market_type": "FUTURES"
                        })
        _positions_cache[cache_key] = (now, positions)
        return positions
    except Exception as e:
        print(f"Error fetching live positions: {e}")
        # Return last cached positions if available
        if cache_key in _positions_cache:
            return _positions_cache[cache_key][1]
        return []

def fetch_live_open_orders(market_type="SPOT"):
    """
    Получает открытые лимитные ордера пользователя напрямую с Binance.
    Кэширует открытые ордера на 4 секунды.
    """
    market_type = market_type.upper()
    cache_key = (market_type)
    now = time.time()
    if cache_key in _open_orders_cache:
        cached_time, cached_ord = _open_orders_cache[cache_key]
        if now - cached_time < 4.0:
            return cached_ord

    user = db.get_settings()
    if not user:
        return []
        
    api_key = user["binance_api_key"]
    api_secret = user["binance_api_secret"]
    if not api_key or not api_secret:
        return []
        
    try:
        endpoint = "/fapi/v1/openOrders" if market_type == "FUTURES" else "/api/v3/openOrders"
        res = send_signed_binance_request(api_key, api_secret, "GET", endpoint, {}, market_type)
        orders = []
        if isinstance(res, list):
            for o in res:
                orders.append({
                    "id": o.get("orderId"),
                    "pair": o.get("symbol"),
                    "side": o.get("side"),
                    "entry_price": float(o.get("price", 0.0)),
                    "amount": float(o.get("origQty", 0.0)),
                    "status": "PENDING",
                    "trading_mode": "LIVE",
                    "market_type": market_type
                })
        _open_orders_cache[cache_key] = (now, orders)
        return orders
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        # Return last cached open orders if available
        if cache_key in _open_orders_cache:
            return _open_orders_cache[cache_key][1]
        return []

# =====================================================================
# 2. РАБОТА С СИГНАЛАМИ И ОРДЕРАМИ (ДЕМО + РЕАЛ)
# =====================================================================
def resolve_order_size(order_size_setting, trading_mode, market_type="SPOT"):
    """
    Разрешает настройку размера ордера (которая может быть числом или строкой вроде '50%')
    в абсолютное значение USDT.
    """
    user = db.get_settings()
    if not user:
        return 100.0
        
    try:
        if isinstance(order_size_setting, str) and "%" in order_size_setting:
            pct = float(order_size_setting.replace("%", "").strip()) / 100.0
            if trading_mode == "LIVE":
                balance = fetch_binance_balance(market_type)
                if balance is None or balance <= 0:
                    print(f"LIVE balance is zero or none, falling back to $100.")
                    return 100.0
                return max(5.0, balance * pct)
            else:
                return max(5.0, user["demo_balance"] * pct)
        else:
            return float(order_size_setting)
    except Exception as e:
        print(f"Error resolving order size '{order_size_setting}': {e}. Falling back to $100.")
        return 100.0

def place_scalping_order(pair, entry_price, trading_mode, size_usdt, market_type="SPOT", leverage=1, atr=None, side="BUY", prob=None, pred_change_1m=None):
    """
    Размещает лимитный или рыночный ордер в Демо-режиме или в реальном режиме на Binance.
    leverage применяется только для FUTURES (1-125x).
    """
    user = db.get_settings()
    if not user:
        return

    if market_type.upper() != "FUTURES":
        leverage = 1
    leverage = max(1, min(125, int(leverage)))

    side = side.upper()
    settings_dict = dict(db.get_settings())
    use_ai_limit_price = settings_dict.get("use_ai_limit_price", 0)

    if use_ai_limit_price and pred_change_1m is not None and abs(pred_change_1m) > 0:
        # 🤖 ИИ сам вычисляет оптимальный отступ лимитного ордера на основе прогноза DLinear (1m)
        predicted_move = entry_price * abs(pred_change_1m)
        min_offset = entry_price * 0.0005  # минимум 0.05%
        limit_offset = max(min_offset, predicted_move * 0.5)

        offset_tp = max(entry_price * 0.003, predicted_move * 2.0)
        offset_sl = max(entry_price * 0.0015, predicted_move * 1.0)
    else:
        # ⚙️ Фиксированный процентный отступ из настроек пользователя (по умолчанию 1.0%)
        limit_offset_pct = float(settings_dict.get("limit_offset_pct", 1.0) or 1.0)
        limit_offset = entry_price * (limit_offset_pct / 100.0)

        if atr and atr > 0:
            offset_tp = 4.0 * atr
            offset_sl = 2.0 * atr
        else:
            offset_tp = entry_price * 0.006
            offset_sl = entry_price * 0.003

    # Decide order type based purely on user settings
    use_market = not bool(use_limit_orders)

    # Calculate initial TP/SL based on market price
    if side == "BUY":
        limit_price = entry_price - limit_offset
        tp = entry_price + offset_tp
        sl = entry_price - offset_sl
    else:
        limit_price = entry_price + limit_offset
        tp = entry_price - offset_tp
        sl = entry_price + offset_sl

    use_trailing_stop = settings_dict.get("use_trailing_stop", 1)
    timeframe = settings_dict.get("timeframe", "1m")
    if use_trailing_stop:
        tp = None  # Remove take profit if trailing is active

    notional = size_usdt * leverage
    amount = notional / entry_price

    if trading_mode == "LIVE":
        api_key = user["binance_api_key"]
        api_secret = user["binance_api_secret"]
        if not api_key or not api_secret:
            print(f"LIVE mode enabled but API keys are missing!")
            send_notification(
                "⚠️ <b>[LIVE Mode]</b> Торговля заблокирована: укажите API Key и Secret в настройках!"
            )
            return

        if market_type.upper() == "FUTURES":
            set_futures_leverage(api_key, api_secret, pair, leverage)

        qty = format_quantity(pair, amount, market_type)
        endpoint = "/fapi/v1/order" if market_type.upper() == "FUTURES" else "/api/v3/order"

        if use_market:
            print(f"Placing LIVE Binance MARKET {side} order  - {pair} (Qty: {qty}, Market: {market_type}, Leverage: {leverage}x)")
            params = {
                "symbol": pair.upper(),
                "side": side,
                "type": "MARKET",
                "quantity": qty
            }
            try:
                res_data = send_signed_binance_request(api_key, api_secret, "POST", endpoint, params, market_type)
                if "orderId" in res_data:
                    binance_order_id = res_data["orderId"]
                    execution_price = entry_price
                    if "price" in res_data and float(res_data["price"]) > 0:
                        execution_price = float(res_data["price"])
                    elif "avgPrice" in res_data and float(res_data["avgPrice"]) > 0:
                        execution_price = float(res_data["avgPrice"])
                    elif "fills" in res_data and res_data["fills"]:
                        total_qty = sum(float(f["qty"]) for f in res_data["fills"])
                        if total_qty > 0:
                            execution_price = sum(float(f["price"]) * float(f["qty"]) for f in res_data["fills"]) / total_qty
                    
                    if side == "BUY":
                        tp = execution_price + offset_tp
                        sl = execution_price - offset_sl
                    else:
                        tp = execution_price - offset_tp
                        sl = execution_price + offset_sl

                    if use_trailing_stop:
                        tp = None

                    db.create_order(
                        pair=pair,
                        side=side,
                        entry_price=execution_price,
                        stop_loss=sl,
                        take_profit=tp,
                        amount=qty,
                        size_usdt=size_usdt,
                        trading_mode="LIVE",
                        market_type=market_type,
                        leverage=leverage,
                        status="ACTIVE",
                        trailing_distance=offset_sl,
                        timeframe=timeframe
                    )
                    lev_str = f" | Плечо: {leverage}x" if market_type.upper() == "FUTURES" else ""
                    tp_str = f"${tp:,.4f}" if tp is not None else "Не задан (Трейлинг-стоп)"
                    sl_str = f"${sl:,.4f}" if sl is not None else "Не задан"
                    send_notification(
                        f"🟢 <b>[LIVE Mode] Рыночный ордер исполнен на Binance ({market_type})</b>\n\n"
                        f"🚀 Сделка: <b>{side}</b> на <b>{pair}</b>{lev_str}\n"
                        f"• Кол-во: {qty}\n"
                        f"• Цена входа: ${execution_price:,.4f}\n"
                        f"• Stop Loss: {sl_str}\n"
                        f"• Take Profit: {tp_str}\n"
                        f"• Order ID: <code>{binance_order_id}</code>"
                    )
                else:
                    err_msg = res_data.get("msg", "Unknown error")
                    print(f"Binance LIVE Order Error: {res_data}")
                    send_notification(
                        f"⚠️ <b>[LIVE Mode] Ошибка создания рыночного ордера на Binance ({market_type})</b>\n\nКод: {err_msg}"
                    )
            except Exception as e:
                print(f"Error placing LIVE Binance market order: {e}")
                send_notification(
                    f"⚠️ <b>[LIVE Mode] Ошибка сети при создании рыночного ордера на Binance ({market_type})</b>\n\nДетали: {str(e)}"
                )
        else:
            # LOCAL PENDING LIMIT ORDER (Virtual Limit)
            try:
                if use_trailing_stop:
                    tp = None

                db.create_order(
                    pair=pair,
                    side=side,
                    entry_price=limit_price,
                    stop_loss=sl,
                    take_profit=tp,
                    amount=amount, # use nominal amount for local limit order
                    size_usdt=size_usdt,
                    trading_mode="LIVE",
                    market_type=market_type,
                    leverage=leverage,
                    status="PENDING",
                    trailing_distance=offset_sl,
                    timeframe=timeframe
                )
                lev_str = f" | Плечо: {leverage}x" if market_type.upper() == "FUTURES" else ""
                tp_str = f"${tp:,.4f}" if tp is not None else "Не задан (Трейлинг-стоп)"
                sl_str = f"${sl:,.4f}" if sl is not None else "Не задан"
                send_notification(
                    f"🟢 <b>[LIVE Mode] Локальный лимитный ордер выставлен в боте ({market_type})</b>\n\n"
                    f"🚀 Сделка: <b>{side}</b> на <b>{pair}</b>{lev_str}\n"
                    f"• Кол-во: {qty}\n"
                    f"• Цена лимита: ${limit_price:,.4f}\n"
                    f"• Stop Loss: {sl_str}\n"
                    f"• Take Profit: {tp_str}\n"
                    f"• Ордер будет активирован на бирже при пересечении цены."
                )
            except Exception as e:
                print(f"Error creating local LIVE limit order: {e}")
                send_notification(
                    f"⚠️ <b>[LIVE Mode] Ошибка создания локального лимитного ордера</b>\n\nДетали: {str(e)}"
                )

    else:  # DEMO mode
        if use_market:
            active_orders = db.get_active_orders()
            locked_collateral = sum(float(o["size_usdt"]) for o in active_orders)
            free_margin = user["demo_balance"] - locked_collateral
            if free_margin < size_usdt:
                send_notification(
                    f"⚠️ <b>[DEMO Mode] Недостаточно свободных средств!</b>\n\n"
                    f"Свободно: ${free_margin:,.2f} | Требуется: ${size_usdt:,.2f}"
                )
                return
            # TP/SL is already calculated relative to entry_price (market price)
            db.create_order(
                pair=pair,
                side=side,
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                amount=amount,
                size_usdt=size_usdt,
                trading_mode="DEMO",
                market_type=market_type,
                leverage=leverage,
                status="ACTIVE",
                trailing_distance=offset_sl,
                timeframe=timeframe
            )
            lev_str = f" | Плечо: {leverage}x" if market_type.upper() == "FUTURES" else ""
            tp_str = f"${tp:,.4f}" if tp is not None else "Не задан (Трейлинг-стоп)"
            sl_str = f"${sl:,.4f}" if sl is not None else "Не задан"
            send_notification(
                f"🟢 <b>[DEMO Mode] Рыночный ордер исполнен ({market_type})</b>\n\n"
                f"🚀 Имитация {side} на <b>{pair}</b>!{lev_str}\n"
                f"• Цена входа: ${entry_price:,.4f}\n"
                f"• Stop Loss: {sl_str}\n"
                f"• Take Profit: {tp_str}"
            )
        else:
            # Для DEMO-режима PENDING ордер создаётся без списания баланса.
            # Коллатерал (size_usdt) будет вычитаться только при срабатывании (активации) ордера
            # в функции db.activate_pending_order(), чтобы избежать двойного списания.
            db.create_order(
                pair=pair,
                side=side,
                entry_price=limit_price,
                stop_loss=sl,
                take_profit=tp,
                amount=amount,
                size_usdt=size_usdt,
                trading_mode="DEMO",
                market_type=market_type,
                leverage=leverage,
                status="PENDING",
                trailing_distance=offset_sl,
                timeframe=timeframe
            )
            lev_str = f" | Плечо: {leverage}x" if market_type.upper() == "FUTURES" else ""
            tp_str = f"${tp:,.4f}" if tp is not None else "Не задан (Трейлинг-стоп)"
            sl_str = f"${sl:,.4f}" if sl is not None else "Не задан"
            send_notification(
                f"🟢 <b>[DEMO Mode] Лимитный ордер выставлен ({market_type})</b>\n\n"
                f"🚀 Имитация {side} на <b>{pair}</b>!{lev_str}\n"
                f"• Цена лимита: ${limit_price:,.4f}\n"
                f"• Stop Loss: {sl_str}\n"
                f"• Take Profit: {tp_str}"
            )


def close_live_position(pair, amount, market_type="SPOT", order_side="BUY"):
    """
    Выполняет реальную рыночную продажу или покупку на Binance для закрытия позиции.
    """
    user = db.get_settings()
    if not user:
        return False
        
    api_key = user["binance_api_key"]
    api_secret = user["binance_api_secret"]
    if not api_key or not api_secret:
        return False
        
    # Если открывали BUY, закрываем через SELL. Если открывали SELL, закрываем через BUY.
    close_side = "SELL" if order_side.upper() == "BUY" else "BUY"
    
    qty = format_quantity(pair, amount, market_type)
    print(f"Placing LIVE Binance Market {close_side} order to close position  - {pair} (Qty: {qty}, Market: {market_type})")
    
    params = {
        "symbol": pair.upper(),
        "side": close_side,
        "type": "MARKET",
        "quantity": qty
    }
    
    endpoint = "/fapi/v1/order" if market_type.upper() == "FUTURES" else "/api/v3/order"
    
    try:
        res = send_signed_binance_request(api_key, api_secret, "POST", endpoint, params, market_type)
        if "orderId" in res:
            return True
        else:
            print(f"Failed to place Binance LIVE close order: {res}")
            return False
    except Exception as e:
        print(f"Error placing Binance LIVE close order: {e}")
        return False

def liquidate_order_manually(order_id):
    """
    Закрывает ордер вручную по запросу пользователя.
    """
    orders = db.get_active_orders()
    target_order = next((o for o in orders if str(o["id"]) == str(order_id)), None)
    
    if not target_order:
        print(f"Order {order_id} not found or already closed.")
        return False
        
    pair = target_order["pair"]
    market_type = target_order.get("market_type", "SPOT")
    trading_mode = target_order.get("trading_mode", "DEMO")
    amount = float(target_order["amount"])
    entry = float(target_order["entry_price"])
    side = target_order["side"]

    current_price = fetch_current_price(pair, market_type)
    if current_price is None or current_price <= 0:
        print(f"Cannot liquidate order {order_id}: unable to fetch current price for {pair}.")
        return False
        
    # Расчет PnL
    if side == "BUY":
        pnl = amount * (current_price - entry)
    else:
        pnl = amount * (entry - current_price)
        
    if trading_mode == "LIVE":
        success = close_live_position(pair, amount, market_type, side)
        if not success:
            print(f"Failed to close LIVE position for order {order_id}.")
            return False
            
    # Сохраняем в БД
    db.close_order(order_id, status="CLOSED_MANUAL", close_price=current_price, pnl=pnl)
    print(f"Order {order_id} manually liquidated at {current_price} with PnL {pnl:.2f}")
    
    # Отправляем уведомление
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    send_notification(f"{pnl_emoji} <b>Ордер закрыт вручную</b>\n\nПара: {pair}\nТип: {side}\nВход: ${entry:,.4f}\nВыход: ${current_price:,.4f}\nPnL: ${pnl:,.2f}")
    return True


# =====================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
# =====================================================================
def fetch_binance_klines(symbol, timeframe, limit=100, market_type="SPOT"):
    """Запрашивает публичную историю свечей с Binance API (Spot или Futures) с кешированием."""
    symbol = symbol.upper()
    market_type = market_type.upper()
    
    cache_key = (symbol, timeframe, limit, market_type)
    now = time.time()
    if cache_key in _klines_cache:
        cached_time, cached_data = _klines_cache[cache_key]
        if now - cached_time < 1.0:
            return cached_data
            
    use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
    url = "https://fapi.binance.com/fapi/v1/klines" if market_type == "FUTURES" else (
        "https://api.binance.us/api/v3/klines" if use_us else "https://api.binance.com/api/v3/klines"
    )
    params = {
        "symbol": symbol,
        "interval": timeframe,
        "limit": limit
    }
    try:
        res = requests.get(url, params=params, timeout=10, proxies=get_binance_proxies())
        res.raise_for_status()
        data = res.json()
        _klines_cache[cache_key] = (now, data)
        return data
    except Exception as e:
        print(f"Error fetching klines for {symbol} ({market_type}): {e}")
        # Search for any cached data for this symbol, timeframe, and market_type
        for k_key, val in _klines_cache.items():
            if k_key[0] == symbol and k_key[1] == timeframe and k_key[3] == market_type:
                return val[1]
        raise e

def fetch_current_price(symbol, market_type="SPOT"):
    """Запрашивает текущую тикерную цену с Binance API (Spot или Futures) с кешированием на 1.0 секунду."""
    symbol = symbol.upper()
    market_type = market_type.upper()
    cache_key = (symbol, market_type)
    now = time.time()
    
    if cache_key in _price_cache:
        cached_time, cached_price = _price_cache[cache_key]
        if now - cached_time < 0.3:
            return cached_price
            
    try:
        use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
        url = "https://fapi.binance.com/fapi/v1/ticker/price" if market_type == "FUTURES" else (
            "https://api.binance.us/api/v3/ticker/price" if use_us else "https://api.binance.com/api/v3/ticker/price"
        )
        params = {"symbol": symbol}
        res = requests.get(url, params=params, timeout=10, proxies=get_binance_proxies())
        res.raise_for_status()
        price = float(res.json()["price"])
        _price_cache[cache_key] = (now, price)
        return price
    except Exception as e:
        print(f"Error updating price for {symbol} ({market_type}): {e}")
        # Return last cached price if available
        if cache_key in _price_cache:
            return _price_cache[cache_key][1]
        # Hardcoded fallbacks if completely offline/blocked
        if "BTC" in symbol:
            return 60000.0
        elif "ETH" in symbol:
            return 1650.0
        return 1.0

def send_notification(message):
    """
    Выводит уведомление в консоль (логирование событий терминала).
    """
    clean_msg = message.replace("<b>", "").replace("</b>", "").replace("🟢", "").replace("🔴", "").replace("🔵", "").replace("⚠️", "").replace("🚀", "")
    print(f"[NOTIFICATION] {clean_msg.strip()}")

# Совместимость со старыми вызовами
send_notification = send_notification


def check_and_reload_models():
    """
    Проверяет, соответствуют ли загруженные в память модели текущей паре и таймфрейму в настройках.
    Если нет, загружает их с диска (или обучает на синтетических данных и сохраняет).
    """
    settings = db.get_settings()
    if not settings:
        return
    
    pair = (dict(settings).get("trading_pair", "BTCUSDT") or "BTCUSDT").upper()
    timeframe = dict(settings).get("timeframe", "1m") or "1m"
    
    current_pair = getattr(scalping_ensemble, "current_model_pair", None)
    current_tf = getattr(scalping_ensemble, "current_model_timeframe", None)
    
    if current_pair != pair or current_tf != timeframe:
        print(f"\n=== [ИИ] ОБНАРУЖЕНО ИЗМЕНЕНИЕ НАСТРОЕК: ПЕРЕКЛЮЧЕНИЕ С {current_pair} ({current_tf}) НА {pair} ({timeframe}) ===")
        # 1. Попытка загрузить модели с диска
        if not scalping_ensemble.load_models_from_disk(pair, timeframe):
            # 2. Если моделей нет на диске, запускаем виртуальное ускоренное обучение на реальной истории рынка
            scalping_ensemble.bootstrap_virtual_training(pair, timeframe)
        # Модели с диска уже обучены — дополнительный ретрейн не нужен.
        # Плановый ретрейн произойдёт через RETRAIN_INTERVAL (30 мин).
        print(f"=== [ИИ] МОДЕЛИ УСПЕШНО НАСТРОЕНЫ ДЛЯ РАБОТЫ С {pair} ({timeframe}) ===\n")


def get_ai_trailing_distance_pct(pair, timeframe, market_type):
    """
    Рассчитывает динамический отступ для трейлинг-стопа на базе ИИ.
    """
    check_and_reload_models()
    try:
        klines = fetch_binance_klines(pair, timeframe, limit=100, market_type=market_type)
        if not klines:
            return None
        df = pd.DataFrame([{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
            "cvd": np.random.normal(0, 50.0)
        } for k in klines])

        df = scalping_ensemble.calculate_indicators(df)
        current_row = df.iloc[-1]
        
        # DLinear prediction
        closes_60 = df["close"].iloc[-60:].values
        last_close = closes_60[-1]
        x_norm = closes_60 / last_close - 1.0
        
        if scalping_ensemble.HAS_TORCH:
            import torch
            with torch.no_grad():
                x_t = torch.tensor(x_norm, dtype=torch.float32).view(1, 60, 1)
                dlinear_pred = scalping_ensemble.dlinear_model(x_t).numpy().flatten()
        else:
            dlinear_pred = scalping_ensemble.dlinear_model.forward(x_norm)
            
        pred_change_1m = dlinear_pred[0]
        pred_change_2m = dlinear_pred[1]
        
        current_hour = pd.to_datetime(float(klines[-1][0]), unit='ms').hour / 24.0
        
        features = np.array([
            current_row["rsi_norm"],
            current_row["atr_pct"],
            current_row["obi"],
            current_row["cvd"],
            pred_change_1m,
            pred_change_2m,
            current_hour,
            current_row.get("vwap_dist", 0.0),
            current_row.get("macd_hist_norm", 0.0)
        ])
        
        # Predict dynamic percentage (e.g. standard deviation)
        vol_pct = scalping_ensemble.predict_ai_trailing_distance(features)
        
        # Use 2.5 standard deviations for a safe but dynamic trailing distance
        trailing_distance_pct = vol_pct * 2.5 * 100.0 # convert to percentage for calculation
        return max(0.1, min(5.0, trailing_distance_pct)) # clamp between 0.1% and 5.0% for safety
    except Exception as e:
        print(f"Error calculating AI trailing stop: {e}")
        return None


# =====================================================================
# 4. ЦИКЛ СКАЛЬПИНГА ПОЛЬЗОВАТЕЛЯ
# =====================================================================
def run_user_scalping_cycle():
    """
    Запускает 1-минутный инференс моделей DLinear + LightGBM/NumPy
    для конкретного пользователя по его торговой паре.
    """
    check_and_reload_models()
    user = db.get_settings()
    settings = db.get_settings()
    if not user or not settings or not settings["bot_enabled"]:
        return
        
    pair = settings["trading_pair"]
    timeframe = settings["timeframe"] or "1m"
    trading_mode = settings["trading_mode"] or "DEMO"
    market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
    futures_leverage = dict(settings).get("futures_leverage", 10) or 10
    order_size_usdt = resolve_order_size(settings["order_size_usdt"], trading_mode, market_type)
    
    # Проверка, нет ли уже открытой сделки по этой паре у пользователя
    active_orders = db.get_active_orders()
    active_pairs = [o["pair"].upper() for o in active_orders]
    if pair.upper() in active_pairs:
        return
        
    try:
        # Запрашиваем 100 свечей с Binance
        klines = fetch_binance_klines(pair, timeframe, limit=100, market_type=market_type)
        
        # Сохраняем последнюю свечу в БД для будущего самообучения
        if klines:
            last_k = klines[-1]
            db.save_market_candle(pair, timeframe, last_k[0], last_k[1], last_k[2], last_k[3], last_k[4], last_k[5])
        
        # Подготовка DataFrame
        df = pd.DataFrame([{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            # Симулируем фичи стакана и CVD в реальном времени
            "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
            "cvd": np.random.normal(0, 50.0)
        } for k in klines])
        
        # Считаем индикаторы
        df = scalping_ensemble.calculate_indicators(df)
        
        current_row = df.iloc[-1]
        current_close = current_row["close"]
        current_rsi_norm = current_row["rsi_norm"]
        current_atr_pct = current_row["atr_pct"]
        current_atr = current_row["atr"]
        current_obi = current_row["obi"]
        current_cvd = current_row["cvd"]
        
        # Фильтр волатильности
        hour_window = min(60, len(df))
        mean_hourly_atr = df["atr"].iloc[-hour_window:].mean()
        
        vol_blocked = current_atr > 4.0 * mean_hourly_atr

        # Инициализируем действие заранее, чтобы любой сбой во время инференса
        # не привёл к UnboundLocalError при формировании результата.
        action = "HOLD"
        reason = "Ожидание сигнала."
            
        # Подготовка данных для DLinear
        closes_60 = df["close"].iloc[-60:].values
        last_close = closes_60[-1]
        x_norm = closes_60 / last_close - 1.0
        
        # Инференс DLinear
        if scalping_ensemble.HAS_TORCH:
            import torch
            with torch.no_grad():
                x_t = torch.tensor(x_norm, dtype=torch.float32).view(1, 60, 1)
                dlinear_pred = scalping_ensemble.dlinear_model(x_t).numpy().flatten()
        else:
            dlinear_pred = scalping_ensemble.dlinear_model.forward(x_norm)
            
        pred_change_1m = dlinear_pred[0]
        pred_change_2m = dlinear_pred[1]
        
        # Инференс Классификатора
        current_time_ms = float(klines[-1][0])
        current_hour = pd.to_datetime(current_time_ms, unit='ms').hour / 24.0

        features = np.array([[
            current_rsi_norm,
            current_atr_pct,
            current_obi,
            current_cvd,
            pred_change_1m,
            pred_change_2m,
            current_hour,
            current_row.get("vwap_dist", 0.0),
            current_row.get("macd_hist_norm", 0.0)
        ]])
        
        prob = scalping_ensemble.classifier_model.predict(features)[0]
        
        # Считываем порог вероятности из настроек пользователя (учитываем 0.0)
        raw_thresh = dict(settings).get("min_probability_threshold")
        threshold = float(raw_thresh) if raw_thresh is not None else 0.65
        
        # Инициализируем состояние сигнала заранее, чтобы любые исключения во время инференса
        # не привели к UnboundLocalError при формировании результата.
        action = "HOLD"
        reason = f"Вероятность классификатора: {prob:.4f} <= {threshold:.2f}."
        if vol_blocked:
            action = "HOLD (VOLATILITY BLOCKED)"
            reason = f"Новостной сквиз: ATR ({current_atr:.4f}) превысил часовой лимит ({4.0*mean_hourly_atr:.4f})."
        elif prob > threshold:
            action = "BUY"
            reason = f"Сигнал на покупку! Вероятность {prob:.4f} > {threshold:.2f}. Фильтр волатильности в норме."
            
        indicators_str = f"RSI: {current_rsi_norm*100:.1f}, ATR%: {current_atr_pct*100:.4f}%, OBI: {current_obi:.3f}, CVD: {current_cvd:.2f}"
        stage1_out = f"1-Minute Scalping Analysis.\nVolatility Filter: {'BLOCKED' if vol_blocked else 'OK'}\nHourly Average ATR: {mean_hourly_atr:.4f}\nCurrent ATR: {current_atr:.4f}"
        stage2_out = f"DLinear Predictions:\n- t+1 Close Change: {pred_change_1m*100:+.4f}%\n- t+2 Close Change: {pred_change_2m*100:+.4f}%\n\nClassifier Success Probability: {prob*100:.2f}%"
        stage3_out = json.dumps({
            "action": "BUY" if action == "BUY" else "HOLD",
            "price": current_close,
            "probability": prob,
            "reason": reason
        }, indent=2, ensure_ascii=False)
        
        # Persist analysis log with dedup/timestamp guard to avoid DB spam
        try:
            db.add_analysis_log_if_needed(
                pair=pair,
                indicators_summary=indicators_str,
                stage1=stage1_out,
                stage2=stage2_out,
                stage3=stage3_out,
                min_interval_seconds=30
            )
        except Exception as e:
            print(f"Failed to persist analysis log (non-fatal): {e}")
        
        if vol_blocked:
            print(f"[VOLATILITY BLOCKED] ({pair}) - current ATR: {current_atr:.4f} > 4x Hourly Avg ({mean_hourly_atr:.4f})")
            return
            
        print(f"Scalper Bot for Pair: {pair} - Close: {current_close:.2f} - Prob: {prob:.4f}")
        
    except Exception as e:
        print(f"Error in run_user_scalping_cycle : {e}")


def evaluate_market_signal(persist_log=False, place_order=False):
    """Оценивает текущий сигнал нейросети без побочных эффектов, если это не требуется."""
    # Ensure correct models are loaded for the current symbol & timeframe
    check_and_reload_models()

    user = db.get_settings()
    settings = db.get_settings()
    if not user or not settings:
        return {"success": False, "error": "User settings not found"}

    pair = settings["trading_pair"]
    timeframe = settings["timeframe"] or "1m"
    trading_mode = settings["trading_mode"] or "DEMO"
    market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
    futures_leverage = dict(settings).get("futures_leverage", 10) or 10
    order_size_usdt = resolve_order_size(settings["order_size_usdt"], trading_mode, market_type)

    active_order = None
    has_existing_pair = False
    
    # Clean up duplicate active/pending orders in SQLite: keep only the latest one and cancel others
    try:
        conn = db.get_db_connection()
        db_orders = conn.execute(
            "SELECT id FROM orders WHERE pair = ? AND (status = 'ACTIVE' OR status = 'PENDING') ORDER BY created_at DESC",
            (pair,)
        ).fetchall()
        if len(db_orders) > 1:
            ids_to_cancel = [row["id"] for row in db_orders[1:]]
            for oid in ids_to_cancel:
                conn.execute("UPDATE orders SET status = 'CANCELLED', closed_at = CURRENT_TIMESTAMP WHERE id = ?", (oid,))
            conn.commit()
        conn.close()
        db.upload_db_to_hf_async()
    except Exception as cleanup_ex:
        print(f"Error cleaning up duplicate local orders: {cleanup_ex}")

    if trading_mode == "LIVE":
        # Check real active positions and open orders on Binance
        live_positions = fetch_live_positions(market_type)
        live_open_orders = fetch_live_open_orders(market_type)
        
        # Also check local DB for local pending limit orders
        local_orders = db.get_active_orders()
        
        # If there's an active position on Binance for this pair
        for pos in live_positions:
            if pos["pair"].upper() == pair.upper():
                has_existing_pair = True
                active_order = pos
                break
                
        # If no active position, check if there is a local pending order or Binance open order
        if not has_existing_pair:
            for o in local_orders:
                if o["pair"].upper() == pair.upper() and o["status"] == "PENDING":
                    has_existing_pair = True
                    break
            for o in live_open_orders:
                if o["pair"].upper() == pair.upper():
                    has_existing_pair = True
                    break
    else:
        # DEMO Mode: check local DB active orders
        active_orders = db.get_active_orders()
        for o in active_orders:
            if o["pair"].upper() == pair.upper():
                has_existing_pair = True
                if (o["status"] or "").upper() == "ACTIVE":
                    active_order = o
                    break

    try:
        klines = fetch_binance_klines(pair, timeframe, limit=100, market_type=market_type)
        if klines:
            last_k = klines[-1]
            db.save_market_candle(pair, timeframe, last_k[0], last_k[1], last_k[2], last_k[3], last_k[4], last_k[5])

        df = pd.DataFrame([{
            "time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
            "cvd": np.random.normal(0, 50.0)
        } for k in klines])

        df = scalping_ensemble.calculate_indicators(df)

        current_row = df.iloc[-1]
        current_close = current_row["close"]
        current_rsi_norm = current_row["rsi_norm"]
        current_atr_pct = current_row["atr_pct"]
        current_atr = current_row["atr"]
        current_obi = current_row["obi"]
        current_cvd = current_row["cvd"]

        hour_window = min(60, len(df))
        mean_hourly_atr = df["atr"].iloc[-hour_window:].mean()
        vol_blocked = current_atr > 4.0 * mean_hourly_atr

        trend_direction = "UP"
        mtf_map = {
            "1m": "5m",
            "3m": "15m",
            "5m": "15m",
            "15m": "1h",
            "30m": "2h",
            "1h": "4h",
            "4h": "1d"
        }
        trend_tf = mtf_map.get(timeframe, timeframe)
        try:
            klines_trend = fetch_binance_klines(pair, trend_tf, limit=500, market_type=market_type)
            if len(klines_trend) >= 50:
                closes_trend = pd.Series([float(k[4]) for k in klines_trend])
                ema_50 = closes_trend.ewm(span=50, adjust=False).mean().iloc[-1]
                last_close_val = closes_trend.iloc[-1]
                if last_close_val < ema_50:
                    trend_direction = "DOWN"
        except Exception as te:
            print(f"Error calculating EMA 50 trend filter: {te}")

        closes_60 = df["close"].iloc[-60:].values
        last_close = closes_60[-1]
        x_norm = closes_60 / last_close - 1.0

        # Инициализируем действие заранее, чтобы любой сбой во время инференса
        # не привёл к UnboundLocalError при формировании ответа.
        action = "HOLD"
        reason = "Ожидание сигнала."
        reason2 = ""

        if scalping_ensemble.HAS_TORCH:
            import torch
            with torch.no_grad():
                x_t = torch.tensor(x_norm, dtype=torch.float32).view(1, 60, 1)
                dlinear_pred = scalping_ensemble.dlinear_model(x_t).numpy().flatten()
        else:
            dlinear_pred = scalping_ensemble.dlinear_model.forward(x_norm)

        pred_change_1m = dlinear_pred[0]
        pred_change_2m = dlinear_pred[1]

        # Вычисляем нормированный час суток для фичи времени
        current_time_ms = float(current_row["time"])
        current_hour = pd.to_datetime(current_time_ms, unit='ms').hour / 24.0

        features = np.array([[
            current_rsi_norm,
            current_atr_pct,
            current_obi,
            current_cvd,
            pred_change_1m,
            pred_change_2m,
            current_hour,
            current_row.get("vwap_dist", 0.0),
            current_row.get("macd_hist_norm", 0.0)
        ]])

        prob = float(scalping_ensemble.classifier_model.predict(features)[0])
        raw_thresh = dict(settings).get("min_probability_threshold")
        threshold = float(raw_thresh) if raw_thresh is not None else 0.65
        invert_signal = bool(dict(settings).get("invert_signal", 0))

        action = "HOLD"
        reason = f"Вероятность классификатора:"
        reason2 = f"{prob:.4f} <= {threshold:.2f}."

        if vol_blocked:
            action = "HOLD"
            reason = f"Новостной сквиз: ATR ({current_atr:.4f}) "  
            reason2 = f"превысил часовой лимит ({4.0 * mean_hourly_atr:.4f})."
        elif prob > threshold:
            if trend_direction == "UP":
                action = "BUY"
                reason = f"Сигнал на покупку по тренду! "
                reason2 = f"Вероятность {prob:.4f} > {threshold:.2f}."
            else:
                action = "SELL"
                reason = f"Сигнал на продажу по тренду! "
                reason2 = f"Вероятность {prob:.4f} > {threshold:.2f}."

        if invert_signal and action in ["BUY", "SELL"]:
            action = "BUY" if action == "SELL" else "SELL"
            reason += " Сигнал инвертирован"

        indicators_str = f"RSI: {current_rsi_norm * 100:.1f}, ATR%: {current_atr_pct * 100:.4f}%, Trend: {trend_direction}"
        trend_desc = f"EMA 50 ({trend_tf} MTF)" if trend_tf != timeframe else f"EMA 50 ({timeframe})"
        stage1_out = f"{timeframe} Scalping Analysis.\nVolatility Filter: {'BLOCKED' if vol_blocked else 'OK'}\nHourly Average ATR: {mean_hourly_atr:.4f}\nCurrent ATR: {current_atr:.4f}\n{trend_desc} Trend Filter: {trend_direction}"
        stage2_out = f"DLinear Predictions:\n- t+1 Close Change: {pred_change_1m * 100:+.4f}%\n- t+2 Close Change: {pred_change_2m * 100:+.4f}%\n\nClassifier Success Probability: {prob * 100:.2f}%"

        settings_dict = dict(db.get_settings())
        use_limit_orders = settings_dict.get("use_limit_orders", 1)

        order_type_desc = "None"
        if action in ["BUY", "SELL"]:
            order_type_desc = "LIMIT" if use_limit_orders else "MARKET"

        stage3_out = json.dumps({
            "action": action,
            "price": current_close,
            "probability": prob,
            "reason": reason,
            "reason2": reason2,
            "order_type": order_type_desc
        }, indent=2, ensure_ascii=False)

        if persist_log:
            try:
                db.add_analysis_log_if_needed(
                    pair=pair,
                    indicators_summary=indicators_str,
                    stage1=stage1_out,
                    stage2=stage2_out,
                    stage3=stage3_out,
                    min_interval_seconds=30
                )
            except Exception as e:
                print(f"Failed to persist analysis log (non-fatal): {e}")

        # Stagnation retrain отключён — ретрейн только после убытка и по расписанию (1 раз в час).

        order_msg = "Рекомендация: HOLD (нет сигнала на вход)."
        if vol_blocked:
            order_msg = "Анализ завершен. Вход заблокирован высокой волатильностью."
        elif has_existing_pair:
            use_ai_exit = bool(settings_dict.get("use_ai_exit", 0))
            if use_ai_exit and active_order and action in ["BUY", "SELL"] and action != active_order["side"] and not vol_blocked and prob > threshold:
                entry_price = float(active_order["entry_price"])
                amount = float(active_order["amount"])
                current_side = active_order["side"].upper()
                pnl = (current_close - entry_price) * amount if current_side == "BUY" else (entry_price - current_close) * amount
                if trading_mode == "LIVE":
                    close_live_position(pair, amount, market_type, order_side=current_side)
                closed = db.close_order(active_order["id"], status="CLOSED_MANUAL", close_price=current_close, pnl=pnl)

                # Check if closed in loss
                if pnl < 0:
                    print(f"[LOSS RETRAIN] Position closed in loss due to AI signal switch (PnL: {pnl}). Triggering retraining to adapt.")
                    try:
                        scalping_ensemble.retrain_on_market_history(pair, timeframe)
                    except Exception as re:
                        print(f"Error retraining models after AI exit loss: {re}")

                
                pnl_sign = "+" if pnl >= 0 else ""
                send_notification(
                    f"🔄 <b>[{trading_mode} Mode] Позиция закрыта (смена сигнала ИИ)</b>\n\n"
                    f"Пара: <b>{pair}</b>\n"
                    f"Сделка: {current_side}\n"
                    f"Цена входа: ${entry_price:,.4f}\n"
                    f"Цена закрытия: ${current_close:,.4f}\n"
                    f"Чистый PnL: <b>{pnl_sign}${pnl:,.2f}</b>"
                )
                order_msg = f"Текущая позиция {current_side} по {pair} закрыта из-за смены сигнала."
            else:
                order_msg = f"Позиция по {pair} уже открыта ({active_order['side'] if active_order else 'ожидает'}). Анализ продолжается."
        elif action in ["BUY", "SELL"] and place_order:
            order_type_desc = "лимитный" if use_limit_orders else "рыночный"
            if trading_mode == "LIVE":
                order_msg = f"Размещен LIVE {order_type_desc} ордер {action} на Binance по паре {pair} ({market_type})!"
            else:
                order_msg = f"Размещен DEMO {order_type_desc} ордер {action} по паре {pair} ({market_type})!"
            place_scalping_order(pair, current_close, trading_mode, order_size_usdt, market_type, futures_leverage, current_atr, side=action, prob=prob, pred_change_1m=pred_change_1m)

        # Подготавливаем последний лог для передачи в websocket (не обязательно сохранять в БД)
        created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        latest_log = {
            "stage1_output": stage1_out,
            "stage2_output": stage2_out,
            "stage3_output": stage3_out,
            "created_at": created_at
        }
        global LATEST_LIVE_SIGNAL
        LATEST_LIVE_SIGNAL = latest_log

        return {
            "success": True,
            "action": action,
            "order_msg": order_msg,
            "probability": prob,
            "reason": reason,
            "price": current_close,
            "trend_direction": trend_direction,
            "vol_blocked": bool(vol_blocked),
            "pair": pair,
            "timeframe": timeframe,
            "latest_log": latest_log
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_user_analysis_cycle():
    """
    Запускает цикл инференса и анализа для пользователя.
    Ордер размещается только если автоторговля включена в настройках.
    """
    settings_row = db.get_settings()
    bot_enabled = (settings_row.get("bot_enabled", 0) == 1) if settings_row else False
    
    result = evaluate_market_signal(persist_log=True, place_order=bot_enabled)
    if not result.get("success"):
        return result
    return result


# =====================================================================
# 5. ФОНОВЫЕ ПОТОКИ (MARKET SIMULATOR & BOT RUNNER)
# =====================================================================
def run_market_simulator():
    """
    Фоновый поток проверки TP/SL по активным ордерам.
    В демо-режиме производит расчеты в БД, в реальном — совершает SELL на Binance.
    """
    print("Market simulator thread started.")
    while not _stop_event.is_set():
        try:
            active_orders = db.get_active_orders()
            if not active_orders:
                time.sleep(5)
                continue
                
            # Собираем уникальные символы и типы рынка
            current_prices = {}
            for order in active_orders:
                sym = order["pair"].upper()
                market_type = dict(order).get("market_type", "SPOT") or "SPOT"
                cache_key = (sym, market_type)
                if cache_key not in current_prices:
                    try:
                        current_prices[cache_key] = fetch_current_price(sym, market_type)
                    except Exception as ex:
                        print(f"Error updating price for {sym} ({market_type}): {ex}")
                        
            for order in active_orders:
                pair = order["pair"].upper()
                market_type = dict(order).get("market_type", "SPOT") or "SPOT"
                cache_key = (pair, market_type)
                if cache_key not in current_prices:
                    continue
                    
                price = current_prices[cache_key]
                side = order["side"].upper()
                entry = order["entry_price"]
                sl = order["stop_loss"]
                tp = order["take_profit"]
                amount = order["amount"]
                size_usdt = order["size_usdt"]
                user_id = order["user_id"]
                order_id = order["id"]
                trading_mode = order["trading_mode"] if "trading_mode" in order.keys() else "DEMO"
                
                order_status = dict(order).get("status", "ACTIVE")
                
                # Fetch 1m candle wicks (high/low) to check for triggers on entire candle range
                candle_high = price
                candle_low = price
                try:
                    # Fetch last 2 candles for pair
                    klines = fetch_binance_klines(pair, "1m", limit=2, market_type=market_type)
                    if klines:
                        last_kline = klines[-1]
                        candle_open_time = int(last_kline[0])
                        
                        # Compare with order creation time (UTC string) to avoid retro-active triggering
                        try:
                            from datetime import timezone
                            created_dt = datetime.strptime(order["created_at"], "%Y-%m-%d %H:%M:%S")
                            order_created_ms = int(created_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                        except Exception as dt_ex:
                            order_created_ms = 0
                            print(f"Error parsing order created_at: {dt_ex}")
                            
                        if candle_open_time >= order_created_ms:
                            candle_high = float(last_kline[2])
                            candle_low = float(last_kline[3])
                        else:
                            # Candle open time is before order creation; fallback to current polled price
                            candle_high = price
                            candle_low = price
                except Exception as ex:
                    print(f"Error fetching 1m kline for {pair} trigger check: {ex}")
                    # Skip trigger checks for this order in this loop iteration to prevent false executions on stale data
                    continue
                
                if order_status == "PENDING":
                    # Check limit order activation using candle's high/low (wicks)
                    triggered = False
                    if side == "BUY" and candle_low <= entry:
                        triggered = True
                    elif side == "SELL" and candle_high >= entry:
                        triggered = True
                        
                    if triggered:
                        user = db.get_settings()
                        if trading_mode == "LIVE" and user:
                            # Place real MARKET order on Binance to execute this virtual limit order
                            api_key = user["binance_api_key"]
                            api_secret = user["binance_api_secret"]
                            if api_key and api_secret:
                                # Get leverage from settings
                                u_settings = db.get_settings()
                                u_lev = dict(u_settings).get("futures_leverage", 10) or 10
                                
                                if market_type.upper() == "FUTURES":
                                    set_futures_leverage(api_key, api_secret, pair, u_lev)
                                
                                qty = format_quantity(pair, amount, market_type)
                                endpoint = "/fapi/v1/order" if market_type.upper() == "FUTURES" else "/api/v3/order"
                                params = {
                                    "symbol": pair.upper(),
                                    "side": side,
                                    "type": "MARKET",
                                    "quantity": qty
                                }
                                try:
                                    res_data = send_signed_binance_request(api_key, api_secret, "POST", endpoint, params, market_type)
                                    if "orderId" in res_data:
                                        # Get actual average execution price
                                        exec_price = entry
                                        if "price" in res_data and float(res_data["price"]) > 0:
                                            exec_price = float(res_data["price"])
                                        elif "avgPrice" in res_data and float(res_data["avgPrice"]) > 0:
                                            exec_price = float(res_data["avgPrice"])
                                        elif "fills" in res_data and res_data["fills"]:
                                            total_qty = sum(float(f["qty"]) for f in res_data["fills"])
                                            if total_qty > 0:
                                                exec_price = sum(float(f["price"]) * float(f["qty"]) for f in res_data["fills"]) / total_qty
                                        
                                        # Calculate new TP/SL based on actual execution price
                                        offset_tp = float(order["take_profit"] - entry) if order["take_profit"] else 0.0
                                        offset_sl = float(entry - order["stop_loss"]) if order["stop_loss"] else 0.0
                                        
                                        new_tp = None
                                        new_sl = None
                                        
                                        if side == "BUY":
                                            if offset_tp > 0:
                                                new_tp = exec_price + offset_tp
                                            if offset_sl > 0:
                                                new_sl = exec_price - offset_sl
                                        else:
                                            if offset_tp < 0: # offset_tp was negative for Sell TP
                                                new_tp = exec_price + offset_tp
                                            if offset_sl < 0: # offset_sl was negative for Sell SL
                                                new_sl = exec_price - offset_sl
                                                
                                        # Update order in DB to ACTIVE with real execution price and recalculated SL/TP
                                        conn = db.get_db_connection()
                                        conn.execute(
                                            "UPDATE orders SET status = 'ACTIVE', entry_price = ?, stop_loss = ?, take_profit = ?, amount = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                                            (exec_price, new_sl, new_tp, qty, order_id)
                                        )
                                        conn.commit()
                                        conn.close()
                                        db.upload_db_to_hf_async()
                                        
                                        lev_str = f" | Плечо: {u_lev}x" if market_type.upper() == "FUTURES" else ""
                                        send_notification(
                                            f"🔔 <b>[LIVE Mode] Локальный лимитный ордер активирован на Binance ({market_type})</b>\n\n"
                                            f"🚀 Сделка: <b>{side}</b> на <b>{pair}</b>{lev_str}\n"
                                            f"• Кол-во: {qty}\n"
                                            f"• Цена исполнения: ${exec_price:,.4f}\n"
                                            f"• Order ID: <code>{res_data['orderId']}</code>"
                                        )
                                    else:
                                        err = res_data.get("msg", "Unknown error")
                                        print(f"Failed to activate live pending order: {err}")
                                except Exception as live_ex:
                                    print(f"Error executing live pending order: {live_ex}")
                        else:
                            # DEMO Mode
                            activated = db.activate_pending_order(order_id)
                            if activated:
                                print(f"[LIMIT ACTIVATED] Pending order {order_id} activated at entry price {entry}")
                                send_notification(
                                    f"🔔 <b>[DEMO Mode] Лимитный ордер активирован</b>\n\n"
                                    f"Пара: <b>{pair}</b>\n"
                                    f"Цена исполнения: ${entry:,.4f}"
                                )
                    continue  # do not check TP/SL on the same tick it activates
                
                # --- Trailing Stop Logic ---
                settings_dict = dict(db.get_settings())
                use_trailing = settings_dict.get("use_trailing_stop", 1)
                
                if use_trailing and sl:
                    use_ai_trailing = settings_dict.get("use_ai_trailing", 0)
                    timeframe = settings_dict.get("timeframe", "1m") or "1m"
                    if use_ai_trailing:
                        # Получаем динамический отступ от ИИ
                        ai_dist_pct = get_ai_trailing_distance_pct(pair, timeframe, market_type)
                        trailing_step_pct = ai_dist_pct if ai_dist_pct is not None else settings_dict.get("trailing_step_pct", 0.2)
                        trailing_activation_pct = trailing_step_pct * 1.5
                    else:
                        trailing_activation_pct = settings_dict.get("trailing_activation_pct", 0.5)
                        trailing_step_pct = settings_dict.get("trailing_step_pct", 0.2)
                    
                    new_sl = None
                    if side == "BUY":
                        profit_pct = (candle_high - entry) / entry * 100
                        if profit_pct >= trailing_activation_pct:
                            trailing_dist = candle_high * (trailing_step_pct / 100)
                            potential_sl = candle_high - trailing_dist
                            # For BUY, we only trail up if it's higher than current SL
                            if potential_sl > sl:
                                new_sl = potential_sl
                    elif side == "SELL":
                        profit_pct = (entry - candle_low) / entry * 100
                        if profit_pct >= trailing_activation_pct:
                            trailing_dist = candle_low * (trailing_step_pct / 100)
                            potential_sl = candle_low + trailing_dist
                            # For SELL, we only trail down if it's lower than current SL
                            if potential_sl < sl:
                                new_sl = potential_sl
                            
                    if new_sl:
                        db.update_order_sl(order_id, new_sl)
                        sl = new_sl # Update for the trigger checks below

                closed = False
                status = ""
                pnl = 0.0
                close_trigger_price = price
                
                if side == "BUY":  # LONG position
                    if sl and candle_low <= sl:
                        closed = True
                        status = "CLOSED_SL"
                        pnl = (sl - entry) * amount
                        close_trigger_price = sl
                    elif tp and candle_high >= tp:
                        closed = True
                        status = "CLOSED_TP"
                        pnl = (tp - entry) * amount
                        close_trigger_price = tp
                elif side == "SELL":  # SHORT position
                    if sl and candle_high >= sl:
                        closed = True
                        status = "CLOSED_SL"
                        pnl = (entry - sl) * amount
                        close_trigger_price = sl
                    elif tp and candle_low <= tp:
                        closed = True
                        status = "CLOSED_TP"
                        pnl = (entry - tp) * amount
                        close_trigger_price = tp
                        
                if closed:
                    print(f"Closing position  - Order {order_id} status {status} PnL {pnl}")
                    
                    if trading_mode == "LIVE":
                        # Закрываем реальную позицию на Binance
                        success = close_live_position(pair, amount, market_type, order_side=side)
                        if not success:
                            print(f"Failed to execute LIVE close order on Binance for order {order_id}. Closing in DB anyway.")
                            
                        # Закрываем ордер в БД (demo_balance не обновляется, т.к. trading_mode='LIVE')
                        db_closed = db.close_order(order_id, status=status, close_price=close_trigger_price, pnl=pnl)
                        
                        if db_closed:
                            pnl_sign = "+" if pnl >= 0 else ""
                            emoji = "🔴" if status == "CLOSED_SL" else "🔵"
                            send_notification(
                                f"{emoji} <b>[LIVE Mode] Позиция закрыта ({status.replace('CLOSED_', '')})</b>\n\n"
                                f"Пара: <b>{pair}</b>\n"
                                f"Сделка: BUY\n"
                                f"Цена входа: ${entry:,.4f}\n"
                                f"Цена закрытия: ${close_trigger_price:,.4f}\n"
                                f"Чистый PnL: <b>{pnl_sign}${pnl:,.2f}</b>"
                            )
                    else:  # DEMO mode
                        db_closed = db.close_order(order_id, status=status, close_price=close_trigger_price, pnl=pnl)
                        if db_closed:
                            pnl_sign = "+" if pnl >= 0 else ""
                            emoji = "🔴" if status == "CLOSED_SL" else "🔵"
                            send_notification(
                                f"{emoji} <b>[DEMO Mode] Ордер закрыт ({status.replace('CLOSED_', '')})</b>\n\n"
                                f"Пара: <b>{pair}</b>\n"
                                f"Цена входа: ${entry:,.4f}\n"
                                f"Цена закрытия: ${close_trigger_price:,.4f}\n"
                                f"Профит/Убыток: <b>{pnl_sign}${pnl:,.2f}</b>"
                            )

                    # Check if closed in loss
                    if pnl < 0:
                        print(f"[LOSS RETRAIN] Position closed in loss (PnL: {pnl}). Triggering retraining to adapt.")
                        try:
                            settings = db.get_settings()
                            tf = (dict(settings).get("timeframe") or "3m") if settings else "3m"
                            scalping_ensemble.retrain_on_market_history(pair, tf)
                        except Exception as re:
                            print(f"Error retraining models after losing trade: {re}")
                        
            time.sleep(0.5)  # проверяем чаще для 1-минутного таймфрейма
            
        except Exception as e:
            print(f"Error in market simulator loop: {e}")
            time.sleep(0.5)


def run_automated_trading_bot():
    """
    Фоновый поток робота скальпинга.
    Проверяет торговые сигналы раз в минуту.
    """
    print("Automated scalping bot thread started.")
    last_run_times = {}  # user_id -> timestamp
    
    # Сопоставление таймфреймов с интервалами в секундах
    TIMEFRAME_TO_SECONDS = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600
    }
    
    last_retrain_time = time.time()
    RETRAIN_INTERVAL = 3600  # Дообучать модели раз в час
    
    while not _stop_event.is_set():
        try:
            settings_row = db.get_settings()
            if settings_row:
                bot_info = dict(settings_row)
                bot_info["user_id"] = 0
                active_bots = [bot_info]
            else:
                active_bots = []
            current_time = time.time()
            
            # Периодическое самообучение на истории
            if current_time - last_retrain_time >= RETRAIN_INTERVAL:
                for bot in active_bots:
                    pair = bot["trading_pair"]
                    timeframe = bot["timeframe"] or "1m"
                    try:
                        scalping_ensemble.retrain_on_market_history(pair, timeframe)
                    except Exception as re:
                        print(f"Ошибка при дообучении моделей для {pair}: {re}")
                last_retrain_time = current_time
            
            for bot in active_bots:
                user_id = bot["user_id"]
                pair = bot["trading_pair"]
                timeframe = bot["timeframe"] or "1m"
                
                # Опрашиваем локальный кеш / Binance раз в 1.0 секунду для мгновенного входа по сигналам
                interval_sec = 1.0
                last_run = last_run_times.get(user_id, 0)
                
                if current_time - last_run >= interval_sec:
                    try:
                        run_user_analysis_cycle()
                    except Exception as e:
                        print(f"Error running user analysis cycle for {user_id}: {e}")
                    last_run_times[user_id] = current_time
                    
            time.sleep(0.25)  # проверяем базу данных 4 раза в секунду для мгновенной реакции
            
        except Exception as e:
            print(f"Error in automated trading bot runner: {e}")
            time.sleep(5)


# =====================================================================
# 6. УПРАВЛЕНИЕ ПОТОКАМИ
# =====================================================================
def start_bot_scheduler():
    """
    Запускает фоновые потоки и инициализирует модели.
    """
    global _simulator_thread, _bot_runner_thread
    
    # 1. Сброс и создание таблиц
    db.init_db()
    
    # 2. Обучение моделей DLinear и LightGBM/NumPyClassifier
    print("Инициализация моделей скальпинга...")
    settings = db.get_settings()
    pair = (dict(settings).get("trading_pair", "BTCUSDT") or "BTCUSDT").upper()
    timeframe = dict(settings).get("timeframe", "1m") or "1m"
    
    if not scalping_ensemble.load_models_from_disk(pair, timeframe):
        print(f"Сохраненные модели для {pair} ({timeframe}) не найдены. Запускаем виртуальное бутстрап-обучение на реальной истории...")
        scalping_ensemble.bootstrap_virtual_training(pair, timeframe)
    else:
        print(f"Модели для {pair} ({timeframe}) успешно загружены с диска.")
    
    _stop_event.clear()
    
    # 3. Запуск фоновых симуляторов
    if _simulator_thread is None or not _simulator_thread.is_alive():
        _simulator_thread = threading.Thread(target=run_market_simulator, daemon=True)
        _simulator_thread.start()
        
    if _bot_runner_thread is None or not _bot_runner_thread.is_alive():
        _bot_runner_thread = threading.Thread(target=run_automated_trading_bot, daemon=True)
        _bot_runner_thread.start()

def stop_bot_scheduler():
    """Останавливает все фоновые потоки."""
    _stop_event.set()
