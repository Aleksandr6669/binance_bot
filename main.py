import os
import sys
import flet as ft

import db
import trading_engine
import telegram_manager
import flet_app

def start_application():
    print("=== Инициализация базы данных... ===")
    db.init_db()
    
    print("=== Запуск фонового торгового движка и симулятора... ===")
    trading_engine.start_bot_scheduler()
    
    print("=== Запуск Telegram-менеджера... ===")
    telegram_manager.start_telegram_manager()
    
    # Считываем конфигурацию портов и хостов из окружения
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    web_mode = os.environ.get("FLET_WEB_MODE") == "1"
    
    print(f"=== Запуск Flet-интерфейса (Web-mode={web_mode}, {host}:{port})... ===")
    try:
        ft.app(
            target=flet_app.main,
            host=host,
            port=port,
            view=None if web_mode else ft.AppView.FLET_APP,
            assets_dir="."
        )
    except KeyboardInterrupt:
        print("Получен сигнал прерывания (Ctrl+C). Выход...")
    except Exception as e:
        print(f"Критическая ошибка при запуске Flet-интерфейса: {e}")
    finally:
        print("=== Корректная остановка фоновых процессов ботов... ===")
        trading_engine.stop_bot_scheduler()
        print("=== Все фоновые процессы остановлены. Выход завершен. ===")

if __name__ == "__main__":
    start_application()
