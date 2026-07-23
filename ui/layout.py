import flet as ft
import db
from ui.theme import *
from ui.styles import *
from ui.i18n import t

ROUTE_INDEX = {
    "/dashboard": 0,
    "/history": 1,
    "/decisions": 2,
    "/settings": 3,
}

def handle_nav_change(page, index):
    routes = ["/dashboard", "/history", "/decisions", "/settings"]
    if 0 <= index < len(routes):
        page.go(routes[index])

def change_language(page, new_lang):
    page.session.store.set("lang", new_lang)
    db.save_ui_settings(new_lang, 1)
    page.pubsub.send_all_on_topic("lang_changed", new_lang)

def check_auth(page):
    return True


# ────────────────────────────────────────────────────────────
# CSV export helpers (module-level so they survive shell reuse)
# ────────────────────────────────────────────────────────────

def _export_ai_logs_csv(page, e):
    import csv, os
    try:
        logs = db.get_all_analysis_logs()
        fp = os.path.abspath("ai_analysis_logs.csv")
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ID", "Pair", "Created At", "Technical Indicators",
                        "Stage 1 Output", "Stage 2 Output", "Stage 3 Output"])
            for l in logs:
                w.writerow([l["id"], l["pair"], l["created_at"], l["indicators_summary"],
                             l["stage1_output"], l["stage2_output"], l["stage3_output"]])
        page.snack_bar = ft.SnackBar(ft.Text(f"AI logs exported to {fp}!"), bgcolor=GREEN_COLOR)
        page.snack_bar.open = True
        page.update()
    except Exception as ex:
        page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
        page.snack_bar.open = True
        page.update()


async def _export_ai_model(page, e):
    import os, sys, asyncio, shutil
    try:
        settings_row = db.get_settings()
        pair = (settings_row["trading_pair"] if settings_row else "ETHUSDC").upper()
        tf = settings_row["timeframe"] if settings_row else "3m"
    except Exception:
        pair = "ETHUSDC"
        tf = "3m"
        
    src_path = f"models/{pair}_{tf}.pkl"
    # If model is not yet saved to disk, trigger save from memory
    if not os.path.exists(src_path):
        import scalping_ensemble
        if getattr(scalping_ensemble, "dlinear_model", None) is not None:
            os.makedirs("models", exist_ok=True)
            scalping_ensemble.save_models_to_disk(pair, tf)

    is_web = getattr(page, "web", False)

    # Desktop OS-specific save handler
    def show_save_dialog_desktop(pair, tf):
        import sys
        if sys.platform == "darwin":
            # Native macOS AppleScript save dialog (avoids NSWindow thread crash)
            default_name = f"model_{pair}_{tf}.pkl"
            script = f'tell application "System Events" to POSIX path of (choose file name with prompt "Сохранить модель ИИ" default name "{default_name}")'
            try:
                import subprocess
                proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
                if proc.returncode == 0:
                    return proc.stdout.strip()
            except:
                pass
            return ""
        else:
            # Fallback for Windows/Linux
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.lift()
            root.attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                title="Сохранить модель ИИ",
                initialfile=f"model_{pair}_{tf}.pkl",
                defaultextension=".pkl",
                filetypes=[("Pickle files", "*.pkl"), ("All files", "*.*")]
            )
            root.destroy()
            return path

    if is_web:
        # Web mode download
        if os.path.exists(src_path):
            page.launch_url(f"/models/{pair}_{tf}.pkl")
        else:
            page.snack_bar = ft.SnackBar(
                ft.Text("⚠️ Модель еще не обучена. Запустите бота для обучения."), 
                bgcolor=RED_COLOR
            )
            page.snack_bar.open = True
            page.update()
    else:
        # Desktop mode save dialog
        save_path = await asyncio.to_thread(show_save_dialog_desktop, pair, tf)
        if not save_path:
            return
        try:
            if os.path.exists(src_path):
                shutil.copy(src_path, save_path)
                page.snack_bar = ft.SnackBar(
                    ft.Text(f"✓ Модель для {pair} ({tf}) успешно экспортирована!"), 
                    bgcolor=GREEN_COLOR
                )
            else:
                page.snack_bar = ft.SnackBar(
                    ft.Text("⚠️ Модель еще не обучена. Запустите бота для обучения."), 
                    bgcolor=RED_COLOR
                )
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"❌ Ошибка экспорта: {ex}"), bgcolor=RED_COLOR)
            page.snack_bar.open = True
            page.update()


