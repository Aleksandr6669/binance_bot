import threading
import json
import time
import websocket

# Cache structure:
# _ws_klines_cache[(symbol, timeframe, market_type)] = [kline1, kline2, ...]
_ws_klines_cache = {}
_active_streams = set()
_ws_connections = {}
_ws_last_update = {}

def init_ws_cache(symbol, timeframe, market_type, initial_klines):
    key = (symbol.upper(), timeframe.lower(), market_type.upper())
    _ws_klines_cache[key] = initial_klines
    _ws_last_update[key] = time.time()

def get_klines(symbol, timeframe, market_type):
    key = (symbol.upper(), timeframe.lower(), market_type.upper())
    return _ws_klines_cache.get(key, [])

def is_stream_active(symbol, timeframe, market_type):
    key = (symbol.upper(), timeframe.lower(), market_type.upper())
    # Consider stream inactive if no updates for 15 seconds
    if key in _active_streams:
        last_upd = _ws_last_update.get(key, 0)
        if time.time() - last_upd < 5:
            return True
        else:
            return False
    return False

def _on_message(ws, message, key):
    try:
        data = json.loads(message)
        if "k" in data:
            k = data["k"]
            # kline format in fetch_binance_klines:
            # [open_time, open, high, low, close, volume, close_time, quote_asset_volume, number_of_trades, taker_buy_base_asset_volume, taker_buy_quote_asset_volume, ignore]
            
            new_kline = [
                k["t"],         # open_time
                k["o"],         # open
                k["h"],         # high
                k["l"],         # low
                k["c"],         # close
                k["v"],         # volume
                k["T"],         # close_time
                k["q"],         # quote_asset_volume
                k["n"],         # number_of_trades
                k["V"],         # taker_buy_base_asset_volume
                k["Q"],         # taker_buy_quote_asset_volume
                k["B"]          # ignore
            ]
            
            is_closed = k["x"]
            
            cache = _ws_klines_cache.get(key)
            if cache and len(cache) > 0:
                last_kline = cache[-1]
                # If it's the same candle (same open time), update it
                if last_kline[0] == new_kline[0]:
                    cache[-1] = new_kline
                else:
                    # New candle started
                    cache.append(new_kline)
                    # Limit to 100 candles to save memory
                    if len(cache) > 100:
                        cache.pop(0)
                        
                _ws_last_update[key] = time.time()
    except Exception as e:
        print(f"[WS] Error parsing message for {key}: {e}")

def _on_error(ws, error, key):
    print(f"[WS] Error in stream {key}: {error}")

def _on_close(ws, close_status_code, close_msg, key):
    print(f"[WS] Stream closed for {key}")
    if key in _active_streams:
        _active_streams.remove(key)
    if key in _ws_connections:
        del _ws_connections[key]

def _start_ws_thread(url, key):
    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=lambda w, m: _on_message(w, m, key),
                    on_error=lambda w, e: _on_error(w, e, key),
                    on_close=lambda w, c, m: _on_close(w, c, m, key)
                )
                _ws_connections[key] = ws
                ws.run_forever()
            except Exception as e:
                print(f"[WS] WebSocket exception for {key}: {e}")
            
            # Reconnect logic
            if key not in _active_streams:
                break
            print(f"[WS] Reconnecting {key} in 5 seconds...")
            time.sleep(5)
            
    t = threading.Thread(target=run, daemon=True)
    t.start()

def start_kline_stream(symbol, timeframe, market_type="SPOT"):
    key = (symbol.upper(), timeframe.lower(), market_type.upper())
    if key in _active_streams:
        return
        
    _active_streams.add(key)
    stream_name = f"{symbol.lower()}@kline_{timeframe.lower()}"
    
    if market_type.upper() == "FUTURES":
        url = f"wss://fstream.binance.com/ws/{stream_name}"
    else:
        url = f"wss://stream.binance.com:9443/ws/{stream_name}"
        
    print(f"[WS] Starting stream for {key} at {url}")
    _start_ws_thread(url, key)

def stop_kline_stream(symbol, timeframe, market_type="SPOT"):
    key = (symbol.upper(), timeframe.lower(), market_type.upper())
    if key in _active_streams:
        _active_streams.remove(key)
    
    ws = _ws_connections.get(key)
    if ws:
        ws.close()
