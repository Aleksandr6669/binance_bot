import flet as ft
from ui.theme import *

def make_textfield(label=None, value="", password=False, can_reveal_password=False, width=None, hint_text=None):
    return ft.TextField(
        label=label,
        value=value,
        hint_text=hint_text,
        password=password,
        can_reveal_password=can_reveal_password,
        width=width,
        color=TEXT_PRIMARY,
        border_color=BORDER_COLOR,
        bgcolor=CARD_COLOR,
        focused_border_color=CYAN_COLOR,
        label_style=ft.TextStyle(color=TEXT_SECONDARY),
        border_radius=8,
        content_padding=15
    )

def make_dropdown(label=None, options=None, value=None, width=None):
    return ft.Dropdown(
        label=label,
        options=options or [],
        value=value,
        width=width,
        color=TEXT_PRIMARY,
        border_color=BORDER_COLOR,
        bgcolor=CARD_COLOR,
        focused_border_color=CYAN_COLOR,
        label_style=ft.TextStyle(color=TEXT_SECONDARY),
        border_radius=8,
        content_padding=15
    )