def _export_combined_csv(page, e):
    import csv, os, json
    try:
        conn = db.get_db_connection()
        conn.row_factory = db.sqlite3.Row
        orders = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        fp = os.path.abspath("combined_trading_history.csv")
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Order ID", "Symbol / Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
                        "Amount (Qty)", "Margin Size (USDT)", "Leverage", "Order Status", "Trading Mode",
                        "Market Type", "Order Created At", "Order Closed At", "Realized PnL (USDT)",
                        "AI Signal Action", "AI Confidence / Probability", "AI Stage 3 Reason", "AI Technical Indicators"])
            for o in orders:
                log = conn.execute("""SELECT * FROM analysis_logs WHERE pair = ? AND created_at <= ?
                                      ORDER BY created_at DESC LIMIT 1""",
                                   (o["pair"], o["created_at"])).fetchone()
                ai_action = ai_prob = ai_reason = ai_ind = "N/A"
                if log:
                    ai_ind = log["indicators_summary"] or "N/A"
                    try:
                        s3 = json.loads(log["stage3_output"])
                        ai_action = s3.get("action", "HOLD")
                        ai_prob = f"{s3.get('probability', 0.0) * 100:.2f}%"
                        ai_reason = s3.get("reason", "N/A")
                    except Exception:
                        pass
                w.writerow([o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"],
                             o["take_profit"], o["amount"], o["size_usdt"], o["leverage"],
                             o["status"], o["trading_mode"], o["market_type"],
                             o["created_at"], o["closed_at"], o["pnl"],
                             ai_action, ai_prob, ai_reason, ai_ind])
        conn.close()
        page.snack_bar = ft.SnackBar(ft.Text(f"Combined report exported to {fp}!"), bgcolor=GREEN_COLOR)
        page.snack_bar.open = True
        page.update()
    except Exception as ex:
        page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
        page.snack_bar.open = True
        page.update()


def _export_orders_csv(page, e):
    import csv, os
    try:
        conn = db.get_db_connection()
        orders = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        conn.close()
        fp = os.path.abspath("orders_history.csv")
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ID", "Pair", "Side", "Entry Price", "Stop Loss", "Take Profit",
                        "Amount", "Size USDT", "Leverage", "Status", "PnL", "Trading Mode",
                        "Market Type", "Created At", "Closed At"])
            for o in orders:
                w.writerow([o["id"], o["pair"], o["side"], o["entry_price"], o["stop_loss"],
                             o["take_profit"], o["amount"], o["size_usdt"], o["leverage"],
                             o["status"], o["pnl"], o["trading_mode"],
                             o["market_type"], o["created_at"], o["closed_at"]])
        page.snack_bar = ft.SnackBar(ft.Text(f"Orders exported to {fp}!"), bgcolor=GREEN_COLOR)
        page.snack_bar.open = True
        page.update()
    except Exception as ex:
        page.snack_bar = ft.SnackBar(ft.Text(f"Export failed: {ex}"), bgcolor=RED_COLOR)
        page.snack_bar.open = True
        page.update()


# ────────────────────────────────────────────────────────────
# Persistent shell builder
# ────────────────────────────────────────────────────────────

def _wrap_content(content_control, route):
    """Wrap page content in the correct scrollable container."""
    return ft.Container(
        content=ft.Column(
            [content_control],
            scroll=None if route in ["/history", "/decisions"] else ft.ScrollMode.AUTO,
            expand=True,
        ),
        expand=True,
        padding=20,
    )


