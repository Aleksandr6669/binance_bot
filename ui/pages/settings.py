import ui.layout
import flet as ft
import db
import threading
import sys
import os
import signal
from ui.theme import *
from ui.styles import *
from ui.i18n import t
from ui.helpers import make_textfield, make_dropdown
from ui.layout import build_layout

_cached_symbols = {}
_fetching_symbols = set()
_symbols_lock = threading.Lock()

_fallback_symbols = {
    "SPOT": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT", "DOTUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "SHIBUSDT", "TRXUSDT", "MATICUSDT", "NEARUSDT", "UNIUSDT"],
    "FUTURES": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT", "DOTUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "SHIBUSDT", "TRXUSDT", "MATICUSDT", "NEARUSDT", "UNIUSDT"]
}

def fetch_symbols_background(market_type):
    market_type = market_type.upper()
    try:
        use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo" if market_type == "FUTURES" else (
            "https://api.binance.us/api/v3/exchangeInfo" if use_us else "https://api.binance.com/api/v3/exchangeInfo"
        )
        import requests
        import trading_engine
        proxies = trading_engine.get_binance_proxies()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=15, proxies=proxies)
        if res.status_code == 200:
            data = res.json()
            symbols = [s["symbol"] for s in data["symbols"] if s.get("status") == "TRADING"]
            symbols = [s for s in symbols if s.endswith(("USDT", "USDC", "BUSD", "BTC", "ETH"))]
            symbols.sort()
            with _symbols_lock:
                _cached_symbols[market_type] = symbols
            print(f"Loaded {len(symbols)} Binance symbols for {market_type}")
    except Exception as e:
        print(f"Error fetching symbols background for {market_type}: {e}")
    finally:
        with _symbols_lock:
            if market_type in _fetching_symbols:
                _fetching_symbols.remove(market_type)

def get_binance_symbols(market_type):
    market_type = market_type.upper()
    with _symbols_lock:
        if market_type in _cached_symbols and len(_cached_symbols[market_type]) > len(_fallback_symbols["SPOT"]):
            return _cached_symbols[market_type]
        if market_type not in _fetching_symbols:
            _fetching_symbols.add(market_type)
            threading.Thread(target=fetch_symbols_background, args=(market_type,), daemon=True).start()
    return _fallback_symbols.get(market_type, _fallback_symbols["SPOT"])

def sanitize_symbol_input(val):
    val = (val or "").strip().upper()
    
    # 1. Phonetic replacement
    phonetic_map = {
        'БТЦ': 'BTC',
        'СОЛ': 'SOL',
        'ЭФИР': 'ETH',
        'УСДТ': 'USDT'
    }
    for cyr, lat in phonetic_map.items():
        val = val.replace(cyr, lat)
        
    # 2. Homoglyph mapping (Cyrillic lookalikes to Latin)
    homoglyphs = {
        'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'К': 'K', 
        'М': 'M', 'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X', 'У': 'Y'
    }
    val = "".join(homoglyphs.get(c, c) for c in val)
    
    # 3. Transliterate keyboard keys (if they typed with Russian layout active)
    keyboard_map = {
        'Й': 'Q', 'Ц': 'W', 'У': 'E', 'К': 'R', 'Е': 'T', 'Н': 'Y', 'Г': 'U', 'Ш': 'I', 'Щ': 'O', 'З': 'P', 'Х': '[', 'Ъ': ']',
        'Ф': 'A', 'Ы': 'S', 'В': 'D', 'А': 'F', 'П': 'G', 'Р': 'H', 'О': 'J', 'Л': 'K', 'Д': 'L', 'Ж': ';', 'Э': "'",
        'Я': 'Z', 'Ч': 'X', 'С': 'C', 'М': 'V', 'И': 'B', 'Т': 'N', 'Ь': 'M', 'Б': ',', 'Ю': '.'
    }
    if any(ord(c) >= 128 for c in val):
        val = "".join(keyboard_map.get(c, c) for c in val)
        
    # Strip any remaining non-ASCII/special characters
    val = "".join(c for c in val if ord(c) < 128 and c.isalnum())
    return val

