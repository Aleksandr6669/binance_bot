import os
import sys
import flet as ft

import db
import trading_engine
import flet_app

def start_application():
    print("=== Инициализация базы данных... ===")
    db.init_db()
    
    print("=== Запуск фонового торгового движка и симулятора... ===")
    trading_engine.start_bot_scheduler()
    

    # Считываем конфигурацию портов и хостов из окружения
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8550))
    web_mode = os.environ.get("FLET_WEB_MODE", "0") == "1"
    
    print("=" * 60)
    print("🚀 NEXUS AI TRADING TERMINAL ЗАПУЩЕН!")
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
