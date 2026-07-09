import os

def extract_lines(filepath, start_line, end_line, unindent=4):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()[start_line-1:end_line]
    
    result = []
    for line in lines:
        if line.startswith(' ' * unindent):
            result.append(line[unindent:])
        elif line.strip() == '':
            result.append(line)
        else:
            result.append(line)
    return "".join(result)

bak = "flet_app.py.bak"

# 1. layout.py
layout_code = """import flet as ft
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

""" + extract_lines(bak, 166, 444, 4)

# Fix lambda closures in layout.py
layout_code = layout_code.replace("logout()", "logout(page)")
layout_code = layout_code.replace("handle_nav_change(e.control.selected_index)", "handle_nav_change(page, e.control.selected_index)")
layout_code = layout_code.replace("check_auth()", "check_auth(page)")
layout_code = layout_code.replace("change_language(lang_code)", "change_language(page, lang_code)")
layout_code = layout_code.replace("def build_layout(content_control, active_index, lang):", "def build_layout(page: ft.Page, content_control, active_index, lang):")

with open("ui/layout.py", "w", encoding="utf-8") as f:
    f.write(layout_code)

# 2. pages/login.py
login_code = """import flet as ft
import db
from werkzeug.security import check_password_hash
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

""" + extract_lines(bak, 460, 525, 4)
login_code = login_code.replace("def build_login_view(lang):", "def build_login_view(page: ft.Page, lang: str):")
with open("ui/pages/login.py", "w", encoding="utf-8") as f:
    f.write(login_code)

# 3. pages/register.py
reg_code = """import flet as ft
import db
from werkzeug.security import generate_password_hash
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

""" + extract_lines(bak, 527, 584, 4)
reg_code = reg_code.replace("def build_register_view(lang):", "def build_register_view(page: ft.Page, lang: str):")
with open("ui/pages/register.py", "w", encoding="utf-8") as f:
    f.write(reg_code)

print("Extraction script done.")
