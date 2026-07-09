import ui.layout
import flet as ft
import db
from werkzeug.security import check_password_hash, generate_password_hash

def build_login_view(page: ft.Page, lang: str):
    is_login = True

    def create_textfield(hint, icon, is_password=False):
        return ft.TextField(
            hint_text=hint,
            password=is_password,
            can_reveal_password=is_password,
            prefix_icon=icon,
            filled=True,
            bgcolor="#1e293b",
            border_color="#334155",
            focused_border_color=ft.Colors.PURPLE_400,
            border_radius=12,
            height=55,
            color=ft.Colors.WHITE,
            cursor_color=ft.Colors.PURPLE_400,
            content_padding=15,
            text_style=ft.TextStyle(size=15),
            hint_style=ft.TextStyle(color=ft.Colors.BLUE_GREY_400, size=15)
        )

    username_field = create_textfield("Enter username", ft.Icons.PERSON)
    password_field = create_textfield("Enter password", ft.Icons.LOCK, is_password=True)
    confirm_field = create_textfield("Confirm password", ft.Icons.LOCK, is_password=True)
    
    def make_field(label_text, tf_control):
        return ft.Column([
            ft.Text(label_text.upper(), size=12, weight=ft.FontWeight.W_600, color=ft.Colors.BLUE_GREY_400),
            tf_control
        ], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # Animated container for confirm field to slide in and out smoothly
    confirm_container = ft.AnimatedSwitcher(
        content=ft.Container(height=0, width=0, key="hidden"),
        transition=ft.AnimatedSwitcherTransition.SCALE,
        duration=300
    )

    error_text = ft.Text("", color=ft.Colors.RED_500, size=14, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER)

    header = ft.AnimatedSwitcher(
        content=ft.Container(
            content=ft.Column([
                ft.Text("Welcome Back", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text("Access your automated AI trading dashboard", size=14, color=ft.Colors.BLUE_GREY_300)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            key="login_head"
        ),
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=200,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_OUT
    )

    submit_btn_content = ft.AnimatedSwitcher(
        content=ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.LOGIN, size=20, color=ft.Colors.WHITE),
                ft.Text("Sign In", size=16, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE)
            ], alignment=ft.MainAxisAlignment.CENTER),
            key="login_btn"
        ),
        transition=ft.AnimatedSwitcherTransition.SCALE,
        duration=200,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_OUT
    )

    def do_action(e):
        nonlocal is_login
        username = username_field.value.strip() if username_field.value else ""
        password = password_field.value if password_field.value else ""
        
        if not username or not password:
            error_text.value = "Заполните все поля!"
            page.update()
            return
            
        if is_login:
            user = db.get_user_by_username(username)
            if not user or not check_password_hash(user["password_hash"], password):
                error_text.value = "Неверное имя пользователя или пароль!"
                page.update()
                return
            page.session.store.set("user_id", user["id"])
            page.go("/dashboard")
        else:
            confirm = confirm_field.value if confirm_field.value else ""
            if password != confirm:
                error_text.value = "Пароли не совпадают!"
                page.update()
                return
            if db.get_user_by_username(username):
                error_text.value = "Пользователь уже существует!"
                page.update()
                return
                
            pwd_hash = generate_password_hash(password)
            user_id = db.create_user(username, pwd_hash, "user")
            page.session.store.set("user_id", user_id)
            page.go("/dashboard")

    submit_btn = ft.Container(
        content=submit_btn_content,
        bgcolor=ft.Colors.INDIGO_500,
        height=55,
        border_radius=12,
        alignment=ft.Alignment.CENTER,
        ink=True,
        on_click=do_action
    )
    
    footer_text = ft.Text("Don't have an account?", color=ft.Colors.BLUE_GREY_400, size=14)
    footer_action_text = ft.Text("Register here", color=ft.Colors.PURPLE_400, size=14, weight=ft.FontWeight.W_600)
    
    def toggle_mode(e):
        nonlocal is_login
        is_login = not is_login
        error_text.value = ""
        username_field.value = ""
        password_field.value = ""
        confirm_field.value = ""
        
        if is_login:
            header_title.value = "Welcome Back"
            header_subtitle.value = "Access your automated AI trading dashboard"
            header.controls[0].content = ft.Container(content=header_title, key="login_title")
            header.controls[1].content = ft.Container(content=header_subtitle, key="login_sub")
            
            submit_btn_content.content = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.LOGIN, size=20, color=ft.Colors.WHITE),
                    ft.Text("Sign In", size=16, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER),
                key="login_btn"
            )
            
            confirm_container.content = ft.Container(height=0, width=0, key="hidden")
            
            footer_text.value = "Don't have an account?"
            footer_action_text.value = "Register here"
        else:
            header_title.value = "Create Account"
            header_subtitle.value = "Join Nexus AI for automated trading"
            header.controls[0].content = ft.Container(content=header_title, key="reg_title")
            header.controls[1].content = ft.Container(content=header_subtitle, key="reg_sub")
            
            submit_btn_content.content = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PERSON_ADD, size=20, color=ft.Colors.WHITE),
                    ft.Text("Register", size=16, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER),
                key="reg_btn"
            )
            
            confirm_container.content = ft.Container(
                content=make_field("Confirm Password", confirm_field),
                key="visible"
            )
            
            footer_text.value = "Already have an account?"
            footer_action_text.value = "Sign In here"
            
        page.update()

    footer_action = ft.Container(
        content=footer_action_text,
        on_click=toggle_mode,
        ink=True,
        padding=5
    )
    
    footer = ft.Row([
        footer_text,
        footer_action
    ], alignment=ft.MainAxisAlignment.CENTER, spacing=5)

    def set_login_language(lang_code):
        page.client_storage.set("lang", lang_code)
        page.session.store.set("lang", lang_code)
        page.go("/loading")
        page.go("/login")

    def make_lang_btn(lang_code, label):
        is_active = (lang == lang_code)
        return ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE if is_active else ft.Colors.BLUE_GREY_400),
            padding=8,
            border_radius=8,
            bgcolor="#40ffffff" if is_active else ft.Colors.TRANSPARENT,
            ink=True,
            on_click=lambda e: set_login_language(lang_code)
        )

    lang_selector = ft.Row([
        make_lang_btn("en", "EN"),
        make_lang_btn("ru", "RU"),
        make_lang_btn("uk", "UK")
    ], alignment=ft.MainAxisAlignment.CENTER, spacing=5)

    fields_col = ft.Column([
        header,
        ft.Container(height=10),
        make_field("Username", username_field),
        make_field("Password", password_field),
        confirm_container,
        ft.Container(content=error_text, alignment=ft.Alignment.CENTER),
        ft.Container(height=5),
        submit_btn,
        footer,
        ft.Container(height=5),
        lang_selector
    ], spacing=15, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # Use more transparent background to maximize glassmorphism
    inner_card = ft.Container(
        content=fields_col,
        bgcolor="#660b0c10",
        padding=40,
        border_radius=20,
    )

    login_card = ft.Container(
        content=inner_card,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            # Use alpha channel (30% opacity) for gradient to not block the background blur
            colors=["#4d4f46e5", "#4d7e22ce"]
        ),
        padding=1,
        border_radius=22,
        width=400,
        blur=ft.Blur(40, 40, ft.BlurTileMode.MIRROR)
    )
    
    return ft.View(
        route="/login",
        controls=[
            ft.Container(
                image=ft.DecorationImage(src="/background.avif", fit=ft.BoxFit.COVER),
                expand=True,
                content=ft.Stack(
                    [
                        ft.Container(
                            content=ft.Column([
                                ft.Row([login_card], alignment=ft.MainAxisAlignment.CENTER)
                            ], alignment=ft.MainAxisAlignment.CENTER, expand=True),
                            expand=True
                        )
                    ],
                    expand=True
                )
            )
        ],
        padding=0
    )
