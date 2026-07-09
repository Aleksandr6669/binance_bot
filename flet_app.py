import flet as ft
import db
from ui.theme import *
from ui.i18n import get_lang
from ui.layout import check_auth

from ui.pages.login import build_login_view
from ui.pages.dashboard import build_dashboard_view
from ui.pages.history import build_history_view
from ui.pages.decisions import build_decisions_view
from ui.pages.settings import build_settings_view

def main(page: ft.Page):
    page.title = "Nexus AI - Trading Terminal"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_COLOR
    page.padding = 0
    page.fonts = {
        "Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
    }
    page.theme = ft.Theme(font_family="Inter")

    def handle_route_change(e):
        page.views.clear()
        
        # Handle root redirect
        if page.route == "/" or page.route == "":
            page.go("/dashboard" if check_auth(page) else "/login")
            return
            
        # Protect routes
        if not check_auth(page) and page.route not in ["/login"]:
            page.go("/login")
            return
            
        lang = get_lang(page)
        
        if page.route == "/login":
            page.views.append(build_login_view(page, lang))
        elif page.route == "/dashboard":
            page.views.append(build_dashboard_view(page, lang))
        elif page.route == "/history":
            page.views.append(build_history_view(page, lang))
        elif page.route == "/decisions":
            page.views.append(build_decisions_view(page, lang))
        elif page.route == "/settings":
            page.views.append(build_settings_view(page, lang))
            
        page.update()

    def handle_resize(e):
        handle_route_change(None)

    page.on_route_change = handle_route_change
    page.on_resize = handle_resize

    if check_auth(page):
        page.go("/dashboard")
    else:
        page.go("/login")

if __name__ == "__main__":
    ft.app(target=main, port=8000, view=ft.AppView.WEB_BROWSER)
