import flet as ft
import db
from ui.theme import *
from ui.i18n import t

def handle_nav_change(page, index):
    if index == 0:
        page.go("/dashboard")
    elif index == 1:
        page.go("/history")
    elif index == 2:
        page.go("/decisions")
    elif index == 3:
        page.go("/settings")

def logout(page):
    page.session.store.clear()
    page.go("/login")

def change_language(page, new_lang):
    page.session.store.set("lang", new_lang)
    db.save_ui_settings(page.session.store.get("user_id"), new_lang, 1)
    # Using page.go to trigger route change refresh
    # To keep same route but trigger change, we can toggle route
    current = page.route
    page.go("/loading")
    page.go(current)

def check_auth(page):
    return page.session.store.get("user_id") is not None

def build_layout(page: ft.Page, content_control, active_index, lang):
    is_mobile = page.width < 768
    
    # 3-stage Ensemble ML CSV exports
    def export_ai_logs_csv(e):
        import csv
        import os
        try:
            user_id = page.session.store.get("user_id")
            logs = db.get_all_analysis_logs(user_id)
            file_path = os.path.abspath("ai_analysis_logs.csv")
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Pair", "Created At", "Technical Indicators",
                    "Stage 1 Output (Sentiment)", "Stage 2 Output (Predictions)", "Stage 3 Output (Execution)"
                ])
                for l in logs:
                    writer.writerow([
                        l["id"], l["pair"], l["created_at"], l["indicators_summary"],
                        l["stage1_output"], l["stage2_output"], l["stage3_output"]
                    ])
            page.snack_bar = ft.SnackBar(ft.Text(f"AI logs exported successfully to {file_path}!"), bgcolor=GREEN_COLOR)
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()

    def export_combined_csv(e):
        import csv
        import os
        import json
        try:
            user_id = page.session.store.get("user_id")
            conn = db.get_db_connection()
            conn.row_factory = db.sqlite3.Row
            orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
            
            file_path = os.path.abspath("combined_trading_history.csv")
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Order ID", "Symbol / Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
                    "Amount (Qty)", "Margin Size (USDT)", "Leverage", "Order Status", "Trading Mode", "Market Type",
                    "Order Created At", "Order Closed At", "Realized PnL (USDT)",
                    "AI Signal Action", "AI Confidence / Probability", "AI Stage 3 Reason", "AI Technical Indicators"
                ])
                for o in orders:
                    log = conn.execute("""
                        SELECT * FROM analysis_logs 
                        WHERE user_id = ? AND pair = ? AND created_at <= ? 
                        ORDER BY created_at DESC LIMIT 1
                    """, (user_id, o["pair"], o["created_at"])).fetchone()
                    
                    ai_action = "N/A"
                    ai_prob = "N/A"
                    ai_reason = "N/A"
                    ai_indicators = "N/A"
                    
                    if log:
                        ai_indicators = log["indicators_summary"] or "N/A"
                        try:
                            s3 = json.loads(log["stage3_output"])
                            ai_action = s3.get("action", "HOLD")
                            ai_prob = f"{s3.get('probability', 0.0) * 100:.2f}%"
                            ai_reason = s3.get("reason", "N/A")
                        except Exception:
                            pass
                            
                    writer.writerow([
                        o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"], o["take_profit"],
                        o["amount"], o["size_usdt"], o["leverage"], o["status"], o["trading_mode"], o["market_type"],
                        o["created_at"], o["closed_at"], o["pnl"],
                        ai_action, ai_prob, ai_reason, ai_indicators
                    ])
            conn.close()
            page.snack_bar = ft.SnackBar(ft.Text(f"Combined report exported to {file_path}!"), bgcolor=GREEN_COLOR)
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()

    def export_orders_csv(e):
        import csv
        import os
        try:
            user_id = page.session.store.get("user_id")
            conn = db.get_db_connection()
            orders = conn.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
            conn.close()
            
            file_path = os.path.abspath("orders_history.csv")
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
                    "Amount", "Size USDT", "Leverage", "Status", "PnL", "Trading Mode",
                    "Market Type", "Created At", "Closed At"
                ])
                for o in orders:
                    writer.writerow([
                        o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"], o["take_profit"],
                        o["amount"], o["size_usdt"], o["leverage"], o["status"], o["pnl"], o["trading_mode"],
                        o["market_type"], o["created_at"], o["closed_at"]
                    ])
            page.snack_bar = ft.SnackBar(ft.Text(f"Orders history exported to {file_path}!"), bgcolor=GREEN_COLOR)
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()

    if is_mobile:
        appbar = ft.AppBar(
            title=ft.Text("Nexus AI", size=18, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
            bgcolor=CARD_COLOR,
            center_title=True,
            actions=[
                ft.IconButton(
                    icon=ft.Icons.LOGOUT_ROUNDED,
                    tooltip=t("logout", lang),
                    icon_color=RED_COLOR,
                    on_click=lambda _: logout(page)
                )
            ]
        )
        nav_bar = ft.NavigationBar(
            selected_index=active_index,
            destinations=[
                ft.NavigationDestination(icon=ft.Icons.DASHBOARD_ROUNDED, label="Terminal"),
                ft.NavigationDestination(icon=ft.Icons.HISTORY_ROUNDED, label="Orders"),
                ft.NavigationDestination(icon=ft.Icons.PSYCHOLOGY_ROUNDED, label="AI"),
                ft.NavigationDestination(icon=ft.Icons.SETTINGS_ROUNDED, label="Settings"),
            ],
            on_change=lambda e: handle_nav_change(page, e.control.selected_index),
            bgcolor=CARD_COLOR
        )
        return ft.View(
            route=page.route,
            controls=[
                ft.Container(
                    image=ft.DecorationImage(src="/background.avif", fit=ft.BoxFit.COVER),
                    expand=True,
                    content=ft.Column([
                        appbar,
                        ft.Container(content=ft.Column([content_control], scroll=ft.ScrollMode.AUTO, expand=True), expand=True, padding=12),
                        nav_bar
                    ])
                )
            ],
            padding=0
        )
    else:
        logo_row = ft.Row(
            [
                ft.Icon(ft.Icons.HUB_ROUNDED, color=GOLD_COLOR, size=24),
                ft.Text("Nexus AI", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        )
        logo_btn = ft.Container(
            content=logo_row,
            on_click=lambda _: page.go("/dashboard") if check_auth(page) else None
        )

        def make_nav_link(text, route, is_active, icon_name):
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon_name, size=16, color=GOLD_COLOR if is_active else TEXT_SECONDARY),
                        ft.Text(text, size=13, weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL, color=TEXT_PRIMARY if is_active else TEXT_SECONDARY)
                    ],
                    spacing=6
                ),
                padding=ft.Padding.only(bottom=4),
                border=ft.Border.only(bottom=ft.BorderSide(2, GOLD_COLOR)) if is_active else None,
                on_click=lambda _: page.go(route),
                
            )

        files_menu = ft.PopupMenuButton(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=16, color=TEXT_SECONDARY),
                    ft.Text("Файлы", size=13, color=TEXT_SECONDARY),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, size=14, color=TEXT_SECONDARY)
                ],
                spacing=4
            ),
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.FILE_DOWNLOAD_ROUNDED, color=GOLD_COLOR, size=16), ft.Text("Сводный отчет (CSV)", size=12)]),
                    on_click=export_combined_csv
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.FILE_DOWNLOAD_ROUNDED, color="#38bdf8", size=16), ft.Text("Экспорт ордеров (CSV)", size=12)]),
                    on_click=export_orders_csv
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.INSERT_DRIVE_FILE_ROUNDED, color=GREEN_COLOR, size=16), ft.Text("Экспорт решений ИИ (CSV)", size=12)]),
                    on_click=export_ai_logs_csv
                )
            ]
        )

        settings_link = make_nav_link("Настройки", "/settings", active_index == 3, ft.Icons.SETTINGS_ROUNDED)

        logout_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LOGOUT_ROUNDED, size=14, color=RED_COLOR),
                    ft.Text("Выйти", size=12, color=TEXT_PRIMARY)
                ],
                spacing=4
            ),
            padding=ft.Padding.symmetric(vertical=8, horizontal=12),
            border_radius=8,
            bgcolor=CARD_ACCENT,
            border=ft.Border.all(1, BORDER_COLOR),
            on_click=lambda _: logout(page)
        )

        def make_lang_badge(lang_code, label):
            is_active = (lang == lang_code)
            return ft.Container(
                content=ft.Text(label, size=10, weight=ft.FontWeight.BOLD, color="#030407" if is_active else TEXT_SECONDARY),
                padding=ft.Padding.symmetric(vertical=4, horizontal=8),
                border_radius=4,
                bgcolor=GOLD_COLOR if is_active else ft.Colors.TRANSPARENT,
                on_click=lambda _: change_language(page, lang_code),
                
            )

        lang_row = ft.Row(
            [
                make_lang_badge("en", "EN"),
                make_lang_badge("ru", "RU"),
                make_lang_badge("uk", "UA")
            ],
            spacing=4
        )

        navbar = ft.Container(
            content=ft.Row(
                [
                    logo_btn,
                    ft.Row(
                        [
                            make_nav_link("Торговый терминал", "/dashboard", active_index == 0, ft.Icons.SHOW_CHART_ROUNDED),
                            make_nav_link("Все ордера", "/history", active_index == 1, ft.Icons.LIST_ALT_ROUNDED),
                            make_nav_link("AI Decisions", "/decisions", active_index == 2, ft.Icons.PSYCHOLOGY_ROUNDED),
                            files_menu,
                            settings_link,
                            logout_btn,
                            lang_row
                        ],
                        spacing=20,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER
                    )
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER
            ),
            bgcolor=CARD_COLOR,
            padding=ft.Padding.symmetric(vertical=12, horizontal=30),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER_COLOR))
        )

        return ft.View(
            route=page.route,
            controls=[
                ft.Container(
                    image=ft.DecorationImage(src="/background.avif", fit=ft.BoxFit.COVER),
                    expand=True,
                    content=ft.Column([
                        navbar,
                        ft.Container(content=ft.Column([content_control], scroll=ft.ScrollMode.AUTO, expand=True), expand=True, padding=20)
                    ])
                )
            ],
            padding=0
        )
