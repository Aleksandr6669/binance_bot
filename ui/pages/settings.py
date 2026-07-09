import ui.layout
import flet as ft
import db
import threading
import sys
import os
import signal
from ui.theme import *
from ui.i18n import t
from ui.helpers import make_textfield, make_dropdown
from ui.layout import build_layout

# We need access to restart_bot function which was in main.py, or we can just emit an event or restart process directly.
def restart_bot():
    print("Restarting bot from UI...")
    os.execv(sys.executable, ['python'] + sys.argv)

def build_settings_view(page: ft.Page, lang: str):
    import httpx
    
    user_id = page.session.store.get("user_id")
    settings = dict(db.get_user_settings(user_id) or {})
    user_info = db.get_user_by_id(user_id)
    
    # Get public IP for whitelist info box
    server_ip = "Unknown"
    try:
        res = httpx.get("https://api.ipify.org?format=json", timeout=2)
        if res.status_code == 200:
            server_ip = res.json().get("ip", "Unknown")
    except Exception:
        pass
        
    # --- Columns Setup ---
    # Left Column: API Keys
    gemini_api_field = make_textfield(label="Gemini API Key", value=user_info.get("gemini_api_key") or "", password=True, can_reveal_password=True)
    binance_api_field = make_textfield(label="Binance API Key", value=user_info.get("binance_api_key") or "")
    binance_secret_field = make_textfield(label="Binance API Secret", value=user_info.get("binance_api_secret") or "", password=True, can_reveal_password=True)
    tg_chat_field = make_textfield(label="Telegram Chat ID", value=user_info.get("telegram_chat_id") or "")
    tg_token_field = make_textfield(label="Telegram Bot Token", value=user_info.get("telegram_bot_token") or "", password=True, can_reveal_password=True)
    
    def save_api_keys(e):
        db.update_user_api_keys(
            user_id,
            gemini_api_field.value.strip(),
            binance_api_field.value.strip(),
            binance_secret_field.value.strip(),
            tg_chat_field.value.strip(),
            tg_token_field.value.strip()
        )
        page.snack_bar = ft.SnackBar(ft.Text("API Keys Saved successfully!"), bgcolor=GREEN_COLOR)
        page.snack_bar.open = True
        page.update()
        
    ip_box = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_ROUNDED, color=GOLD_COLOR, size=18),
                ft.Text(f"IP-адрес сервера для Binance API Whitelist: {server_ip}", size=12, color=GOLD_COLOR, weight=ft.FontWeight.BOLD)
            ],
            spacing=8
        ),
        bgcolor="rgba(252, 213, 53, 0.1)",
        border=ft.Border.all(1, GOLD_COLOR),
        padding=10,
        border_radius=8
    )
    
    api_card = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.KEY_ROUNDED, color=GOLD_COLOR), ft.Text("Сохранить API ключи", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)]),
                ft.Divider(color=BORDER_COLOR),
                ip_box if server_ip != "Unknown" else ft.Container(),
                gemini_api_field,
                binance_api_field,
                binance_secret_field,
                tg_token_field,
                tg_chat_field,
                ft.ElevatedButton("Сохранить API ключи", on_click=save_api_keys, bgcolor=GOLD_COLOR, color="#000000", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))
            ],
            spacing=15
        ),
        bgcolor=CARD_COLOR,
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=16,
        padding=25,
        col={"xs": 12, "md": 6}
    )
    
    # Right Column: Trading Rules
    pair_dd = make_dropdown(
        label="TRADING SYMBOL (PAIR)",
        options=[
            ft.dropdown.Option("BTCUSDT", "BTCUSDT"),
            ft.dropdown.Option("ETHUSDT", "ETHUSDT"),
            ft.dropdown.Option("SOLUSDT", "SOLUSDT"),
            ft.dropdown.Option("BNBUSDT", "BNBUSDT")
        ],
        value=settings.get("trading_pair", "BTCUSDT")
    )
    
    timeframe_dd = make_dropdown(
        label="ТАЙМФРЕЙМ",
        options=[
            ft.dropdown.Option("1m", "1m"),
            ft.dropdown.Option("3m", "3m"),
            ft.dropdown.Option("5m", "5m"),
            ft.dropdown.Option("15m", "15m"),
            ft.dropdown.Option("1h", "1h")
        ],
        value=settings.get("timeframe", "1m")
    )
    
    market_type_dd = make_dropdown(
        label="ТИП РЫНКА",
        options=[
            ft.dropdown.Option("SPOT", "Спотовый рынок"),
            ft.dropdown.Option("FUTURES", "USD-M Фьючерсы")
        ],
        value=settings.get("market_type", "SPOT")
    )
    
    mode_dd = make_dropdown(
        label="TRADING MODE",
        options=[
            ft.dropdown.Option("DEMO", "Demo Mode (Simulated Paper Trading)"),
            ft.dropdown.Option("LIVE", "LIVE Mode (Real Money)")
        ],
        value=settings.get("trading_mode", "DEMO")
    )
    
    prob_field = make_dropdown(
        label="ПОРОГ УВЕРЕННОСТИ КЛАССИФИКАТОРА (CLASSIFIER CONFIDENCE THRESHOLD)",
        options=[
            ft.dropdown.Option("0.85", "85%"),
            ft.dropdown.Option("0.88", "88% (Рекомендуемый, консервативный)"),
            ft.dropdown.Option("0.90", "90% (Очень консервативный)")
        ],
        value=f"{settings.get('min_probability_threshold', 0.88):.2f}" if isinstance(settings.get('min_probability_threshold', 0.88), float) else str(settings.get('min_probability_threshold', 0.88))
    )
    
    # Segment toggles for Fixed vs Percent size
    is_pct = "%" in str(settings.get("order_size_usdt", "100"))
    size_mode = "PERCENT" if is_pct else "FIXED"
    
    size_field = make_textfield(label="Simulated Position size (USDT)", value=str(settings.get("order_size_usdt", 100)))
    leverage_field = make_textfield(label="Futures Leverage", value=str(settings.get("futures_leverage", 10)))
    
    def set_size_mode(mode):
        nonlocal size_mode
        size_mode = mode
        if mode == "FIXED":
            fixed_btn.bgcolor = TEXT_PRIMARY
            fixed_btn.content.color = "#030407"
            percent_btn.bgcolor = ft.Colors.TRANSPARENT
            percent_btn.content.color = TEXT_SECONDARY
            size_field.label = "Simulated Position size (USDT)"
            if "%" in size_field.value:
                size_field.value = size_field.value.replace("%", "").strip()
        else:
            fixed_btn.bgcolor = ft.Colors.TRANSPARENT
            fixed_btn.content.color = TEXT_SECONDARY
            percent_btn.bgcolor = TEXT_PRIMARY
            percent_btn.content.color = "#030407"
            size_field.label = "Position size (% of balance)"
            if size_field.value and "%" not in size_field.value:
                size_field.value = size_field.value.strip() + "%"
        page.update()
        
    fixed_btn = ft.Container(
        content=ft.Text("USDT", size=12, weight=ft.FontWeight.BOLD),
        padding=ft.Padding.symmetric(vertical=8, horizontal=20),
        border_radius=6,
        on_click=lambda _: set_size_mode("FIXED")
    )
    percent_btn = ft.Container(
        content=ft.Text("% от баланса", size=12, weight=ft.FontWeight.BOLD),
        padding=ft.Padding.symmetric(vertical=8, horizontal=20),
        border_radius=6,
        on_click=lambda _: set_size_mode("PERCENT")
    )
    
    # Initialize styles based on load state
    if is_pct:
        fixed_btn.bgcolor = ft.Colors.TRANSPARENT
        fixed_btn.content.color = TEXT_SECONDARY
        percent_btn.bgcolor = TEXT_PRIMARY
        percent_btn.content.color = "#030407"
        size_field.label = "Position size (% of balance)"
    else:
        fixed_btn.bgcolor = TEXT_PRIMARY
        fixed_btn.content.color = "#030407"
        percent_btn.bgcolor = ft.Colors.TRANSPARENT
        percent_btn.content.color = TEXT_SECONDARY
        size_field.label = "Simulated Position size (USDT)"
        
    size_mode_selector = ft.Container(
        content=ft.Row([fixed_btn, percent_btn], spacing=0, tight=True),
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=8,
        bgcolor=CARD_ACCENT,
        padding=2
    )
    
    rules_card = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color=GOLD_COLOR), ft.Text("Параметры торговли", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)]),
                ft.Divider(color=BORDER_COLOR),
                pair_dd,
                timeframe_dd,
                market_type_dd,
                mode_dd,
                prob_field,
                ft.Text("РАЗМЕР ПОЗИЦИИ (USDT)", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.BOLD),
                ft.Row([size_mode_selector]),
                size_field,
                leverage_field
            ],
            spacing=15
        ),
        bgcolor=CARD_COLOR,
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=16,
        padding=25
    )
    
    # Reset Balance card
    deposit_field = make_textfield(
        label="НАЧАЛЬНЫЙ ДЕПОЗИТ ($)",
        hint_text=f"Текущий баланс: ${user_info.get('demo_balance', 10000.0):.2f}"
    )
    
    def reset_demo_portfolio(e):
        val = (deposit_field.value or "10000").strip()
        try:
            amount = float(val)
            if amount <= 0:
                raise ValueError("Deposit must be positive")
        except ValueError:
            page.snack_bar = ft.SnackBar(ft.Text("Введите корректное число для депозита"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()
            return
            
        db.clear_demo_orders(user_id)
        db.update_user_demo_balance(user_id, amount)
        deposit_field.hint_text = f"Текущий баланс: ${amount:.2f}"
        deposit_field.value = ""
        
        page.snack_bar = ft.SnackBar(ft.Text("Демо-депозит успешно обновлен, история ордеров очищена!"), bgcolor=GREEN_COLOR)
        page.snack_bar.open = True
        page.update()
        
    reset_card = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.WARNING_ROUNDED, color=RED_COLOR), ft.Text("Сброс баланса (Risk Ops)", size=16, weight=ft.FontWeight.BOLD, color=RED_COLOR)]),
                ft.Divider(color=BORDER_COLOR),
                ft.Text("Сброс баланса очистит историю ордеров и вернет ваш демо-баланс к исходным $10,000.00 USDT.", size=12, color=TEXT_SECONDARY),
                deposit_field,
                ft.ElevatedButton("Установить депозит", on_click=reset_demo_portfolio, bgcolor=GOLD_COLOR, color="#000000", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))
            ],
            spacing=15
        ),
        bgcolor=CARD_COLOR,
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=16,
        padding=25
    )
    
    right_column = ft.Column(
        [
            rules_card,
            reset_card
        ],
        spacing=20,
        col={"xs": 12, "md": 6}
    )
    
    # Bottom full-width row: Smart logic switches & Risk Limits
    invert_signal_sw = ft.Switch(value=settings.get("invert_signal", 0) == 1)
    use_limit_sw = ft.Switch(value=settings.get("use_limit_orders", 1) == 1)
    use_ai_limit_sw = ft.Switch(value=settings.get("use_ai_limit_price", 0) == 1)
    use_ai_exit_sw = ft.Switch(value=settings.get("use_ai_exit", 0) == 1)
    
    # Trailing Stop components
    use_trailing_sw = ft.Switch(value=settings.get("use_trailing_stop", 1) == 1)
    use_ai_trailing_sw = ft.Switch(value=settings.get("use_ai_trailing", 0) == 1)
    trailing_activation_field = make_textfield(value=str(settings.get("trailing_activation_pct", 0.5)), width=80)
    trailing_step_field = make_textfield(value=str(settings.get("trailing_step_pct", 0.2)), width=80)
    
    # Risk limits
    loss_limit_field = make_textfield(label="ЛИМИТ ДНЕВНОГО УБЫТКА ($)", value=str(settings.get("daily_loss_limit", 0)))
    profit_target_field = make_textfield(label="ЦЕЛЬ ДНЕВНОЙ ПРИБЫЛИ ($)", value=str(settings.get("daily_profit_target", 0)))
    
    def save_rules(e):
        val = (size_field.value or "100").strip()
        if size_mode == "PERCENT":
            if "%" not in val:
                val = val + "%"
            try:
                pct = float(val.replace("%", "").strip())
                if pct <= 0 or pct > 100:
                    raise ValueError("Percentage must be between 0 and 100")
            except ValueError:
                page.snack_bar = ft.SnackBar(ft.Text("Invalid percentage format (e.g. 50%)"), bgcolor=RED_COLOR)
                page.snack_bar.open = True
                page.update()
                return
        else:
            try:
                num = float(val)
                if num <= 0:
                    raise ValueError("Amount must be positive")
            except ValueError:
                page.snack_bar = ft.SnackBar(ft.Text("Size must be a valid number"), bgcolor=RED_COLOR)
                page.snack_bar.open = True
                page.update()
                return

        try:
            db.save_user_settings(
                user_id,
                pair_dd.value,
                timeframe_dd.value,
                val,
                settings.get("bot_enabled", 0),
                mode_dd.value,
                market_type_dd.value,
                int(leverage_field.value or 10),
                float(prob_field.value or 0.88),
                1 if invert_signal_sw.value else 0,
                settings.get("bot_started_at"),
                1 if use_limit_sw.value else 0,
                1 if use_trailing_sw.value else 0,
                1 if use_ai_limit_sw.value else 0,
                float(trailing_activation_field.value or 0.5),
                float(trailing_step_field.value or 0.2),
                1 if use_ai_exit_sw.value else 0,
                1 if use_ai_trailing_sw.value else 0,
                float(loss_limit_field.value or 0),
                float(profit_target_field.value or 0)
            )
            page.snack_bar = ft.SnackBar(ft.Text("Trading Settings Saved successfully!"), bgcolor=GREEN_COLOR)
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Save failed: {ex}"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()
            
    # Helper layout box for switches
    def make_switch_box(title, switch_ctrl, desc):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row([ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, expand=True), switch_ctrl], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(desc, size=11, color=TEXT_SECONDARY)
                ]
            ),
            bgcolor=CARD_ACCENT,
            padding=15,
            border_radius=8,
            border=ft.Border.all(1, BORDER_COLOR),
            col={"xs": 12, "md": 3}
        )
        
    switches_row = ft.ResponsiveRow(
        [
            make_switch_box("ИНВЕРСИЯ ТОРГОВОГО СИГНАЛА", invert_signal_sw, "SELL станет BUY и наоборот."),
            make_switch_box("ИСПОЛЬЗОВАТЬ ЛИМИТНЫЕ ОРДЕРА", use_limit_sw, "Входить в сделки лимитками для экономии комиссий."),
            make_switch_box("AI ДИАПАЗОН СДЕЛКИ (TP/SL)", use_ai_limit_sw, "Использовать прогноз (1m) вместо ATR для TP/SL."),
            make_switch_box("ЗАКРЫТИЕ ПО СИГНАЛУ ИИ", use_ai_exit_sw, "Закрывать сделку досрочно при возникновении противоположного сигнала ИИ.")
        ],
        spacing=10
    )
    
    trailing_stop_box = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("ИСПОЛЬЗОВАТЬ ТРЕЙЛИНГ СТОП-ЛОСС", size=12, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
                        ft.Text("Жесткий Тейк-Профит отключается для максимизации прибыли.", size=11, color=TEXT_SECONDARY)
                    ],
                    expand=True
                ),
                ft.Row(
                    [
                        ft.Text("ТРЕЙЛИНГ СИЛАМИ ИИ:", size=11, color=TEXT_PRIMARY),
                        use_ai_trailing_sw,
                        ft.Text("АКТИВАЦИЯ (%):", size=11, color=TEXT_PRIMARY),
                        trailing_activation_field,
                        ft.Text("ШАГ (%):", size=11, color=TEXT_PRIMARY),
                        trailing_step_field,
                        use_trailing_sw
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        ),
        bgcolor=CARD_ACCENT,
        padding=15,
        border_radius=8,
        border=ft.Border.all(1, BORDER_COLOR)
    )
    
    risk_limits_box = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.SHIELD_ROUNDED, color=RED_COLOR, size=16), ft.Text("Дневные лимиты риска", size=12, weight=ft.FontWeight.BOLD, color=RED_COLOR)]),
                ft.Text("Бот автоматически приостановит торговлю до следующего дня при достижении лимита. Установите 0, чтобы отключить лимит.", size=11, color=TEXT_SECONDARY),
                ft.Row([loss_limit_field, profit_target_field], spacing=15)
            ],
            spacing=10
        ),
        bgcolor="rgba(244, 63, 94, 0.04)",
        padding=15,
        border_radius=8,
        border=ft.Border.all(1, "rgba(244, 63, 94, 0.15)")
    )
    
    smart_card = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=GOLD_COLOR), ft.Text("Умные функции и Торговая логика", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)]),
                ft.Divider(color=BORDER_COLOR),
                switches_row,
                ft.Container(height=10),
                trailing_stop_box,
                ft.Container(height=10),
                risk_limits_box,
                ft.Container(height=10),
                ft.Row(
                    [
                        ft.ElevatedButton("Сохранить Основные и Умные правила", on_click=save_rules, bgcolor=GOLD_COLOR, color="#000000", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))
                    ],
                    alignment=ft.MainAxisAlignment.END
                )
            ],
            spacing=10
        ),
        bgcolor=CARD_COLOR,
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=16,
        padding=25,
        col={"xs": 12, "md": 12}
    )
    
    main_row = ft.ResponsiveRow(
        [
            api_card,
            right_column,
            smart_card
        ],
        spacing=20
    )
    
