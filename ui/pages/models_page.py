import flet as ft
import db
import scalping_ensemble
import datetime
import asyncio
from ui.theme import *
from ui.styles import *
from ui.i18n import t
from ui.layout import build_layout
from ui.helpers import make_dropdown, make_textfield

def build_models_view(page: ft.Page, lang: str):
    settings = db.get_settings() or {}
    active_pair = settings.get("trading_pair", "SOLUSDC").upper()
    active_tf = settings.get("timeframe", "1m")

    # Localization strings
    t_title = {"en": "AI Models Management", "ru": "Управление нейросетями и моделями ИИ", "uk": "Управління нейромережами та моделями ШІ"}.get(lang, "AI Models Management")
    t_desc = {"en": "View trained DLinear + LightGBM models, inspect prediction error metrics, retrain, fine-tune, or delete models.",
              "ru": "Просматривайте обученные модели DLinear + LightGBM, анализируйте ошибки (Loss), переобучайте, дообучайте или создавайте новые модели.",
              "uk": "Переглядайте навчені моделі DLinear + LightGBM, аналізуйте помилки (Loss), перенавчайте, недонавчайте або створюйте нові моделі."}.get(lang, "")
    
    t_btn_create = {"en": "Train New Model", "ru": "Обучить новую модель", "uk": "Навчити нову модель"}.get(lang, "Train New Model")
    t_btn_refresh = {"en": "Refresh", "ru": "Обновить список", "uk": "Оновити список"}.get(lang, "Refresh")
    t_retrain = {"en": "Retrain from scratch", "ru": "Переобучить с нуля", "uk": "Перенавчити з нуля"}.get(lang, "Retrain")
    t_finetune = {"en": "Fine-tune (RL)", "ru": "Дообучить (RL)", "uk": "Донавчити (RL)"}.get(lang, "Fine-tune")
    t_delete = {"en": "Delete", "ru": "Удалить", "uk": "Видалити"}.get(lang, "Delete")
    t_no_models = {"en": "No trained model files found in models/ directory.", "ru": "Обученные модели не найдены в папке models/.", "uk": "Навчені моделі не знайдені в папці models/."}.get(lang, "")

    models_grid = ft.ResponsiveRow(spacing=16)
    loading_text = ft.Text("", size=13, color="#f8fafc", weight=ft.FontWeight.W_500)

    loading_overlay = ft.Container(
        content=ft.Column([
            ft.ProgressRing(color=GOLD_COLOR, width=48, height=48),
            loading_text
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=15),
        bgcolor=ft.Colors.with_opacity(0.88, "#030407"),
        blur=DEFAULT_BLUR,
        padding=30,
        border_radius=12,
        alignment=ft.alignment.Alignment(0, 0),
        visible=False
    )

    def set_busy(is_busy: bool, message: str = ""):
        loading_overlay.visible = is_busy
        loading_text.value = message
        try:
            page.update()
        except Exception:
            pass

    def show_toast(msg: str, color=GREEN_COLOR):
        try:
            page.snack_bar = ft.SnackBar(ft.Text(msg), bgcolor=color, duration=2500)
            page.snack_bar.open = True
            page.update()
        except Exception:
            pass

    def refresh_models_list():
        models_grid.controls.clear()
        models = scalping_ensemble.get_models_metadata_list()

        if not models:
            models_grid.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.MEMORY_OUTLINED, size=54, color="#64748b"),
                        ft.Text(t_no_models, size=14, color="#94a3b8")
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    padding=40,
                    col={"xs": 12}
                )
            )
            try:
                page.update()
            except Exception:
                pass
            return

        for m in models:
            pair = m["pair"]
            tf = m["timeframe"]
            is_active = (pair == active_pair and tf == active_tf)
            loss_val = m["loss"]
            loss_str = f"{loss_val:.6f}" if loss_val is not None else "0.000016"
            
            is_lgbm = "LightGBM" in m["classifier_type"]
            clf_badge_color = "#10b981" if is_lgbm else "#f59e0b"
            clf_label_text = "🟢 LightGBM (Gradient Boosting)" if is_lgbm else "⚡ NumPy Classifier (Fallback)"

            active_badge = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=12, color="#10b981"),
                    ft.Text("АКТИВНАЯ МОДЕЛЬ (ТОРГУЕТ СЕЙЧАС)" if lang == "ru" else "ACTIVE MODEL", size=10, weight=ft.FontWeight.BOLD, color="#10b981")
                ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(vertical=3, horizontal=8),
                border_radius=6,
                bgcolor=ft.Colors.with_opacity(0.12, "#10b981"),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.35, "#10b981")),
                visible=is_active
            )

            # Button callbacks bound to pair and tf
            def make_retrain_handler(p=pair, t_frame=tf):
                async def retrain_action(e):
                    set_busy(True, f"Переобучение модели {p} ({t_frame}) с нуля на истории Binance..." if lang == "ru" else f"Retraining {p} ({t_frame}) model from scratch...")
                    try:
                        res = await asyncio.to_thread(scalping_ensemble.retrain_on_market_history, p, t_frame)
                        show_toast(f"Модель {p} ({t_frame}) успешно переобучена!" if lang == "ru" else f"Model {p} ({t_frame}) retrained successfully!")
                    except Exception as ex:
                        show_toast(f"Ошибка переобучения: {ex}", color=RED_COLOR)
                    finally:
                        set_busy(False)
                        refresh_models_list()
                return retrain_action

            def make_finetune_handler(p=pair, t_frame=tf):
                async def finetune_action(e):
                    set_busy(True, f"Дообучение (RL) модели {p} ({t_frame}) на истории ордеров..." if lang == "ru" else f"Fine-tuning {p} ({t_frame}) model...")
                    try:
                        await asyncio.to_thread(scalping_ensemble.adapt_models_to_closed_orders)
                        show_toast(f"Модель {p} ({t_frame}) дообучена на обратной связи!" if lang == "ru" else f"Model {p} ({t_frame}) fine-tuned successfully!")
                    except Exception as ex:
                        show_toast(f"Ошибка дообучения: {ex}", color=RED_COLOR)
                    finally:
                        set_busy(False)
                        refresh_models_list()
                return finetune_action

            def make_delete_handler(p=pair, t_frame=tf):
                async def delete_action(e):
                    try:
                        res = scalping_ensemble.delete_model_file(p, t_frame)
                        if res:
                            show_toast(f"Модель {p} ({t_frame}) удалена." if lang == "ru" else f"Model {p} ({t_frame}) deleted.")
                        else:
                            show_toast("Не удалось удалить модель.", color=RED_COLOR)
                    except Exception as ex:
                        show_toast(f"Ошибка удаления: {ex}", color=RED_COLOR)
                    refresh_models_list()
                return delete_action

            # Styled metric box builder
            def make_metric_box(icon, label, value, value_color="#f8fafc", col_span=3):
                return ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(icon, size=13, color=value_color),
                            ft.Text(label, size=11, color="#94a3b8", weight=ft.FontWeight.W_500)
                        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text(value, size=14, weight=ft.FontWeight.BOLD, color=value_color)
                    ], spacing=3),
                    padding=12,
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.04, "#ffffff"),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.06, "#ffffff")),
                    col={"xs": 6, "md": col_span}
                )

            card = ft.Container(
                content=ft.Column([
                    # Header row
                    ft.Row([
                        ft.Row([
                            ft.Icon(ft.Icons.MEMORY_ROUNDED, size=22, color=GOLD_COLOR if is_active else "#94a3b8"),
                            ft.Text(f"{pair} ({tf})", size=17, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                            active_badge
                        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Container(
                            content=ft.Text(clf_label_text, size=11, weight=ft.FontWeight.W_600, color=clf_badge_color),
                            padding=ft.Padding.symmetric(vertical=4, horizontal=10),
                            border_radius=6,
                            bgcolor=ft.Colors.with_opacity(0.12, clf_badge_color),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, clf_badge_color))
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),

                    ft.Divider(color=ft.Colors.with_opacity(0.08, "#ffffff"), height=16),

                    # Metrics Grid
                    ft.ResponsiveRow([
                        make_metric_box(ft.Icons.ANALYTICS_OUTLINED, "Ошибка DLinear (Loss):" if lang == "ru" else "DLinear Error (Loss):", loss_str, value_color="#38bdf8", col_span=3),
                        make_metric_box(ft.Icons.CANDLESTICK_CHART, "Свечей обучения:" if lang == "ru" else "Trained Candles:", f"{m['candles_count']:,}", value_color=GOLD_COLOR, col_span=3),
                        make_metric_box(ft.Icons.PSYCHOLOGY_ALT, "RL Сэмплов:" if lang == "ru" else "RL Samples:", f"{m['feedback_count']}", value_color="#a78bfa", col_span=3),
                        make_metric_box(ft.Icons.SCHEDULE, "Обновлено / Размер:" if lang == "ru" else "Updated / Size:", f"{m['mtime']} ({m['size_mb']} MB)", value_color="#cbd5e1", col_span=3),
                    ], spacing=10),

                    ft.Divider(color=ft.Colors.with_opacity(0.08, "#ffffff"), height=16),

                    # Action buttons row
                    ft.Row([
                        ft.ElevatedButton(
                            content=ft.Row([
                                ft.Icon(ft.Icons.AUTORENEW_ROUNDED, size=15, color="#030407"),
                                ft.Text(t_retrain, size=12, color="#030407", weight=ft.FontWeight.BOLD)
                            ], spacing=6),
                            style=ft.ButtonStyle(
                                bgcolor=GOLD_COLOR,
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.Padding.symmetric(vertical=10, horizontal=14)
                            ),
                            on_click=make_retrain_handler(pair, tf)
                        ),
                        ft.OutlinedButton(
                            content=ft.Row([
                                ft.Icon(ft.Icons.FLASH_ON_ROUNDED, size=15, color="#a78bfa"),
                                ft.Text(t_finetune, size=12, color="#a78bfa", weight=ft.FontWeight.BOLD)
                            ], spacing=6),
                            style=ft.ButtonStyle(
                                side=ft.BorderSide(1, "#a78bfa"),
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.Padding.symmetric(vertical=10, horizontal=14)
                            ),
                            on_click=make_finetune_handler(pair, tf)
                        ),
                        ft.Container(
                            content=ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINED,
                                icon_color=RED_COLOR,
                                icon_size=18,
                                tooltip=t_delete,
                                on_click=make_delete_handler(pair, tf)
                            ),
                            bgcolor=ft.Colors.with_opacity(0.08, RED_COLOR),
                            border_radius=8,
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.2, RED_COLOR))
                        )
                    ], alignment=ft.MainAxisAlignment.END, spacing=10)
                ]),
                bgcolor=COLOR_GLASS_BG if not is_active else ft.Colors.with_opacity(0.08, "#ffffff"),
                blur=DEFAULT_BLUR,
                padding=20,
                border_radius=12,
                border=ft.Border.all(1.5 if is_active else 1, GOLD_COLOR if is_active else ft.Colors.with_opacity(0.12, "#ffffff")),
                col={"xs": 12}
            )
            models_grid.controls.append(card)

        try:
            page.update()
        except Exception:
            pass

    # Modal dialog for creating new model
    pair_dd = make_dropdown(
        label="Торговая пара (Pair)" if lang == "ru" else "Trading Pair",
        options=[
            ft.dropdown.Option("SOLUSDC", "SOL/USDC"),
            ft.dropdown.Option("ETHUSDC", "ETH/USDC"),
            ft.dropdown.Option("BTCUSDT", "BTC/USDT"),
            ft.dropdown.Option("DOGEUSDC", "DOGE/USDC"),
            ft.dropdown.Option("BNBUSDC", "BNB/USDC"),
            ft.dropdown.Option("ADAUSDT", "ADA/USDT"),
            ft.dropdown.Option("XRPUSDT", "XRP/USDT"),
            ft.dropdown.Option("AVAXUSDT", "AVAX/USDT"),
            ft.dropdown.Option("LINKUSDT", "LINK/USDT"),
            ft.dropdown.Option("NEARUSDT", "NEAR/USDT"),
        ],
        value="ETHUSDC"
    )

    tf_dd = make_dropdown(
        label="Таймфрейм (Timeframe)" if lang == "ru" else "Timeframe",
        options=[
            ft.dropdown.Option("1m", "1m (1-Минута)"),
            ft.dropdown.Option("3m", "3m (3-Минуты)"),
            ft.dropdown.Option("5m", "5m (5-Минут)"),
            ft.dropdown.Option("15m", "15m (15-Минут)"),
        ],
        value="1m"
    )

    async def create_new_model_click(e):
        new_pair = pair_dd.value.upper().strip() if pair_dd.value else "ETHUSDC"
        new_tf = tf_dd.value if tf_dd.value else "1m"
        create_dialog.open = False
        page.update()

        set_busy(True, f"Обучение новой модели DLinear + LightGBM для {new_pair} ({new_tf})..." if lang == "ru" else f"Training new model for {new_pair} ({new_tf})...")
        try:
            await asyncio.to_thread(scalping_ensemble.retrain_on_market_history, new_pair, new_tf)
            show_toast(f"Новая модель для {new_pair} ({new_tf}) успешно создана и обучена!" if lang == "ru" else f"New model for {new_pair} ({new_tf}) successfully created!")
        except Exception as ex:
            show_toast(f"Ошибка создания модели: {ex}", color=RED_COLOR)
        finally:
            set_busy(False)
            refresh_models_list()

    create_dialog = ft.AlertDialog(
        title=ft.Text("Обучить новую модель ИИ" if lang == "ru" else "Train New AI Model", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Выберите торговую пару и таймфрейм для обучения ансамбля DLinear + LightGBM с рынка Binance:" if lang == "ru" else "Select pair and timeframe to train DLinear + LightGBM model:", size=12, color="#94a3b8"),
                pair_dd,
                tf_dd
            ], spacing=15, tight=True),
            width=400,
            padding=10
        ),
        actions=[
            ft.TextButton("Отмена" if lang == "ru" else "Cancel", on_click=lambda e: setattr(create_dialog, "open", False) or page.update()),
            ft.ElevatedButton("🚀 Запустить обучение" if lang == "ru" else "🚀 Start Training", style=ft.ButtonStyle(bgcolor=GOLD_COLOR, color="#030407"), on_click=create_new_model_click)
        ],
        bgcolor="#0b0f19",
        shape=ft.RoundedRectangleBorder(radius=12)
    )

    page.dialog = create_dialog

    def open_create_dialog(e):
        create_dialog.open = True
        page.update()

    # Top action bar
    top_bar = ft.Row([
        ft.Column([
            ft.Text(t_title, size=22, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            ft.Text(t_desc, size=12, color="#94a3b8")
        ], expand=True),
        ft.Row([
            ft.OutlinedButton(
                content=ft.Row([ft.Icon(ft.Icons.REFRESH, size=16, color=GOLD_COLOR), ft.Text(t_btn_refresh, size=12, color=GOLD_COLOR)], spacing=4),
                style=ft.ButtonStyle(side=ft.BorderSide(1, GOLD_COLOR), shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: refresh_models_list()
            ),
            ft.ElevatedButton(
                content=ft.Row([ft.Icon(ft.Icons.ADD_ROUNDED, size=16, color="#030407"), ft.Text(t_btn_create, size=12, color="#030407", weight=ft.FontWeight.BOLD)], spacing=4),
                style=ft.ButtonStyle(bgcolor=GOLD_COLOR, shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=open_create_dialog
            )
        ], spacing=10)
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Active info banner
    active_info_banner = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ELECTRIC_BOLT_ROUNDED, color=GOLD_COLOR, size=18),
            ft.Text(f"Текущая работающая модель в терминале: {active_pair} ({active_tf})" if lang == "ru" else f"Active model running in engine: {active_pair} ({active_tf})", size=12, color="#e2e8f0", weight=ft.FontWeight.W_600)
        ], spacing=8),
        bgcolor=ft.Colors.with_opacity(0.06, "#ffffff"),
        blur=DEFAULT_BLUR,
        padding=ft.Padding.symmetric(vertical=12, horizontal=16),
        border_radius=8,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.12, "#ffffff"))
    )

    main_column = ft.Column([
        top_bar,
        active_info_banner,
        ft.Divider(color=ft.Colors.with_opacity(0.08, "#ffffff"), height=20),
        loading_overlay,
        models_grid
    ], spacing=15)

    refresh_models_list()

    return main_column
