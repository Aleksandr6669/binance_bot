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
    t_desc = {"en": "View trained DLinear + LightGBM models, inspect Loss error metrics, retrain with TP/SL virtual bootstrapping, fine-tune or train new models.",
              "ru": "Просматривайте обученные модели DLinear + LightGBM, анализируйте ошибки (Loss). При обучении выполняется псевдоторговля, проверка исходов TP/SL, расчёт уровней лимитных ордеров и трейлинг-стопа.",
              "uk": "Переглядайте навчені моделі DLinear + LightGBM, аналізуйте помилки (Loss). При навчанні виконується псевдоторгівля, перевірка результатів TP/SL, розрахунок рівнів лімітних ордерів та трейлінг-стопу."}.get(lang, "")
    
    t_btn_create = {"en": "Train New Model", "ru": "Обучить новую модель", "uk": "Навчити нову модель"}.get(lang, "Train New Model")
    t_btn_refresh = {"en": "Refresh", "ru": "Обновить список", "uk": "Оновити список"}.get(lang, "Refresh")
    t_retrain = {"en": "Retrain from scratch", "ru": "Переобучить с нуля", "uk": "Перенавчити з нуля"}.get(lang, "Retrain")
    t_finetune = {"en": "Fine-tune (RL)", "ru": "Дообучить (RL)", "uk": "Донавчити (RL)"}.get(lang, "Fine-tune")
    t_delete = {"en": "Delete", "ru": "Удалить", "uk": "Видалити"}.get(lang, "Delete")
    t_no_models = {"en": "No trained model files found in models/ directory.", "ru": "Обученные модели не найдены в папке models/.", "uk": "Навчені моделі не знайдені в папці models/."}.get(lang, "")

    models_grid = ft.ResponsiveRow(spacing=16)
    active_tasks = {} # Dict tracking in-progress training per model: "PAIR_TF" -> status_msg

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

        # Sync active background training tasks from scalping_ensemble engine
        st = scalping_ensemble.get_training_status()
        if st and st.get("active"):
            st_key = f"{st['pair']}_{st['timeframe']}"
            active_tasks[st_key] = st.get("msg", f"Обучение нейросети {st['pair']} ({st['timeframe']})...")
        elif st and not st.get("active") and st.get("pair") and st.get("timeframe"):
            st_key = f"{st['pair']}_{st['timeframe']}"
            active_tasks.pop(st_key, None)

        # Inject placeholder entries for models currently training that are not on disk yet
        for task_key, task_msg in list(active_tasks.items()):
            if "_" in task_key:
                p, tf = task_key.split("_", 1)
                if not any(m["pair"] == p and m["timeframe"] == tf for m in models):
                    models.append({
                        "pair": p,
                        "timeframe": tf,
                        "loss": None,
                        "candles_count": 0,
                        "feedback_count": 0,
                        "size_mb": "0.0",
                        "mtime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "classifier_type": "LightGBM Classifier"
                    })

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
            task_key = f"{pair}_{tf}"
            is_training = task_key in active_tasks
            training_msg = active_tasks.get(task_key, "")

            is_active = (pair == active_pair and tf == active_tf)
            loss_val = m["loss"]
            loss_str = f"{loss_val:.6f}" if loss_val is not None else "0.000016"
            
            v_st = m.get("virtual_stats") or {}
            r_st = m.get("real_stats") or {}

            v_tot = v_st.get("total", 0)
            v_w = v_st.get("wins", 0)
            v_l = v_st.get("losses", 0)
            v_wr = v_st.get("winrate", 0.0)

            r_tot = r_st.get("total", 0)
            r_w = r_st.get("wins", 0)
            r_l = r_st.get("losses", 0)
            r_wr = r_st.get("winrate", 0.0)

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
                    t_key = f"{p}_{t_frame}"
                    active_tasks[t_key] = f"Обучение с нуля {p} ({t_frame}): псевдоторговля, проверка TP/SL, отступы лимиток и ИИ-трейлинг..." if lang == "ru" else f"Retraining {p} ({t_frame}) from scratch..."
                    refresh_models_list()
                    try:
                        res = await asyncio.to_thread(scalping_ensemble.bootstrap_virtual_training, p, t_frame)
                        show_toast(f"Модель {p} ({t_frame}) успешно переобучена с нуля!" if lang == "ru" else f"Model {p} ({t_frame}) retrained successfully!")
                    except Exception as ex:
                        show_toast(f"Ошибка переобучения: {ex}", color=RED_COLOR)
                    finally:
                        active_tasks.pop(t_key, None)
                        refresh_models_list()
                return retrain_action

            def make_finetune_handler(p=pair, t_frame=tf):
                async def finetune_action(e):
                    t_key = f"{p}_{t_frame}"
                    active_tasks[t_key] = f"Дообучение (RL) модели {p} ({t_frame}) на закрытых ордерах и логах..." if lang == "ru" else f"Fine-tuning {p} ({t_frame}) model..."
                    refresh_models_list()
                    try:
                        res = await asyncio.to_thread(scalping_ensemble.adapt_models_to_closed_orders, p, t_frame)
                        show_toast(f"Модель {p} ({t_frame}) дообучена на обратной связи!" if lang == "ru" else f"Model {p} ({t_frame}) fine-tuned successfully!")
                    except Exception as ex:
                        show_toast(f"Ошибка дообучения: {ex}", color=RED_COLOR)
                    finally:
                        active_tasks.pop(t_key, None)
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

            # Action area: Normal buttons OR inline progress bar for this specific card
            if is_training:
                action_area = ft.Container(
                    content=ft.Row([
                        ft.ProgressRing(color=GOLD_COLOR, width=15, height=15, stroke_width=2),
                        ft.Text(training_msg, size=11, color=GOLD_COLOR, weight=ft.FontWeight.W_500)
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=ft.Colors.with_opacity(0.08, GOLD_COLOR),
                    padding=ft.Padding.symmetric(vertical=6, horizontal=10),
                    border_radius=6,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.25, GOLD_COLOR))
                )
            else:
                action_area = ft.Row([
                    ft.ElevatedButton(
                        content=ft.Row([
                            ft.Icon(ft.Icons.AUTORENEW_ROUNDED, size=13, color="#030407"),
                            ft.Text(t_retrain, size=11, color="#030407", weight=ft.FontWeight.BOLD)
                        ], spacing=4),
                        style=ft.ButtonStyle(
                            bgcolor=GOLD_COLOR,
                            shape=ft.RoundedRectangleBorder(radius=6),
                            padding=ft.Padding.symmetric(vertical=6, horizontal=10)
                        ),
                        on_click=make_retrain_handler(pair, tf)
                    ),
                    ft.OutlinedButton(
                        content=ft.Row([
                            ft.Icon(ft.Icons.FLASH_ON_ROUNDED, size=13, color="#a78bfa"),
                            ft.Text(t_finetune, size=11, color="#a78bfa", weight=ft.FontWeight.BOLD)
                        ], spacing=4),
                        style=ft.ButtonStyle(
                            side=ft.BorderSide(1, "#a78bfa"),
                            shape=ft.RoundedRectangleBorder(radius=6),
                            padding=ft.Padding.symmetric(vertical=6, horizontal=10)
                        ),
                        on_click=make_finetune_handler(pair, tf)
                    ),
                    ft.Container(
                        content=ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINED,
                            icon_color=RED_COLOR,
                            icon_size=16,
                            tooltip=t_delete,
                            on_click=make_delete_handler(pair, tf)
                        ),
                        bgcolor=ft.Colors.with_opacity(0.08, RED_COLOR),
                        border_radius=6,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.2, RED_COLOR))
                    )
                ], alignment=ft.MainAxisAlignment.END, spacing=6)

            card = ft.Container(
                content=ft.Column([
                    # Header row: Pair info + Badges on left, Action buttons on right
                    ft.Row([
                        ft.Row([
                            ft.Icon(ft.Icons.MEMORY_ROUNDED, size=18, color=GOLD_COLOR if is_active else "#94a3b8"),
                            ft.Text(f"{pair} ({tf})", size=15, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                            active_badge,
                            ft.Container(
                                content=ft.Text(clf_label_text, size=9, weight=ft.FontWeight.BOLD, color=clf_badge_color),
                                padding=ft.Padding.symmetric(vertical=2, horizontal=7),
                                border_radius=6,
                                bgcolor=ft.Colors.with_opacity(0.12, clf_badge_color),
                                border=ft.Border.all(1, ft.Colors.with_opacity(0.25, clf_badge_color))
                            )
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),

                        action_area
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),

                    ft.Divider(color=ft.Colors.with_opacity(0.06, "#ffffff"), height=8),

                    # Metrics Columns matching history.py and decisions.py
                    ft.ResponsiveRow([
                        ft.Column([
                            ft.Text("DLINEAR LOSS", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                            ft.Text(loss_str, size=12, weight=ft.FontWeight.BOLD, color="#38bdf8")
                        ], spacing=1, col={"xs": 6, "md": 3}),
                        ft.Column([
                            ft.Text("CANDLES TRAINED", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                            ft.Text(f"{m['candles_count']:,}", size=12, weight=ft.FontWeight.BOLD, color="#f8fafc")
                        ], spacing=1, col={"xs": 6, "md": 3}),
                        ft.Column([
                            ft.Text("RL SAMPLES", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                            ft.Text(f"{m['feedback_count']}", size=12, weight=ft.FontWeight.BOLD, color="#a78bfa")
                        ], spacing=1, col={"xs": 6, "md": 3}),
                        ft.Column([
                            ft.Text("UPDATED / SIZE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                            ft.Row([
                                ft.Text(f"{m['mtime']}", size=11, color="#94a3b8"),
                                ft.Text(f"({m['size_mb']} MB)", size=11, color="#64748b")
                            ], spacing=3)
                        ], spacing=1, col={"xs": 6, "md": 3}),
                    ], spacing=6),

                    ft.Divider(color=ft.Colors.with_opacity(0.06, "#ffffff"), height=8),

                    # Trades Stats Row (Virtual vs Real/Demo)
                    ft.ResponsiveRow([
                        # Column 1: Virtual Trades (Bootstrap simulation)
                        ft.Column([
                            ft.Row([
                                ft.Icon(ft.Icons.AUTO_GRAPH_ROUNDED, size=11, color=GOLD_COLOR),
                                ft.Text("ВИРТУАЛЬНЫЕ СДЕЛКИ (BOOTSTRAP)", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD)
                            ], spacing=3),
                            ft.Row([
                                ft.Text(f"{v_tot} всего", size=11, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                                ft.Text(f"({v_w} 🟢 | {v_l} 🔴)", size=11, color="#cbd5e1"),
                                ft.Container(
                                    content=ft.Text(f"WR {v_wr:.1f}%", size=9, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
                                    padding=ft.Padding.symmetric(vertical=1, horizontal=4),
                                    border_radius=4,
                                    bgcolor=ft.Colors.with_opacity(0.12, GOLD_COLOR),
                                    border=ft.Border.all(1, ft.Colors.with_opacity(0.3, GOLD_COLOR))
                                )
                            ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                        ], spacing=1, col={"xs": 12, "md": 6}),

                        # Column 2: Real / Demo Trading Orders
                        ft.Column([
                            ft.Row([
                                ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, size=11, color="#38bdf8"),
                                ft.Text("РЕАЛЬНЫЕ / ДЕМО СДЕЛКИ", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD)
                            ], spacing=3),
                            ft.Row([
                                ft.Text(f"{r_tot} всего", size=11, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                                ft.Text(f"({r_w} 🟢 | {r_l} 🔴)", size=11, color="#cbd5e1"),
                                ft.Container(
                                    content=ft.Text(f"WR {r_wr:.1f}%", size=9, weight=ft.FontWeight.BOLD, color="#38bdf8"),
                                    padding=ft.Padding.symmetric(vertical=1, horizontal=4),
                                    border_radius=4,
                                    bgcolor=ft.Colors.with_opacity(0.12, "#38bdf8"),
                                    border=ft.Border.all(1, ft.Colors.with_opacity(0.3, "#38bdf8"))
                                )
                            ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                        ], spacing=1, col={"xs": 12, "md": 6})
                    ], spacing=6)
                ]),
                bgcolor=ft.Colors.with_opacity(0.05, "#ffffff") if not is_active else ft.Colors.with_opacity(0.1, "#ffffff"),
                blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
                padding=ft.Padding(18, 14, 18, 14),
                border_radius=12,
                border=ft.Border.all(
                    1.5 if is_active else 1,
                    GOLD_COLOR if is_active else ft.Colors.with_opacity(0.1, "#ffffff")
                ),
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

        t_key = f"{new_pair}_{new_tf}"
        active_tasks[t_key] = f"Обучение с нуля {new_pair} ({new_tf}): псевдоторговля, проверка TP/SL, отступы лимиток и ИИ-трейлинг..." if lang == "ru" else f"Training new model for {new_pair} ({new_tf})..."
        refresh_models_list()

        try:
            await asyncio.to_thread(scalping_ensemble.bootstrap_virtual_training, new_pair, new_tf)
            show_toast(f"Новая модель для {new_pair} ({new_tf}) успешно создана и обучена!" if lang == "ru" else f"New model for {new_pair} ({new_tf}) successfully created!")
        except Exception as ex:
            show_toast(f"Ошибка создания модели: {ex}", color=RED_COLOR)
        finally:
            active_tasks.pop(t_key, None)
            refresh_models_list()

    create_dialog = ft.AlertDialog(
        title=ft.Text("Обучить новую модель ИИ" if lang == "ru" else "Train New AI Model", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Выберите торговую пару и таймфрейм. При обучении симулируется псевдоторговля, проверяются исходы TP/SL, уровни отложенных ордеров и профили волатильности для ИИ-Трейлинга:" if lang == "ru" else "Select pair and timeframe. Bootstrapping simulates virtual orders, TP/SL hits, limit offsets, and AI trailing stop profiles:", size=11, color="#94a3b8"),
                pair_dd,
                tf_dd
            ], spacing=15, tight=True),
            width=420,
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

    # Fixed top header bar (Non-scrollable)
    top_bar = ft.Row([
        ft.Column([
            ft.Text(t_title, size=22, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            ft.Text(t_desc, size=11, color="#94a3b8")
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

    # Fixed active info banner (Non-scrollable)
    active_info_banner = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ELECTRIC_BOLT_ROUNDED, color=GOLD_COLOR, size=18),
            ft.Text(f"Текущая работающая модель в терминале: {active_pair} ({active_tf})" if lang == "ru" else f"Active model running in engine: {active_pair} ({active_tf})", size=12, color="#e2e8f0", weight=ft.FontWeight.W_600)
        ], spacing=8),
        bgcolor=ft.Colors.with_opacity(0.06, "#ffffff"),
        blur=DEFAULT_BLUR,
        padding=ft.Padding.symmetric(vertical=10, horizontal=16),
        border_radius=8,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.12, "#ffffff"))
    )

    fixed_header = ft.Container(
        content=ft.Column([
            top_bar,
            active_info_banner,
        ], spacing=12),
        bgcolor=COLOR_GLASS_BG,
        blur=DEFAULT_BLUR,
        padding=16,
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.12, "#ffffff"))
    )

    # Scrollable area containing ONLY the models grid
    scrollable_content = ft.Column([
        models_grid
    ], expand=True, scroll=ft.ScrollMode.AUTO, spacing=15)

    # Main view layout - Header fixed at top, models grid scrollable below
    main_column = ft.Column([
        fixed_header,
        scrollable_content
    ], spacing=10, expand=True)

    refresh_models_list()

    return main_column