# We need access to restart_bot function which was in main.py, or we can just emit an event or restart process directly.
def restart_bot():
    print("Restarting bot from UI...")
    os.execv(sys.executable, ['python'] + sys.argv)

def build_settings_view(page: ft.Page, lang: str):
    import httpx
    import asyncio
    is_web = getattr(page, "web", False)
    settings = dict(db.get_settings() or {})
    user_info = db.get_settings()
    active_orders = db.get_active_orders()
    has_active = len(active_orders) > 0
    
    # Get public IP for whitelist info box
    server_ip = "Unknown"
    try:
        import trading_engine
        px = trading_engine.get_binance_proxies()
        proxy_url = px.get("http") if px else None
        if proxy_url:
            with httpx.Client(proxy=proxy_url, timeout=5) as client:
                res = client.get("https://api.ipify.org?format=json")
                if res.status_code == 200:
                    server_ip = res.json().get("ip", "Unknown")
        else:
            res = httpx.get("https://api.ipify.org?format=json", timeout=5)
            if res.status_code == 200:
                server_ip = res.json().get("ip", "Unknown")
    except Exception:
        pass
        
    # --- Columns Setup ---
    autosave_timer = None

    def perform_autosave():
        try:
            db.update_api_keys(
                user_info.get("gemini_api_key") or "",
                binance_api_field.value.strip(),
                binance_secret_field.value.strip(),
                1 if use_proxy_sw.value else 0,
                proxy_url_field.value.strip()
            )
            
            if mode_dd.value == "DEMO" and demo_balance_field.value:
                try:
                    db.update_demo_balance(float(demo_balance_field.value))
                except Exception:
                    pass
            
            if size_mode == "PERCENT":
                val = f"{int(percent_slider.value)}%"
            else:
                val = (size_field.value or "100").strip()
                if "%" in val:
                    val = val.replace("%", "").strip()
            
            # Get last saved settings to fallback to the last valid trading pair
            db_settings = db.get_settings()
            fallback_pair = db_settings.get("trading_pair", "BTCUSDT") if db_settings else "BTCUSDT"
            fallback_tf = db_settings.get("timeframe", "1m") if db_settings else "1m"

            clean_pair = sanitize_symbol_input(pair_field.value)
            
            # Check if pair or timeframe is changed AND active orders exist
            pair_changed = (clean_pair != fallback_pair)
            tf_changed = (timeframe_dd.value != fallback_tf)
            
            if pair_changed or tf_changed:
                active_orders_list = db.get_active_orders()
                if active_orders_list:
                    # Revert values in UI
                    pair_field.value = fallback_pair
                    timeframe_dd.value = fallback_tf
                    
                    # Show error snack bar
                    msg = "Нельзя менять пару или таймфрейм при наличии активных ордеров!" if lang == "ru" else "Cannot change pair or timeframe when active orders exist!"
                    page.snack_bar = ft.SnackBar(
                        ft.Text(msg),
                        bgcolor="#ef4444",
                        duration=3000
                    )
                    page.snack_bar.open = True
                    page.update()
                    return
            
            market_type = market_type_dd.value or "SPOT"
            valid_symbols = get_binance_symbols(market_type)
            
            if clean_pair in valid_symbols:
                pair_to_save = clean_pair
                pair_field.label = "TRADING SYMBOL (PAIR)"
                pair_field.label_style = ft.TextStyle(color="#94a3b8", size=12, weight=ft.FontWeight.BOLD)
                pair_field.error_text = None
            else:
                pair_to_save = fallback_pair
                if clean_pair:
                    pair_field.label = f"TRADING SYMBOL (PAIR) - {t('invalid_symbol', lang, market_type=market_type)}"
                    pair_field.label_style = ft.TextStyle(color=RED_COLOR, size=12, weight=ft.FontWeight.BOLD)
                    pair_field.error_text = ""
                else:
                    pair_field.label = "TRADING SYMBOL (PAIR)"
                    pair_field.label_style = ft.TextStyle(color="#94a3b8", size=12, weight=ft.FontWeight.BOLD)
                    pair_field.error_text = None
            
            if clean_pair != pair_field.value:
                pair_field.value = clean_pair
            
            try:
                page.update()
            except Exception:
                pass

            db.save_settings(
                pair_to_save,
                timeframe_dd.value,
                val,
                settings.get("bot_enabled", 0),
                mode_dd.value,
                market_type,
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
            t_saved = t("settings_saved", lang)
            # No cache invalidation needed — dashboard_refresher uses continue not break
            try:
                page.snack_bar = ft.SnackBar(
                    ft.Text(t_saved), 
                    bgcolor=GREEN_COLOR, 
                    duration=1500
                )
                page.snack_bar.open = True
                page.update()
            except Exception:
                pass
            print("Autosaved settings!")
        except Exception as e:
            print(f"Autosave error: {e}")

    def trigger_autosave(e=None):
        nonlocal autosave_timer
        if autosave_timer is not None:
            autosave_timer.cancel()
        autosave_timer = threading.Timer(0.5, perform_autosave)
        autosave_timer.start()

    def trigger_autosave_instant(e=None):
        nonlocal autosave_timer
        if autosave_timer is not None:
            autosave_timer.cancel()
            autosave_timer = None
        perform_autosave()

    binance_api_field = make_textfield(label="Binance API Key", value=user_info.get("binance_api_key") or "", on_change=trigger_autosave)
    binance_secret_field = make_textfield(label="Binance API Secret", value=user_info.get("binance_api_secret") or "", password=True, can_reveal_password=True, on_change=trigger_autosave)
    use_proxy_sw = ft.Switch(
        label=t("use_proxy", lang),
        value=user_info.get("use_proxy", 0) == 1,
        on_change=trigger_autosave_instant,
        active_color="#0284c7"
    )
    proxy_url_field = make_textfield(
        label="PROXY URL",
        hint_text="http://user:pass@ip:port",
        value=user_info.get("proxy_url") or "",
        on_change=trigger_autosave
    )
        
    def make_glass_card(content_widget, col_sizes=None):
        return ft.Container(
            content=content_widget,
            bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
            padding=ft.Padding.all(24),
            border_radius=16,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
            blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
            col=col_sizes
        )

    ip_box = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_ROUNDED, color="#38bdf8", size=18),
                ft.Text(t("server_ip_notice", lang, ip=server_ip), size=12, color="#38bdf8", weight=ft.FontWeight.BOLD)
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        ),
        bgcolor=ft.Colors.with_opacity(0.1, "#38bdf8"),
        border=ft.Border.all(1, "#38bdf8"),
        padding=ft.Padding(15, 0, 15, 0),
        border_radius=8,
        height=48,
        alignment=ft.alignment.Alignment(-1.0, 0.0)
    )
    
    api_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.KEY_ROUNDED, color="#0284c7"), ft.Text(t("save_api", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                ft.Divider(color=ft.Colors.with_opacity(0.1, "#ffffff")),
                ip_box if server_ip != "Unknown" else ft.Container(),
                binance_api_field,
                binance_secret_field,
                use_proxy_sw,
                proxy_url_field
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
    )
    api_card.height = 460
    
    # Right Column: Trading Rules
    pair_field = make_textfield(
        label="TRADING SYMBOL (PAIR)",
        value=settings.get("trading_pair", "BTCUSDT"),
        hint_text=t("pair_hint", lang)
    )
    if has_active:
        pair_field.disabled = True
        pair_field.color = "#64748b"
        pair_field.border_color = ft.Colors.with_opacity(0.15, "#ffffff")
        pair_field.label_style = ft.TextStyle(color="#64748b", size=12, weight=ft.FontWeight.BOLD)
    else:
        pair_field.disabled = False

    suggestions_col = ft.Column(spacing=4, height=200, scroll=ft.ScrollMode.AUTO)
    suggestions_container = ft.Container(
        content=suggestions_col,
        bgcolor=CARD_COLOR,
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=8,
        padding=6,
        visible=False,
        top=115,
        left=0,
        right=0
    )

    def select_symbol(symbol):
        pair_field.value = symbol
        suggestions_container.visible = False
        pair_field.label = "TRADING SYMBOL (PAIR)"
        pair_field.label_style = ft.TextStyle(color="#94a3b8", size=12, weight=ft.FontWeight.BOLD)
        pair_field.error_text = None
        try:
            page.update()
        except Exception:
            pass
        perform_autosave()

    def make_suggestion_item(symbol):
        return ft.Container(
            content=ft.Text(symbol, color="#f8fafc", size=13, weight=ft.FontWeight.BOLD),
            padding=ft.Padding(12, 8, 12, 8),
            border_radius=6,
            on_click=lambda e: select_symbol(symbol),
            on_hover=lambda e: setattr(e.control, "bgcolor", ft.Colors.with_opacity(0.1, "#38bdf8") if e.data == "true" else None) or e.control.update()
        )

    def on_pair_field_change(e):
        val = sanitize_symbol_input(pair_field.value)
        
        market_type = market_type_dd.value or "SPOT"
        valid_symbols = get_binance_symbols(market_type)
        
        if not val:
            suggestions_container.visible = False
        else:
            matches = [s for s in valid_symbols if val in s]
            if len(matches) == 1 and matches[0] == val:
                suggestions_container.visible = False
            elif matches:
                suggestions_col.controls = [
                    make_suggestion_item(sym) for sym in matches[:6]
                ]
                suggestions_container.visible = True
            else:
                suggestions_container.visible = False
        
        try:
            suggestions_container.update()
        except Exception:
            pass
        trigger_autosave()

    def hide_suggestions_delayed(e=None):
        def do_hide():
            import time
            time.sleep(0.2)
            suggestions_container.visible = False
            try:
                page.update()
            except Exception:
                pass
        threading.Thread(target=do_hide, daemon=True).start()

    pair_field.on_change = on_pair_field_change
    pair_field.on_blur = hide_suggestions_delayed

    # Suggestions overlay will be rendered on top of fields via ft.Stack inside rules_card
    
    timeframe_dd = make_dropdown(
        label=t("timeframe", lang).upper(),
        options=[
            ft.dropdown.Option("1m", "1m"),
            ft.dropdown.Option("3m", "3m"),
            ft.dropdown.Option("5m", "5m"),
            ft.dropdown.Option("15m", "15m"),
            ft.dropdown.Option("30m", "30m"),
            ft.dropdown.Option("1h", "1h")
        ],
        value=settings.get("timeframe", "1m"),
        on_change=trigger_autosave_instant
    )
    if has_active:
        timeframe_dd.disabled = True
        timeframe_dd.color = "#64748b"
        timeframe_dd.border_color = ft.Colors.with_opacity(0.15, "#ffffff")
        timeframe_dd.label_style = ft.TextStyle(color="#64748b", size=12, weight=ft.FontWeight.BOLD)
    else:
        timeframe_dd.disabled = False
    
    is_bot_enabled = settings.get("bot_enabled", 0) == 1
    if is_bot_enabled:
        warning_text = (
            "Внимание: изменение настроек заблокировано! Пожалуйста, остановите бота на панели управления и закройте все активные ордера."
            if lang == "ru" else
            "Warning: settings are locked! Please stop the bot on the dashboard and close all active orders."
        )
    else:
        warning_text = (
            "Внимание: изменение настроек заблокировано при наличии открытых ордеров! Закройте все активные ордера, чтобы разблокировать параметры."
            if lang == "ru" else
            "Warning: settings are locked because open orders exist! Close all active orders to unlock parameters."
        )
    warning_box = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WARNING_ROUNDED, color="#f59e0b", size=18),
                ft.Text(warning_text, size=11, color="#f59e0b", weight=ft.FontWeight.W_500, expand=True)
            ],
            spacing=8
        ),
        bgcolor=ft.Colors.with_opacity(0.1, "#f59e0b"),
        border=ft.Border.all(1, "#f59e0b"),
        padding=10,
        border_radius=8,
        visible=has_active
    )
    
    market_options = [
        ("SPOT", t("spot", lang)),
        ("FUTURES", t("futures", lang))
    ]

    market_type_dd = make_dropdown(
        label=t("market_type", lang).upper(),
        options=[ft.dropdown.Option(k, v) for k, v in market_options],
        value=settings.get("market_type", "SPOT"),
        on_change=trigger_autosave_instant
    )
    if has_active:
        market_type_dd.disabled = True
        market_type_dd.color = "#64748b"
        market_type_dd.border_color = ft.Colors.with_opacity(0.15, "#ffffff")
        market_type_dd.label_style = ft.TextStyle(color="#64748b", size=12, weight=ft.FontWeight.BOLD)
    else:
        market_type_dd.disabled = False
    
    def on_trading_mode_change(e):
        is_demo = (mode_dd.value == "DEMO")
        demo_balance_card.disabled = not is_demo
        demo_balance_card.opacity = 1.0 if is_demo else 0.4
        page.update()
        trigger_autosave_instant()

    mode_options = [
        ("DEMO", t("demo_mode", lang)),
        ("LIVE", t("live_mode", lang))
    ]

    mode_dd = make_dropdown(
        label=t("trading_mode_label", lang).upper(),
        options=[ft.dropdown.Option(k, v) for k, v in mode_options],
        value=settings.get("trading_mode", "DEMO"),
        on_change=on_trading_mode_change
    )
    if has_active:
        mode_dd.disabled = True
        mode_dd.color = "#64748b"
        mode_dd.border_color = ft.Colors.with_opacity(0.15, "#ffffff")
        mode_dd.label_style = ft.TextStyle(color="#64748b", size=12, weight=ft.FontWeight.BOLD)
    else:
        mode_dd.disabled = False
    
    prob_options = [
        ("0.55", "55% (Агрессивная)" if lang == "ru" else "55% (Aggressive)"),
        ("0.60", "60% (Частая торговля)" if lang == "ru" else "60% (Active)"),
        ("0.65", "65% (Оптимальная)" if lang == "ru" else "65% (Recommended)"),
        ("0.70", "70% (Сбалансированная)" if lang == "ru" else "70% (Balanced)"),
        ("0.75", "75% (Умеренная)" if lang == "ru" else "75% (Moderate)"),
        ("0.80", "80% (Повышенная)" if lang == "ru" else "80% (High Confidence)"),
        ("0.85", "85% (Строгая)" if lang == "ru" else "85% (Strict)"),
        ("0.88", "88% (Высокая строжайшая)" if lang == "ru" else "88% (Very Strict)"),
        ("0.90", "90% (Максимально строгая)" if lang == "ru" else "90% (Max Strict)"),
        ("0.93", "93% (Ультра-строгая)" if lang == "ru" else "93% (Ultra Strict)"),
        ("0.95", "95% (Премиальная)" if lang == "ru" else "95% (Premium)"),
        ("0.98", "98% (Экстремальная)" if lang == "ru" else "98% (Extreme)"),
        ("1.00", "100% (Абсолютная)" if lang == "ru" else "100% (Absolute)")
    ]

    curr_prob_val = settings.get("min_probability_threshold", 0.65)
    if isinstance(curr_prob_val, (int, float)):
        curr_prob_str = f"{curr_prob_val:.2f}"
    else:
        curr_prob_str = str(curr_prob_val)

    prob_field = make_dropdown(
        label=t("classifier_threshold", lang),
        options=[ft.dropdown.Option(k, v) for k, v in prob_options],
        value=curr_prob_str,
        on_change=trigger_autosave_instant
    )
    
    # Segment toggles for Fixed vs Percent size
    is_pct = "%" in str(settings.get("order_size_usdt", "100"))
    size_mode = "PERCENT" if is_pct else "FIXED"
    
    # Parse initial percent value
    init_pct_val = 50
    if is_pct:
        try:
            init_pct_val = int(str(settings.get("order_size_usdt", "50")).replace("%", "").strip())
        except ValueError:
            init_pct_val = 50
            
    percent_slider = ft.Slider(
        min=1,
        max=100,
        divisions=100,
        value=init_pct_val,
        on_change=lambda e: update_percent_label(e.control.value),
        active_color="#0284c7"
    )
    percent_label = ft.Text(f"{init_pct_val}%", size=14, color="#f8fafc", weight=ft.FontWeight.BOLD)
    
    slider_container = ft.Column([
        ft.Row([
            ft.Text(t("pos_size_label_pct", lang), size=12, color="#94a3b8"),
            percent_label
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        percent_slider
    ], spacing=4)

    def update_percent_label(val):
        percent_label.value = f"{int(val)}%"
        page.update()
        trigger_autosave_instant()

    size_val_str = str(settings.get("order_size_usdt", 100))
    if "%" in size_val_str:
        size_val_str = size_val_str.replace("%", "").strip()
    size_field = make_textfield(label=t("pos_size_label_fixed", lang), value=size_val_str, on_change=trigger_autosave)
    leverage_field = make_textfield(label=t("futures_leverage", lang), value=str(settings.get("futures_leverage", 10)), on_change=trigger_autosave)
    
    def set_size_mode(mode):
        nonlocal size_mode
        size_mode = mode
        if mode == "FIXED":
            fixed_btn.bgcolor = TEXT_PRIMARY
            fixed_btn.content.color = "#030407"
            percent_btn.bgcolor = ft.Colors.TRANSPARENT
            percent_btn.content.color = TEXT_SECONDARY
            
            try:
                # If switching to FIXED, preset the textfield value to the slider's value
                size_field.value = str(int(percent_slider.value))
            except Exception:
                pass
                
            size_field.visible = True
            slider_container.visible = False
        else:
            fixed_btn.bgcolor = ft.Colors.TRANSPARENT
            fixed_btn.content.color = TEXT_SECONDARY
            percent_btn.bgcolor = TEXT_PRIMARY
            percent_btn.content.color = "#030407"
            
            try:
                # If switching to PERCENT, try to parse current textfield value into slider
                val_num = int(float(size_field.value.replace("%", "").strip()))
                if 1 <= val_num <= 100:
                    percent_slider.value = val_num
                    percent_label.value = f"{val_num}%"
            except Exception:
                pass
                
            size_field.visible = False
            slider_container.visible = True
        page.update()
        trigger_autosave_instant()
        
    fixed_btn = ft.Container(
        content=ft.Text(t("pos_size_label_fixed", lang).split(" (")[0], size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
        padding=ft.Padding.symmetric(vertical=8, horizontal=20),
        border_radius=6,
        expand=True,
        on_click=lambda _: set_size_mode("FIXED")
    )
    percent_btn = ft.Container(
        content=ft.Text(t("pos_size_pct", lang), size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
        padding=ft.Padding.symmetric(vertical=8, horizontal=20),
        border_radius=6,
        expand=True,
        on_click=lambda _: set_size_mode("PERCENT")
    )
    
    # Initialize styles and visibility based on load state
    if is_pct:
        fixed_btn.bgcolor = ft.Colors.TRANSPARENT
        fixed_btn.content.color = TEXT_SECONDARY
        percent_btn.bgcolor = TEXT_PRIMARY
        percent_btn.content.color = "#030407"
        size_field.visible = False
        slider_container.visible = True
    else:
        fixed_btn.bgcolor = TEXT_PRIMARY
        fixed_btn.content.color = "#030407"
        percent_btn.bgcolor = ft.Colors.TRANSPARENT
        percent_btn.content.color = TEXT_SECONDARY
        size_field.visible = True
        slider_container.visible = False
        
    size_mode_selector = ft.Container(
        content=ft.Row([fixed_btn, percent_btn], spacing=0, tight=True),
        border=ft.Border.all(1, BORDER_COLOR),
        border_radius=8,
        bgcolor=CARD_ACCENT,
        padding=2,
        expand=True
    )
    
    main_column = ft.Column(
        [
            ft.Row([ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color="#0284c7"), ft.Text(t("save_rules", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
            ft.Divider(color=ft.Colors.with_opacity(0.1, "#ffffff")),
            warning_box,
            pair_field,
            timeframe_dd,
            market_type_dd,
            mode_dd,
            prob_field,
            ft.Container(height=4),
            ft.Text(t("position_size_title", lang), size=11, color="#94a3b8", weight=ft.FontWeight.BOLD),
            ft.Row([size_mode_selector], expand=True),
            size_field,
            slider_container,
            leverage_field,
            ft.Container(height=4)
        ],
        spacing=12,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH
    )

    rules_card = make_glass_card(
        ft.Stack(
            [
                main_column,
                suggestions_container
            ]
        )
    )
    rules_card.height = 720
    
    # Demo Balance card
    demo_balance_field = make_textfield(
        label=t("demo_balance_lbl", lang),
        value=f"{settings.get('demo_balance', 10000.0):.2f}",
        on_change=trigger_autosave
    )
    
    demo_balance_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, color="#0284c7"), ft.Text(t("balance_mgmt_title", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                ft.Divider(color=ft.Colors.with_opacity(0.1, "#ffffff")),
                ft.Text(t("balance_mgmt_desc", lang), size=12, color="#94a3b8"),
                demo_balance_field,
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
    )
    demo_balance_card.height = 240
    is_demo_init = (settings.get("trading_mode", "DEMO") == "DEMO")
    demo_balance_card.disabled = not is_demo_init
    demo_balance_card.opacity = 1.0 if is_demo_init else 0.4
    
    right_column = ft.Column(
        [
            rules_card
        ],
        spacing=20,
        col={"xs": 12, "md": 6}
    )
    
    left_column = ft.Column(
        [
            api_card,
            demo_balance_card
        ],
        spacing=20,
        col={"xs": 12, "md": 6}
    )
    
    # Bottom full-width row: Smart logic switches & Risk Limits
    invert_signal_sw = ft.Switch(value=settings.get("invert_signal", 0) == 1, on_change=trigger_autosave_instant)
    # Limit order components
    def on_limit_change(e):
        page.update()
        trigger_autosave_instant()

    is_limit_active = (settings.get("use_limit_orders", 1) == 1)
    use_limit_sw = ft.Switch(value=is_limit_active, on_change=on_limit_change)
    use_ai_limit_sw = ft.Switch(value=settings.get("use_ai_limit_price", 0) == 1, on_change=trigger_autosave_instant)
    use_ai_exit_sw = ft.Switch(value=settings.get("use_ai_exit", 0) == 1, on_change=trigger_autosave_instant)
    
    # Trailing Stop components
    def on_trailing_change(e):
        is_active = use_trailing_sw.value
        use_ai_trailing_sw.disabled = not is_active
        trailing_activation_field.disabled = not is_active
        trailing_step_field.disabled = not is_active
        
        # When trailing is enabled, standard AI TP/SL targets are disabled
        use_ai_limit_sw.disabled = is_active
        if is_active:
            use_ai_limit_sw.value = False
            
        if not is_active:
            use_ai_trailing_sw.value = False
        page.update()
        trigger_autosave_instant()

    is_trailing_active = (settings.get("use_trailing_stop", 1) == 1)
    use_trailing_sw = ft.Switch(value=is_trailing_active, on_change=on_trailing_change)
    use_ai_trailing_sw = ft.Switch(value=settings.get("use_ai_trailing", 0) == 1 and is_trailing_active, disabled=not is_trailing_active, on_change=trigger_autosave_instant)
    trailing_activation_field = make_textfield(value=str(settings.get("trailing_activation_pct", 0.5)), width=80, on_change=trigger_autosave)
    trailing_activation_field.disabled = not is_trailing_active
    trailing_step_field = make_textfield(value=str(settings.get("trailing_step_pct", 0.2)), width=80, on_change=trigger_autosave)
    trailing_step_field.disabled = not is_trailing_active
    
    # Initialize use_ai_limit_sw state based on trailing stop status
    if is_trailing_active:
        use_ai_limit_sw.disabled = True
        use_ai_limit_sw.value = False
    
    # Risk limits
    loss_limit_field = make_textfield(label=t("daily_loss_limit_title", lang), value=str(settings.get("daily_loss_limit", 0)), on_change=trigger_autosave)
    profit_target_field = make_textfield(label=t("daily_profit_target_title", lang), value=str(settings.get("daily_profit_target", 0)), on_change=trigger_autosave)
    

    # Helper layout box for switches
    def make_switch_box(title, switch_ctrl, desc):
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                            ft.Text(desc, size=11, color="#94a3b8")
                        ],
                        expand=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=4
                    ),
                    switch_ctrl
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER
            ),
            bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
            padding=ft.Padding(15, 0, 15, 0),
            border_radius=8,
            border=ft.Border.all(1, ft.Colors.TRANSPARENT),
            col={"xs": 12, "md": 6},
            height=80,
            alignment=ft.alignment.Alignment(-1.0, 0.0)
        )
        
    switches_row = ft.ResponsiveRow(
        [
            make_switch_box(t("invert_signal_title", lang), invert_signal_sw, t("invert_signal_desc", lang)),
            make_switch_box(t("use_limit_orders_title", lang), use_limit_sw, t("use_limit_orders_desc", lang)),
            make_switch_box(t("ai_trade_range_title", lang), use_ai_limit_sw, t("ai_trade_range_desc", lang)),
            make_switch_box(t("ai_exit_title", lang), use_ai_exit_sw, t("ai_exit_desc", lang))
        ],
        spacing=10
    )
    
    trailing_stop_box = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(t("trailing_stop_title", lang), size=12, weight=ft.FontWeight.BOLD, color="#fbbf24"),
                        ft.Text(t("trailing_stop_desc", lang), size=11, color="#94a3b8")
                    ],
                    expand=True
                ),
                ft.Row(
                    [
                        ft.Text(t("ai_trailing_title", lang), size=11, color="#f8fafc"),
                        use_ai_trailing_sw,
                        ft.Text(t("trailing_activation_title", lang), size=11, color="#f8fafc"),
                        trailing_activation_field,
                        ft.Text(t("trailing_step_title", lang), size=11, color="#f8fafc"),
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
        bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
        padding=15,
        border_radius=8,
        border=ft.Border.all(1, ft.Colors.TRANSPARENT)
    )
    
    risk_limits_box = ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.SHIELD_ROUNDED, color="#ef4444", size=16), ft.Text(t("risk_limits_title", lang), size=12, weight=ft.FontWeight.BOLD, color="#ef4444")]),
                ft.Text(t("risk_limits_desc", lang), size=11, color="#94a3b8"),
                ft.Row([ft.Container(content=loss_limit_field, expand=True), ft.Container(content=profit_target_field, expand=True)], spacing=15)
            ],
            spacing=10
        ),
        bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
        padding=15,
        border_radius=8,
        border=ft.Border.all(1, ft.Colors.TRANSPARENT)
    )
    
    smart_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color="#38bdf8"), ft.Text(t("smart_logic_title", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                ft.Divider(color=ft.Colors.with_opacity(0.1, "#ffffff")),
                switches_row,
                ft.Container(height=10),
                trailing_stop_box,
                ft.Container(height=10),
                risk_limits_box,
                ft.Container(height=10),
                ft.Container(height=10)
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )
    
    main_row = ft.ResponsiveRow(
        [
            left_column,
            right_column,
            smart_card
        ],
        spacing=20
    )
    
    return main_row
