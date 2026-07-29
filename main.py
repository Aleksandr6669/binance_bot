import os
import sys
from dotenv import load_dotenv
import flet as ft

load_dotenv()

import db
import trading_engine
import flet_app
import video_streamer

# Глобальная настройка прокси для всех сетевых запросов при старте
trading_engine.get_binance_proxies()

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_application():
    print("=== Инициализация базы данных... ===")
    db.init_db()
    
    print("=== Запуск фонового торгового движка и симулятора... ===")
    trading_engine.start_bot_scheduler()
    

    # Считываем конфигурацию портов и хостов из окружения
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8550))
    # Включаем сетевой веб-режим для доступа с любых устройств в сети (по умолчанию True)
    web_mode_env = os.environ.get("FLET_WEB_MODE", "1")
    web_mode = web_mode_env != "0"
    local_ip = get_local_ip()
    stream_url = f"http://{local_ip}:{port}"
    video_stream_url = f"http://{local_ip}:8554/stream.mjpeg"
    os.environ["STREAM_URL"] = stream_url
    os.environ["VIDEO_STREAM_URL"] = video_stream_url

    # Запускаем прямой MJPEG Видеостример для медиаплееров
    try:
        video_streamer.start_video_streamer(host="0.0.0.0", port=8554)
    except Exception as ex:
        print(f"Ошибка запуска Видеостримера: {ex}")
    
    print("=" * 60)
    print("🚀 NEXUS AI TRADING TERMINAL ЗАПУЩЕН!")
    print("=" * 60)
    print(f"🌐 СЕТЕВОЙ ВЕБ-ИНТЕРФЕЙС (Браузеры): {stream_url}")
    print(f"🎥 ПРЯМОЙ ВИДЕОПОТОК (VLC / Smart TV / AirPlay / Google Play): {video_stream_url}")
    print("=" * 60)
    if os.environ.get("APP_PASSWORD"):
        print("🔒 Вход защищен паролем из .env (APP_PASSWORD)")
    else:
        print("⚠️ Пароль не установлен! Кто угодно в сети может открыть интерфейс.")
    print("=" * 60)
    
    # Создаем папки для моделей и загрузок
    os.makedirs("models", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)

    print(f"=== Запуск Flet-интерфейса (Web-mode={web_mode}, {host}:{port})... ===")
    interrupted = False
    try:
        ft.app(
            target=flet_app.main,
            host=host,
            port=port,
            view=ft.AppView.WEB_BROWSER if web_mode else ft.AppView.FLET_APP,
            assets_dir=".",
            upload_dir="uploads"
        )
    except KeyboardInterrupt:
        interrupted = True
        print("Получен сигнал прерывания (Ctrl+C). Выход...")
    except Exception as e:
        print(f"Критическая ошибка при запуске Flet-интерфейса: {e}")
    finally:
        if not web_mode and not interrupted:
            print("=" * 60)
            print("📺 Окно интерфейса закрыто, но бот продолжает работать в фоне.")
            print("Для полной остановки нажмите Ctrl+C в этом окне терминала.")
            print("=" * 60)
            try:
                import signal
                signal.signal(signal.SIGINT, signal.SIG_DFL)
            except:
                pass
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("Получен сигнал прерывания (Ctrl+C) в фоновом режиме. Выход...")
        
        print("=== Корректная остановка фоновых процессов ботов... ===")
        trading_engine.stop_bot_scheduler()
        print("=== Все фоновые процессы остановлены. Выход завершен. ===")

if __name__ == "__main__":
    start_application()
