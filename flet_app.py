import flet as ft
import db
import os
from ui.theme import *
from ui.i18n import get_lang
from ui.layout import build_layout, ROUTE_INDEX

from ui.pages.login import build_login_view
from ui.pages.dashboard import build_dashboard_view
from ui.pages.history import build_history_view
from ui.pages.decisions import build_decisions_view
from ui.pages.settings import build_settings_view

def main(page: ft.Page):
    page.title = "Nexus AI - Trading Terminal"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_COLOR
    try:
        import time
        system_offset = int(-time.timezone / 60) if hasattr(time, "timezone") and time.timezone != 0 else 180
        page.tz_offset = system_offset
    except Exception:
        page.tz_offset = 180

    try:
        if hasattr(page, "window"):
            page.window.width = 1200
            page.window.height = 850
            page.window.min_width = 1100
            page.window.min_height = 800
        else:
            page.window_width = 1200
            page.window_height = 850
            page.window_min_width = 1100
            page.window_min_height = 800
        page.update()
    except Exception:
        pass

    page.fonts = {
        "Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
    }
    page.theme = ft.Theme(font_family="Inter")

    def safe_go(route):
        try:
            print(f"[DEBUG] safe_go calling page.go({route})")
            page.go(route)
        except Exception as ex:
            import traceback
            print(f"[ERROR] safe_go failed to go to {route}: {ex}")
            traceback.print_exc()

    def handle_route_change(e):
        print(f"[DEBUG] handle_route_change start. page.route = {page.route}")
        if page.route == "/" or page.route == "":
            safe_go("/dashboard")
            return

        target_password = os.environ.get("APP_PASSWORD")
        if target_password and not getattr(page, "authenticated", False) and page.route != "/login":
            safe_go("/login")
            return

        lang = get_lang(page)
        print(f"[DEBUG] handle_route_change lang = {lang}, route = {page.route}")

        # Login page bypasses the shell
        if page.route == "/login":
            new_view = build_login_view(page, lang)
            page.views.clear()
            page.views.append(new_view)
            page.update()
            print("[DEBUG] handle_route_change: login view updated successfully")
            return

        # Content cache (stores page content controls, not full views)
        if not hasattr(page, "_content_cache"):
            page._content_cache = {}

        cache_key = (page.route, lang)
        # history, decisions and settings always rebuild to show fresh data
        NO_CACHE_ROUTES = {"/history", "/decisions", "/settings"}

        if cache_key in page._content_cache:
            content = page._content_cache[cache_key]
        else:
            content = None
            if page.route == "/login":
                pass  # handled above
            elif page.route == "/dashboard":
                content = build_dashboard_view(page, lang)
            elif page.route == "/history":
                content = build_history_view(page, lang)
            elif page.route == "/decisions":
                content = build_decisions_view(page, lang)
            elif page.route == "/settings":
                content = build_settings_view(page, lang)

            if content is not None and page.route not in NO_CACHE_ROUTES:
                page._content_cache[cache_key] = content

        if content is not None:
            active_index = ROUTE_INDEX.get(page.route, 0)
            shell_view = build_layout(page, content, active_index, lang)

            # Only append to views if not already there (avoids full re-render)
            if not page.views or page.views[-1] is not shell_view:
                page.views.clear()
                page.views.append(shell_view)

        print("DEBUG route_change:", page.route, "views:", len(page.views))
        page.update()

        # Trigger lazy load tasks after transition has rendered
        if page.route == "/decisions" and hasattr(page, "load_decisions_data"):
            page.run_task(page.load_decisions_data)
        elif page.route == "/history" and hasattr(page, "load_history_data"):
            page.run_task(page.load_history_data, None)

    def handle_resize(e):
        is_web = getattr(page, "web", False)
        if not is_web:
            return
        current_width = page.width
        if current_width:
            is_invalid_width = current_width < 1100 and is_web
            last_invalid = getattr(page, "_is_invalid_width", None)
            if last_invalid is None or last_invalid != is_invalid_width:
                setattr(page, "_is_invalid_width", is_invalid_width)
                handle_route_change(None)
        try:
            page.update()
        except Exception:
            pass

    def handle_lang_changed(topic, new_lang):
        # Clear both caches and rebuild shell on language change
        if hasattr(page, "_content_cache"):
            page._content_cache.clear()
        if hasattr(page, "_persistent_shell"):
            del page._persistent_shell
        handle_route_change(None)

    page.on_route_change = handle_route_change
    page.on_resize = handle_resize
    page.pubsub.subscribe_topic("lang_changed", handle_lang_changed)

    target_password = os.environ.get("APP_PASSWORD")
    if target_password and not getattr(page, "authenticated", False):
        page.route = "/login"
    else:
        page.route = "/dashboard"

    handle_route_change(None)

    
