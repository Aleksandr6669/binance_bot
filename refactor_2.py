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

def indent_lines(text, spaces=4):
    prefix = ' ' * spaces
    return "\n".join([(prefix + line if line.strip() else line) for line in text.split('\n')])

bak = "flet_app.py.bak"

# 4. pages/history.py
history_code = """import flet as ft
import db
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

""" + extract_lines(bak, 766, 854, 4)
history_code = history_code.replace("def build_history_view(lang):", "def build_history_view(page: ft.Page, lang: str):")
with open("ui/pages/history.py", "w", encoding="utf-8") as f:
    f.write(history_code)

# 5. pages/decisions.py
decisions_code = """import flet as ft
import db
import json
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

""" + extract_lines(bak, 856, 936, 4)
decisions_code = decisions_code.replace("def build_decisions_view(lang):", "def build_decisions_view(page: ft.Page, lang: str):")
with open("ui/pages/decisions.py", "w", encoding="utf-8") as f:
    f.write(decisions_code)

# 6. pages/settings.py
settings_code = """import flet as ft
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

""" + extract_lines(bak, 938, 1383, 4)
settings_code = settings_code.replace("def build_settings_view(lang):", "def build_settings_view(page: ft.Page, lang: str):")
# settings uses change_language inside: it needs to call ui.layout.change_language
settings_code = settings_code.replace("change_language(lang_dd.value)", "import ui.layout; ui.layout.change_language(page, lang_dd.value)")
with open("ui/pages/settings.py", "w", encoding="utf-8") as f:
    f.write(settings_code)

# 7. pages/dashboard.py
# This is the tricky one.
dashboard_controls = extract_lines(bak, 84, 133, 4)
fetch_dashboard_data = extract_lines(bak, 1391, 1600, 4)
dashboard_refresher = """
    async def dashboard_refresher():
        import asyncio
        while True:
            await asyncio.sleep(2)
            if not balance_text.page: # view was destroyed
                break
            if page.route == "/dashboard" and page.session.store.get("user_id"):
                try:
                    await fetch_dashboard_data()
                except Exception as e:
                    print(f"Error in dashboard refresher: {e}")
                    
    page.run_task(dashboard_refresher)
"""
dashboard_build_content = extract_lines(bak, 587, 764, 4) # Skip def build_dashboard_view(lang):

dashboard_full = """import flet as ft
import flet_charts as ftc
import db
import json
import asyncio
from datetime import datetime
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

def build_dashboard_view(page: ft.Page, lang: str):
""" + indent_lines(dashboard_controls, 4) + "\n\n" + indent_lines(fetch_dashboard_data, 4) + "\n\n" + dashboard_refresher + "\n\n" + indent_lines(dashboard_build_content, 4)

with open("ui/pages/dashboard.py", "w", encoding="utf-8") as f:
    f.write(dashboard_full)

print("Refactor 2 done.")