def build_layout(page: ft.Page, content_control, active_index: int, lang: str):
    """
    Persistent-shell layout manager.
    First call: builds the shell (navbar + AnimatedSwitcher) and returns the ft.View.
    Subsequent calls: updates nav active state + content area in place, returns same view.
    """

    # ── Invalid-width fallback (web only) ───────────────────
    if getattr(page, "_is_invalid_width", False):
        return ft.View(
            route=page.route,
            controls=[
                ft.Container(
                    image=ft.DecorationImage(src="/background.jpg", fit=ft.BoxFit.COVER),
                    expand=True,
                    content=ft.Container(
                        bgcolor=ft.Colors.with_opacity(0.8, "#0f172a"),
                        expand=True,
                        alignment=ft.alignment.Alignment(0, 0),
                        content=ft.Column([
                            ft.Icon(ft.Icons.DESKTOP_MAC_ROUNDED, size=64, color=GOLD_COLOR),
                            ft.Text(
                                {"en": "Insufficient Screen Size", "ru": "Недостаточный размер экрана", "uk": "Недостатній розмір екрану"}.get(lang, "Insufficient Screen Size"),
                                size=24, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY, text_align=ft.TextAlign.CENTER
                            ),
                            ft.Text(
                                {"en": "Please open the terminal on PC or increase window width.", "ru": "Пожалуйста, откройте терминал на ПК или увеличьте ширину окна.", "uk": "Будь ласка, відкрийте термінал на ПК або збільшіть ширину вікна."}.get(lang, "Please open the terminal on PC or increase window width."),
                                size=16, color=TEXT_SECONDARY, text_align=ft.TextAlign.CENTER
                            ),
                            ft.Text(
                                ({"en": "Current width: {}px (Minimum: 1100px)", "ru": "Текущая ширина: {}px (Минимум: 1100px)", "uk": "Поточна ширина: {}px (Мінімум: 1100px)"}.get(lang, "Current width: {}px (Minimum: 1100px)")).format(page.width),
                                size=14, color=TEXT_SECONDARY, text_align=ft.TextAlign.CENTER
                            ),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                           alignment=ft.MainAxisAlignment.CENTER, spacing=16),
                    ),
                )
            ],
            padding=0,
        )

    shell = getattr(page, "_persistent_shell", None)

    # ── Update existing shell ────────────────────────────────
    if shell is not None:
        # Update nav active indicators
        for route, refs in shell["nav_refs"].items():
            is_active = (route == page.route)
            refs["icon"].color = GOLD_COLOR if is_active else TEXT_SECONDARY
            refs["text"].weight = ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL
            refs["text"].color = TEXT_PRIMARY if is_active else TEXT_SECONDARY
            refs["container"].border = (
                ft.Border.only(bottom=ft.BorderSide(2, GOLD_COLOR)) if is_active else None
            )

        # Swap content (AnimatedSwitcher animates between old and new)
        shell["content_area"].content = _wrap_content(content_control, page.route)

        try:
            shell["navbar"].update()
        except Exception:
            pass
        try:
            shell["content_area"].update()
        except Exception:
            pass

        return shell["view"]

    # ── Build shell for the first time ──────────────────────
    nav_refs = {}

    def make_nav(text, route, icon_name):
        is_active = (route == page.route)
        icon = ft.Icon(icon_name, size=16,
                       color=GOLD_COLOR if is_active else TEXT_SECONDARY)
        txt = ft.Text(
            text, size=13,
            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
            color=TEXT_PRIMARY if is_active else TEXT_SECONDARY,
        )
        cont = ft.Container(
            content=ft.Row([icon, txt], spacing=6),
            padding=ft.Padding.only(bottom=4),
            border=ft.Border.only(bottom=ft.BorderSide(2, GOLD_COLOR)) if is_active else None,
            on_click=lambda _, r=route: page.go(r),
        )
        nav_refs[route] = {"icon": icon, "text": txt, "container": cont}
        return cont

    logo_btn = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.HUB_ROUNDED, color=GOLD_COLOR, size=24),
            ft.Text("Nexus AI", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=lambda _: page.go("/dashboard"),
    )

    # files_menu removed

    def make_lang_badge(lang_code, label):
        is_active = (lang == lang_code)
        return ft.Container(
            content=ft.Text(label, size=10, weight=ft.FontWeight.BOLD,
                            color="#030407" if is_active else TEXT_SECONDARY),
            padding=ft.Padding.symmetric(vertical=4, horizontal=8),
            border_radius=4,
            bgcolor=GOLD_COLOR if is_active else ft.Colors.TRANSPARENT,
            on_click=lambda _: change_language(page, lang_code),
        )

    lang_row = ft.Row([
        make_lang_badge("en", "EN"),
        make_lang_badge("ru", "RU"),
        make_lang_badge("uk", "UA"),
    ], spacing=4)

    # Dynamic clock displaying the host device's local time
    clock_text = ft.Text("", size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500)
    clock_container = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=13, color=GOLD_COLOR),
            clock_text
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(vertical=4, horizontal=8),
        border_radius=6,
        bgcolor=ft.Colors.with_opacity(0.06, "#ffffff"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.08, "#ffffff"))
    )

    async def update_header_clock():
        import asyncio, datetime
        while True:
            try:
                now = datetime.datetime.now()
                offset_sec = now.astimezone().utcoffset().total_seconds()
                offset_h = int(offset_sec / 3600)
                tz_str = f"UTC{offset_h:+d}"
                clock_text.value = f"{now.strftime('%H:%M:%S')} ({tz_str})"
                clock_container.update()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["session closed", "destroyed session", "has been closed", "connection closed", "websocket"]):
                    break
            await asyncio.sleep(1.0)

    page.run_task(update_header_clock)

    t_nav_dash = {"en": "Trading Terminal", "ru": "Торговый терминал", "uk": "Торговий термінал"}.get(lang, "Trading Terminal")
    t_nav_hist = {"en": "Order History", "ru": "Все ордера", "uk": "Усі ордери"}.get(lang, "Order History")
    t_nav_dec = {"en": "AI Decisions", "ru": "AI Решения", "uk": "Рішення ШІ"}.get(lang, "AI Decisions")
    t_nav_set = {"en": "Settings", "ru": "Настройки", "uk": "Налаштування"}.get(lang, "Settings")

    nav_dash = make_nav(t_nav_dash, "/dashboard", ft.Icons.SHOW_CHART_ROUNDED)
    nav_hist = make_nav(t_nav_hist, "/history", ft.Icons.LIST_ALT_ROUNDED)
    nav_dec  = make_nav(t_nav_dec, "/decisions", ft.Icons.PSYCHOLOGY_ROUNDED)
    nav_set  = make_nav(t_nav_set, "/settings", ft.Icons.SETTINGS_ROUNDED)

    navbar = ft.Container(
        content=ft.Row([
            logo_btn,
            ft.Row([nav_dash, nav_hist, nav_dec, nav_set, clock_container, lang_row],
                   spacing=16,
                   alignment=ft.MainAxisAlignment.END,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
           vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=COLOR_GLASS_BG,
        blur=DEFAULT_BLUR,
        padding=ft.Padding.symmetric(vertical=12, horizontal=30),
        border=ft.Border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
    )

    # Plain container for content (no animation)
    content_area = ft.Container(
        content=_wrap_content(content_control, page.route),
        expand=True,
    )

    shell_view = ft.View(
        route="/shell",
        controls=[
            ft.Container(
                image=ft.DecorationImage(src="/background.jpg", fit=ft.BoxFit.COVER),
                expand=True,
                content=ft.Column([navbar, content_area]),
            )
        ],
        padding=0,
    )

    page._persistent_shell = {
        "view":         shell_view,
        "navbar":       navbar,
        "content_area": content_area,
        "nav_refs":     nav_refs,
    }

    return shell_view
