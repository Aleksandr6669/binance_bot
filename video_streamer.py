import time
import io
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    import subprocess
    import sys
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "pillow"], check=False)
        from PIL import Image, ImageDraw, ImageFont
        HAS_PIL = True
    except Exception:
        HAS_PIL = False

import trading_engine
import scalping_ensemble
import db

_streamer_thread = None
_streamer_server = None
_latest_jpeg_frame = None
_frame_lock = threading.Lock()

def render_terminal_frame():
    """
    Рендерит живой кадр терминала 1280x720 с помощью Pillow:
    - Цена, волатильность и статус ИИ
    - Стакан цен Bids/Asks и крупные стенки
    - Карта ликвидаций фьючерсов
    - Уровень уверенности нейросети
    """
    width, height = 1280, 720
    if not HAS_PIL:
        # Валидный минимальный байтовый заголовок JPEG (fallback)
        return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x10\x00\x10\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'

    img = Image.new("RGB", (width, height), color="#0f172a")
    draw = ImageDraw.Draw(img)

    # Используем дефолтный шрифт PIL
    try:
        font_title = ImageFont.load_default()
    except Exception:
        font_title = None

    # Градиентный фон карточек (темно-синяя элегантная гамма)
    draw.rectangle([0, 0, width, 60], fill="#1e293b")
    draw.text((20, 18), "NEXUS AI LIVE STREAM — TRADING TERMINAL", fill="#38bdf8")

    pair = db.get_setting("symbol", "ETHUSDT")
    market_type = db.get_setting("market_type", "FUTURES")
    cur_price = trading_engine.fetch_current_price(pair, market_type)
    sig_info = trading_engine.LATEST_LIVE_SIGNAL

    # 1. Карточка текущей цены и ИИ
    draw.rectangle([20, 80, 620, 340], fill="#1e293b", outline="#334155", width=2)
    draw.text((40, 95), f"ТОРГОВАЯ ПАРА: {pair} ({market_type})", fill="#f8fafc")
    draw.text((40, 125), f"ТЕКУЩАЯ ЦЕНА: ${cur_price:,.2f}", fill="#10b981" if cur_price > 0 else "#ffffff")

    action = sig_info.get("action", "HOLD")
    prob = sig_info.get("prob", 0.5)
    action_color = "#10b981" if action == "BUY" else ("#ef4444" if action == "SELL" else "#94a3b8")
    draw.text((40, 165), f"СИГНАЛ ИИ: {action} (Уверенность: {prob*100:.1f}%)", fill=action_color)

    # 2. Стакан цен и крупные стенки (Order Book)
    draw.rectangle([640, 80, 1260, 340], fill="#1e293b", outline="#334155", width=2)
    draw.text((660, 95), "СТАКАН ЦЕН И КРУПНЫЕ ПЛОТНОСТИ (ORDER BOOK WALLS)", fill="#38bdf8")
    
    ob_data = trading_engine.get_live_orderbook_details(pair, market_type)
    bids = ob_data.get("bids", [])[:6]
    asks = ob_data.get("asks", [])[:6]
    max_bid_p = ob_data.get("max_bid_price", 0.0)
    max_ask_p = ob_data.get("max_ask_price", 0.0)

    y_off = 135
    draw.text((660, y_off), "🟢 BIDS (ПОКУПКА)", fill="#10b981")
    draw.text((960, y_off), "🔴 ASKS (ПРОДАЖА)", fill="#ef4444")
    y_off += 25

    for i in range(min(len(bids), len(asks))):
        bp, bv = bids[i]
        ap, av = asks[i]
        b_tag = " [🏆 СТЕНКА]" if bp == max_bid_p else ""
        a_tag = " [🏆 СТЕНКА]" if ap == max_ask_p else ""
        draw.text((660, y_off), f"${bp:,.2f} ({bv:.2f}){b_tag}", fill="#34d399")
        draw.text((960, y_off), f"${ap:,.2f} ({av:.2f}){a_tag}", fill="#f87171")
        y_off += 22

    # 3. Карта ликвидаций (Predicted Liquidation Map)
    draw.rectangle([20, 360, 1260, 680], fill="#1e293b", outline="#334155", width=2)
    draw.text((40, 375), "⚡ КАРТА ЛИКВИДАЦИЙ ФЬЮЧЕРСОВ (PREDICTED LIQUIDATION MAP)", fill="#a78bfa")

    liq_data = trading_engine.get_live_liquidation_map_details(pair, market_type)
    shorts = liq_data.get("short_levels", [])
    longs = liq_data.get("long_levels", [])
    max_s_price = liq_data.get("max_short_price", 0.0)
    max_l_price = liq_data.get("max_long_price", 0.0)

    draw.text((40, 410), "🟢 SHORT LIQUIDATIONS (ВЫШЕ ЦЕНЫ)", fill="#10b981")
    draw.text((660, 410), "🔴 LONG LIQUIDATIONS (НИЖЕ ЦЕНЫ)", fill="#ef4444")

    y_off_s = 440
    for sp, sv, lev in shorts:
        m_tag = " 🎯 [МАГНИТ]" if sp == max_s_price else ""
        draw.text((40, y_off_s), f"${sp:,.2f} [{lev}] — ${sv:,.0f}{m_tag}", fill="#34d399")
        y_off_s += 25

    y_off_l = 440
    for lp, lv, lev in longs:
        m_tag = " 🎯 [МАГНИТ]" if lp == max_l_price else ""
        draw.text((660, y_off_l), f"${lp:,.2f} [{lev}] — ${lv:,.0f}{m_tag}", fill="#f87171")
        y_off_l += 25

    # Нижний статус времени
    draw.rectangle([0, 690, width, height], fill="#0284c7")
    time_str = time.strftime("%Y-%m-%d %H:%M:%S")
    draw.text((20, 698), f"LIVE STREAM ACTIVE — {time_str} | VIDEO STREAM: http://<LOCAL_IP>:8554/stream.mjpeg", fill="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

def _frame_worker():
    global _latest_jpeg_frame
    while True:
        try:
            frame_bytes = render_terminal_frame()
            with _frame_lock:
                _latest_jpeg_frame = frame_bytes
        except Exception:
            pass
        time.sleep(0.3)  # ~3.3 FPS

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class MJPEGStreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/stream.mjpeg", "/video", "/mjpeg", "/"]:
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            try:
                while True:
                    with _frame_lock:
                        frame = _latest_jpeg_frame
                    if frame:
                        self.wfile.write(b'--frame\r\n')
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.3)
            except Exception:
                pass
        else:
            self.send_error(404)

def start_video_streamer(host="0.0.0.0", port=8554):
    global _streamer_thread, _streamer_server
    
    # Фоновый генератор кадров
    t_gen = threading.Thread(target=_frame_worker, daemon=True)
    t_gen.start()

    # HTTP Видеосервер
    try:
        _streamer_server = ThreadingHTTPServer((host, port), MJPEGStreamHandler)
        _streamer_thread = threading.Thread(target=_streamer_server.serve_forever, daemon=True)
        _streamer_thread.start()
        print(f"🎥 LIVE VIDEO STREAMER ЗАПУЩЕН! Поток прямого видео: http://{host}:{port}/stream.mjpeg")
    except Exception as e:
        print(f"Ошибка запуска MJPEG Видеостримера: {e}")
