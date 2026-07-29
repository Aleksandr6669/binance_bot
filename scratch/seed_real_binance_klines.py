import sqlite3
import json
import random
import time
import requests

DB_PATH = "trading_bot.db"

def fetch_random_binance_klines(symbol="ETHUSDC", limit=25):
    """Запрашивает 25 реальных свечей с Binance за случайный исторический период."""
    try:
        # Берем случайный интервал из последних 30 дней
        now_ts = int(time.time() * 1000)
        thirty_days_ms = 30 * 24 * 3600 * 1000
        random_start = now_ts - random.randint(3600 * 1000, thirty_days_ms)
        
        tf = random.choice(["1m", "5m", "15m"])
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={tf}&startTime={random_start}&limit={limit}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data:
                # Извлекаем реальные цены закрытия (Close prices)
                closes = [float(k[4]) for k in data]
                return closes
    except Exception as e:
        print(f"Error fetching Binance klines: {e}")
    
    return []

def populate_closed_orders_with_real_klines():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Извлекаем все ордера
    cursor.execute("SELECT id, pair, side, entry_price, close_price, status FROM orders")
    rows = cursor.fetchall()
    print(f"Found {len(rows)} orders in database.")
    
    updated_count = 0
    for r in rows:
        order_id, pair, side, entry_p, close_p, status = r
        sym = pair if pair else "ETHUSDC"
        if "USDT" in sym and not sym.endswith("USDC"):
            sym = sym.replace("USDT", "USDC")
            
        real_closes = fetch_random_binance_klines(symbol=sym, limit=25)
        if real_closes:
            snapshot_json = json.dumps(real_closes)
            cursor.execute("UPDATE orders SET chart_snapshot = ? WHERE id = ?", (snapshot_json, order_id))
            updated_count += 1
            print(f"Updated order ID {order_id} ({sym}) with {len(real_closes)} real Binance klines.")
        
        time.sleep(0.1)  # пауза между запросами к API Binance
        
    conn.commit()
    conn.close()
    print(f"✅ Successfully updated {updated_count} orders with REAL Binance klines!")

if __name__ == "__main__":
    populate_closed_orders_with_real_klines()
