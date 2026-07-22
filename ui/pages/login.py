import flet as ft
from ui.theme import *
import os

def build_login_view(page: ft.Page, lang: dict):
    password_input = ft.TextField(
        label="Password",
        password=True,
        can_reveal_password=True,
        bgcolor=CARD_COLOR,
        border_color=BORDER_COLOR,
        color=TEXT_PRIMARY,
        width=300,
        text_align=ft.TextAlign.CENTER
    )
    
    error_text = ft.Text("", color=RED_COLOR, size=12)

    def login_click(e):
        target_password = os.environ.get("APP_PASSWORD")
        if target_password and password_input.value == target_password:
            setattr(page, "authenticated", True)
            page.go("/dashboard")
        else:
            error_text.value = "Invalid password"
            page.update()

    login_btn = ft.ElevatedButton(
        "Login",
        bgcolor=CYAN_COLOR,
        color=TEXT_PRIMARY,
        on_click=login_click,
        width=300,
        height=45
    )

    content = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.LOCK, size=64, color=CYAN_COLOR),
                ft.Text("Nexus AI Terminal", size=24, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                ft.Text("Authentication Required", size=14, color=TEXT_SECONDARY),
                ft.Container(height=20),
                password_input,
                error_text,
                ft.Container(height=10),
                login_btn
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        alignment=ft.alignment.Alignment(0.0, 0.0),
        expand=True,
        bgcolor=BG_COLOR
    )

    return ft.View(
        "/login",
        [content],
        bgcolor=BG_COLOR,
        padding=0
    )
