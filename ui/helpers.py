import flet as ft
from ui.theme import *

def make_textfield(label=None, value="", password=False, can_reveal_password=False, width=None, hint_text=None, on_change=None, on_blur=None):
    return ft.TextField(
        label=label,
        value=value,
        hint_text=hint_text,
        password=password,
        can_reveal_password=can_reveal_password,
        width=width,
        expand=True if width is None else None,
        color="#f8fafc",
        border=ft.InputBorder.OUTLINE,
        border_color=ft.Colors.with_opacity(0.3, "#ffffff"),
        bgcolor=ft.Colors.TRANSPARENT,
        filled=False,
        focused_border_color="#0284c7",
        label_style=ft.TextStyle(color="#94a3b8", size=12, weight=ft.FontWeight.BOLD),
        border_radius=8,
        content_padding=15,
        on_change=on_change,
        on_blur=on_blur
    )

def make_dropdown(label=None, options=None, value=None, width=None, on_change=None):
    return ft.Dropdown(
        label=label,
        options=options or [],
        value=value,
        width=width,
        expand=True if width is None else None,
        color="#f8fafc",
        border=ft.InputBorder.OUTLINE,
        border_color=ft.Colors.with_opacity(0.3, "#ffffff"),
        bgcolor="#050505",
        filled=False,
        focused_border_color="#0284c7",
        label_style=ft.TextStyle(color="#94a3b8", size=12, weight=ft.FontWeight.BOLD),
        border_radius=8,
        content_padding=15,
        on_select=on_change
    )
