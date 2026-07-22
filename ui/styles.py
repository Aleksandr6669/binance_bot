import flet as ft

# Colors
COLOR_BG_DARK = "#0b0c10"
COLOR_PRIMARY = "#4f46e5"
COLOR_SECONDARY = "#9333ea"
COLOR_GLASS_BG = "#660b0c10"
COLOR_TEXT_PRIMARY = ft.Colors.WHITE
COLOR_TEXT_SECONDARY = ft.Colors.BLUE_GREY_300

# Constants
DEFAULT_BLUR = ft.Blur(40, 40, ft.BlurTileMode.MIRROR)
ANIMATION_DURATION = 150

# Gradients
PRIMARY_GRADIENT = ft.LinearGradient(
    begin=ft.Alignment(-1, -1),
    end=ft.Alignment(1, 1),
    colors=[
        "#804f46e5",
        "#809333ea",
        "#800f172a"
    ],
    stops=[0.0, 0.5, 1.0],
)

def create_glass_card(content, padding=40, width=None, animate_size=None):
    """
    Creates a glassmorphism card matching the dashboard style.
    """
    return ft.Container(
        content=content,
        bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
        blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
        padding=padding,
        width=width,
        animate_size=animate_size
    )

def apply_global_styles(page: ft.Page):
    """
    Sets the global page styles.
    """
    page.bgcolor = COLOR_BG_DARK
