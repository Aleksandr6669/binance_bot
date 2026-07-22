import flet as ft
import db
import datetime as _dt_mod
from ui.theme import *
from ui.styles import *
from ui.i18n import t
from ui.layout import build_layout

from ui.helpers import make_textfield, make_dropdown

def utc_to_local(ts_str, tz_offset_min=180):
    """Конвертирует UTC timestamp из БД в локальное время для отображения."""
    if not ts_str:
        return "—"
    try:
        utc_dt = _dt_mod.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt_mod.timezone.utc)
        if tz_offset_min is not None:
            user_tz = _dt_mod.timezone(_dt_mod.timedelta(minutes=tz_offset_min))
            return utc_dt.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
        else:
            return utc_dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts_str

def build_history_view(page: ft.Page, lang: str):
    tz_offset = getattr(page, "tz_offset", 180)
    user_tz = _dt_mod.timezone(_dt_mod.timedelta(minutes=tz_offset))
    today_str = _dt_mod.datetime.now(_dt_mod.timezone.utc).astimezone(user_tz).strftime("%Y-%m-%d")

    rendered_order_controls = {}
    t_loading = t("loading_orders", lang)
    t_no_trades = t("no_trades", lang)
    t_delete_tooltip = t("delete_tooltip", lang)
    t_open_lbl = t("open_lbl", lang)
    t_close_lbl = t("close_lbl", lang)
    t_nav_hist = t("nav_orders", lang)

    history_list = ft.Column(
        controls=[
            ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color="#a78bfa"),
                    ft.Text(t_loading, color="#94a3b8", size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding(0, 40, 0, 40)
            )
        ],
        spacing=10,
        scroll=ft.ScrollMode.ADAPTIVE,
        expand=True
    )
    
    def run_apply(e):
        page.run_task(apply_filters, None)

    # State variables for date ranges - по умолчанию сегодняшний день
    filter_state = {
        "open_start": today_str,
        "open_end": today_str,
        "close_start": today_str,
        "close_end": today_str
    }

    status_options = [
        ("", t("all_statuses", lang)),
        ("CLOSED_TP", t("status_tp", lang)),
        ("CLOSED_SL", t("status_sl", lang)),
        ("CLOSED_MANUAL", t("status_manual", lang)),
        ("CANCELED", t("status_canceled", lang))
    ]

    pair_field = make_textfield(hint_text=t("col_pair", lang), value="", width=100, on_change=run_apply)
    status_dd = make_dropdown(
        label=None,
        options=[ft.dropdown.Option(k, v) for k, v in status_options],
        width=125,
        value="",
        on_change=run_apply
    )
    
    timeframe_options = [
        ("", "Все" if lang == "ru" else "All"),
        ("1m", "1m"),
        ("3m", "3m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("30m", "30m"),
        ("1h", "1h")
    ]
    timeframe_dd = make_dropdown(
        label=None,
        options=[ft.dropdown.Option(k, v) for k, v in timeframe_options],
        width=100,
        value="",
        on_change=run_apply
    )
    
    pair_field.height = 48
    status_dd.height = 48
    status_dd.width = 140
    pair_field.margin = ft.Margin.all(0)
    
    # Wrap status_dd in a Container to properly apply margin/alignment in the Row
    status_container = ft.Container(
        content=status_dd,
        margin=ft.Margin.all(0),
        padding=0
    )
    
    timeframe_container = ft.Container(
        content=timeframe_dd,
        margin=ft.Margin.all(0),
        padding=0
    )
    
    pair_field.content_padding = ft.Padding(10, 14, 10, 14)
    status_dd.content_padding = ft.Padding(10, 14, 10, 14)
    timeframe_dd.content_padding = ft.Padding(10, 14, 10, 14)
    pair_field.text_size = 10
    status_dd.text_style = ft.TextStyle(size=10)
    timeframe_dd.text_style = ft.TextStyle(size=10)
    timeframe_dd.height = 48

    def set_date_and_apply(picker_control):
        if picker_control.value:
            dt = picker_control.value
            # Flet DatePicker возвращает datetime в UTC.
            # Конвертируем в локальный timezone чтобы получить правильную дату
            import datetime as _dt
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            local_dt = dt.astimezone()
            key, text_control, container = picker_control.user_data
            formatted_date = f"{local_dt.year:04d}-{local_dt.month:02d}-{local_dt.day:02d}"
            filter_state[key] = formatted_date
            text_control.value = formatted_date
            text_control.color = "#f8fafc"
            container.update()
            run_apply(None)

    open_start_picker = ft.DatePicker(on_change=lambda e: set_date_and_apply(e.control))
    open_end_picker = ft.DatePicker(on_change=lambda e: set_date_and_apply(e.control))
    close_start_picker = ft.DatePicker(on_change=lambda e: set_date_and_apply(e.control))
    close_end_picker = ft.DatePicker(on_change=lambda e: set_date_and_apply(e.control))
    
    page.overlay.extend([open_start_picker, open_end_picker, close_start_picker, close_end_picker])

    def create_date_button(key, label_placeholder, picker):
        # Initial text color
        init_val = filter_state[key]
        text_control = ft.Text(
            init_val if init_val else label_placeholder,
            size=10,
            color="#f8fafc" if init_val else "#94a3b8"
        )
        
        def open_picker(e):
            picker.open = True
            picker.update()
            
        row_content = ft.Row(
            [
                ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=12, color="#94a3b8"),
                text_control
            ],
            spacing=3,
            alignment=ft.MainAxisAlignment.CENTER
        )
        
        container = ft.Container(
            content=row_content,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, "#ffffff")),
            border_radius=8,
            padding=ft.Padding(6, 0, 6, 0),
            on_click=open_picker,
            bgcolor=ft.Colors.TRANSPARENT,
            alignment=ft.alignment.Alignment(0, 0),
            width=100,
            height=48
        )
        
        picker.user_data = (key, text_control, container)
        return container

    open_start_btn = create_date_button("open_start", "Open From", open_start_picker)
    open_end_btn = create_date_button("open_end", "Open To", open_end_picker)
    close_start_btn = create_date_button("close_start", "Close From", close_start_picker)
    close_end_btn = create_date_button("close_end", "Close To", close_end_picker)

    filter_running = False
    filter_pending = False

    async def apply_filters(e=None):
        nonlocal filter_running, filter_pending
        if filter_running:
            filter_pending = True
            return
        
        filter_running = True
        try:
            while True:
                filter_pending = False
                await apply_filters_internal()
                if not filter_pending:
                    break
        finally:
            filter_running = False

    async def apply_filters_internal():
        # Показываем красивый спиннер загрузки ордеров
        history_list.controls.clear()
        rendered_order_controls.clear()
        history_list.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color="#a78bfa"),
                    ft.Text(t_loading, color="#94a3b8", size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding(0, 40, 0, 40)
            )
        )
        try:
            history_list.update()
        except:
            pass

        import asyncio
        # Загружаем данные в фоновом потоке, не блокируя UI
        orders = await asyncio.to_thread(
            db.get_filtered_orders,
            pair=pair_field.value.upper().strip() if pair_field.value.strip() else None,
            timeframe=timeframe_dd.value if timeframe_dd.value else None,
            status=status_dd.value if status_dd.value else None,
            open_start=filter_state["open_start"] if filter_state["open_start"] else None,
            open_end=filter_state["open_end"] if filter_state["open_end"] else None,
            close_start=filter_state["close_start"] if filter_state["close_start"] else None,
            close_end=filter_state["close_end"] if filter_state["close_end"] else None
        )
        
        history_list.controls.clear()
        rendered_order_controls.clear()
        if not orders:
            summary_card.visible = False
            history_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HISTORY_ROUNDED, size=48, color="#64748b"),
                        ft.Text(t_no_trades, color="#94a3b8", size=14, weight=ft.FontWeight.W_500),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.alignment.Alignment(0, 0),
                    padding=ft.Padding(0, 40, 0, 40)
                )
            )
        else:
            total_pnl_val = sum(float(o["pnl"]) if o["pnl"] is not None else 0.0 for o in orders)
            total_pnl_text.value = f"{total_pnl_val:+.2f}$"
            total_pnl_text.color = "#10b981" if total_pnl_val >= 0 else "#ef4444"
            summary_card.visible = True
            
            def make_delete_handler(order_id):
                async def handler(e):
                    await asyncio.to_thread(db.delete_order, order_id)
                    await apply_filters(None)
                return handler

            for o in orders:
                pnl_val = float(o["pnl"]) if o["pnl"] is not None else 0.0
                pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
                card = ft.Container(
                    content=ft.Row(
                        [
                            # Col 1: Asset Info
                            ft.Column([
                                ft.Row([
                                    ft.Text(f"{o['pair']} ({o.get('timeframe') or '—'})", weight=ft.FontWeight.BOLD, size=14, color="#f8fafc"),
                                    ft.Container(
                                        content=ft.Text(o['side'], size=8, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                        bgcolor="#10b981" if o['side'] == "BUY" else "#ef4444",
                                        border_radius=4,
                                        padding=ft.Padding.symmetric(vertical=1, horizontal=4)
                                    )
                                ], spacing=6),
                                ft.Container(
                                    content=ft.Text(o.get("trading_mode", "DEMO"), size=8, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                                    bgcolor="#0284c7" if o.get("trading_mode") == "LIVE" else "#64748b",
                                    border_radius=4,
                                    padding=ft.Padding.symmetric(vertical=1, horizontal=4)
                                )
                            ], spacing=4, width=175),
                            
                            # Col 2: Entry / Exit
                            ft.Column([
                                ft.Text("ENTRY / EXIT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"${float(o['entry_price']):.2f}", size=12, color="#f8fafc"),
                                ft.Text(f"${float(o['close_price']):.2f}" if o.get('close_price') is not None else "—", size=11, color="#94a3b8")
                            ], spacing=2, width=110),
                            
                            # Col 3: Targets (SL / TP)
                            ft.Column([
                                ft.Text("SL / TP", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"SL: ${float(o['stop_loss']):.2f}" if o.get('stop_loss') else "SL: —", size=11, color="#f43f5e"),
                                ft.Text(f"TP: ${float(o['take_profit']):.2f}" if o.get('take_profit') else "TP: —", size=11, color="#10b981")
                            ], spacing=2, width=110),
                            
                            # Col 4: Position Details (Size & Leverage)
                            ft.Column([
                                ft.Text("STAKE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"${float(o['size_usdt']):.2f}", size=12, color="#f8fafc"),
                                ft.Text(f"Lev: {o['leverage']}x" if o.get('leverage') else "Spot", size=11, color="#94a3b8")
                            ], spacing=2, width=80),
                            
                            # Col 5: Date
                            ft.Column([
                                ft.Text("DATE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(utc_to_local(o['created_at']).split(" ")[0], size=12, color="#f8fafc"),
                                ft.Text(utc_to_local(o['created_at']).split(" ")[1] if " " in utc_to_local(o['created_at']) else "", size=11, color="#94a3b8")
                            ], spacing=2, width=90),
                            
                            # Col 6: PnL & Status
                            ft.Column([
                                ft.Text("RESULT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"{pnl_val:+.2f}$", size=13, weight=ft.FontWeight.BOLD, color=pnl_color),
                                ft.Container(
                                    content=ft.Text(o["status"], size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                    bgcolor="#334155" if "MANUAL" in o["status"] else ("#10b981" if "TP" in o["status"] else "#ef4444"),
                                    padding=ft.Padding.symmetric(vertical=1, horizontal=4),
                                    border_radius=4
                                )
                            ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
                            
                            # Col 7: Action (Delete)
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                icon_color="#f43f5e",
                                tooltip=t_delete_tooltip,
                                on_click=make_delete_handler(o["id"]),
                                width=40
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER
                    ),
                    bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
                    blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
                    border_radius=12,
                    padding=ft.Padding(16, 12, 16, 12),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff"))
                )
                history_list.controls.append(card)
                rendered_order_controls[o["id"]] = card
            try:
                summary_card.update()
            except:
                pass
        page.update()

    # --- Grouped date blocks ---
    open_block = ft.Container(
        content=ft.Row([
            ft.Text(t_open_lbl, size=8, color="#64748b", weight=ft.FontWeight.BOLD),
            ft.Container(width=1, height=16, bgcolor="#334155"),
            open_start_btn,
            ft.Text("—", size=10, color="#475569"),
            open_end_btn,
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.3, "#ffffff")),
        border_radius=8,
        padding=ft.Padding(8, 0, 8, 0),
        bgcolor=ft.Colors.with_opacity(0.02, "#ffffff"),
        height=48,
        expand=False,
    )

    close_block = ft.Container(
        content=ft.Row([
            ft.Text(t_close_lbl, size=8, color="#64748b", weight=ft.FontWeight.BOLD),
            ft.Container(width=1, height=16, bgcolor="#334155"),
            close_start_btn,
            ft.Text("—", size=10, color="#475569"),
            close_end_btn,
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.3, "#ffffff")),
        border_radius=8,
        padding=ft.Padding(8, 0, 8, 0),
        bgcolor=ft.Colors.with_opacity(0.02, "#ffffff"),
        height=48,
        expand=False,
    )

    # Remove individual borders and height constraints from date buttons (they're inside blocks now)
    for btn in [open_start_btn, open_end_btn, close_start_btn, close_end_btn]:
        btn.border = None
        btn.bgcolor = ft.Colors.TRANSPARENT
        btn.height = None

    # Restructured filter card: Inputs on the left, Date Blocks on the right
    filter_card = ft.Container(
        content=ft.Row([
            # Left Group: Symbol, Timeframe, and Status Dropdown
            ft.Row([
                pair_field,
                timeframe_container,
                status_container,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            # Right Group: Open and Close Date blocks
            ft.Row([
                open_block,
                close_block,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True),
        bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
        padding=ft.Padding(12, 8, 12, 8),
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
        blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
    )

    # Summary of filtered orders
    total_pnl_lbl = "Total PnL of displayed orders:"
    if lang == "ru":
        total_pnl_lbl = "Общая прибыль отображаемых ордеров:"
    elif lang == "uk":
        total_pnl_lbl = "Загальний прибуток обраних ордерів:"

    total_pnl_text = ft.Text("$0.00", size=14, weight=ft.FontWeight.BOLD)
    summary_card = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.MONETIZATION_ON_ROUNDED, color="#a78bfa", size=18),
                ft.Text(total_pnl_lbl, size=13, color="#94a3b8", weight=ft.FontWeight.W_500)
            ], spacing=6),
            total_pnl_text
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=ft.Colors.with_opacity(0.03, "#ffffff"),
        padding=ft.Padding(16, 12, 16, 12),
        border_radius=10,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.05, "#ffffff")),
        visible=False
    )
    
    layout = ft.Column(
        [
            ft.Text(t_nav_hist, size=20, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            filter_card,
            summary_card,
            history_list
        ],
        expand=True,
        spacing=15,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH
    )
    
    # Первичная загрузка
    page.load_history_data = apply_filters

    async def history_refresher():
        import asyncio
        while True:
            await asyncio.sleep(0.5)
            if page.route != "/history":
                continue
            
            try:
                orders = await asyncio.to_thread(
                    db.get_filtered_orders,
                    pair=pair_field.value.upper().strip() if pair_field.value.strip() else None,
                    timeframe=timeframe_dd.value if timeframe_dd.value else None,
                    status=status_dd.value if status_dd.value else None,
                    open_start=filter_state["open_start"] if filter_state["open_start"] else None,
                    open_end=filter_state["open_end"] if filter_state["open_end"] else None,
                    close_start=filter_state["close_start"] if filter_state["close_start"] else None,
                    close_end=filter_state["close_end"] if filter_state["close_end"] else None
                )
                
                if page.route != "/history":
                    continue

                db_ids = {o["id"] for o in orders} if orders else set()
                rendered_ids = set(rendered_order_controls.keys())

                if not db_ids and rendered_ids:
                    await apply_filters_internal()
                    continue

                if db_ids and not rendered_ids:
                    await apply_filters_internal()
                    continue

                # Remove deleted orders from UI
                deleted_ids = rendered_ids - db_ids
                if deleted_ids:
                    for oid in deleted_ids:
                        ctrl = rendered_order_controls.pop(oid)
                        try:
                            history_list.controls.remove(ctrl)
                        except:
                            pass

                # Add new orders to UI
                new_added = False
                newly_created_controls = []
                for o in orders:
                    oid = o["id"]
                    if oid not in rendered_order_controls:
                        pnl_val = float(o["pnl"]) if o["pnl"] is not None else 0.0
                        pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
                        
                        def make_delete_handler(order_id):
                            async def handler(e):
                                await asyncio.to_thread(db.delete_order, order_id)
                                await apply_filters(None)
                            return handler

                        card = ft.Container(
                            content=ft.Row(
                                [
                                    # Col 1: Asset Info
                                    ft.Column([
                                        ft.Row([
                                            ft.Text(f"{o['pair']} ({o.get('timeframe') or '—'})", weight=ft.FontWeight.BOLD, size=14, color="#f8fafc"),
                                            ft.Container(
                                                content=ft.Text(o['side'], size=8, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                                bgcolor="#10b981" if o['side'] == "BUY" else "#ef4444",
                                                border_radius=4,
                                                padding=ft.Padding.symmetric(vertical=1, horizontal=4)
                                            )
                                        ], spacing=6),
                                        ft.Container(
                                            content=ft.Text(o.get("trading_mode", "DEMO"), size=8, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                                            bgcolor="#0284c7" if o.get("trading_mode") == "LIVE" else "#64748b",
                                            border_radius=4,
                                            padding=ft.Padding.symmetric(vertical=1, horizontal=4)
                                        )
                                    ], spacing=4, width=175),
                                    
                                    # Col 2: Entry / Exit
                                    ft.Column([
                                        ft.Text("ENTRY / EXIT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                        ft.Text(f"${float(o['entry_price']):.2f}", size=12, color="#f8fafc"),
                                        ft.Text(f"${float(o['close_price']):.2f}" if o.get('close_price') is not None else "—", size=11, color="#94a3b8")
                                    ], spacing=2, width=110),
                                    
                                    # Col 3: Targets (SL / TP)
                                    ft.Column([
                                        ft.Text("SL / TP", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                        ft.Text(f"SL: ${float(o['stop_loss']):.2f}" if o.get('stop_loss') else "SL: —", size=11, color="#f43f5e"),
                                        ft.Text(f"TP: ${float(o['take_profit']):.2f}" if o.get('take_profit') else "TP: —", size=11, color="#10b981")
                                    ], spacing=2, width=110),
                                    
                                    # Col 4: Position Details (Size & Leverage)
                                    ft.Column([
                                        ft.Text("STAKE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                        ft.Text(f"${float(o['size_usdt']):.2f}", size=12, color="#f8fafc"),
                                        ft.Text(f"Lev: {o['leverage']}x" if o.get('leverage') else "Spot", size=11, color="#94a3b8")
                                    ], spacing=2, width=80),
                                    
                                    # Col 5: Date
                                    ft.Column([
                                        ft.Text("DATE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                        ft.Text(utc_to_local(o['created_at']).split(" ")[0], size=12, color="#f8fafc"),
                                        ft.Text(utc_to_local(o['created_at']).split(" ")[1] if " " in utc_to_local(o['created_at']) else "", size=11, color="#94a3b8")
                                    ], spacing=2, width=90),
                                    
                                    # Col 6: PnL & Status
                                    ft.Column([
                                        ft.Text("RESULT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                        ft.Text(f"{pnl_val:+.2f}$", size=13, weight=ft.FontWeight.BOLD, color=pnl_color),
                                        ft.Container(
                                            content=ft.Text(o["status"], size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                            bgcolor="#334155" if "MANUAL" in o["status"] else ("#10b981" if "TP" in o["status"] else "#ef4444"),
                                            padding=ft.Padding.symmetric(vertical=1, horizontal=4),
                                            border_radius=4
                                        )
                                    ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
                                    
                                    # Col 7: Action (Delete)
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                        icon_color="#f43f5e",
                                        tooltip=t_delete_tooltip,
                                        on_click=make_delete_handler(oid),
                                        width=40
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER
                            ),
                            bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
                            blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
                            border_radius=12,
                            padding=ft.Padding(16, 12, 16, 12),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
                            opacity=0,
                            scale=0.8,
                            animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                            animate_scale=ft.Animation(300, ft.AnimationCurve.EASE_OUT_BACK)
                        )
                        
                        insert_idx = 0
                        for existing_ctrl in history_list.controls:
                            existing_id = None
                            for k, v in rendered_order_controls.items():
                                if v == existing_ctrl:
                                    existing_id = k
                                    break
                            if existing_id is not None:
                                existing_order = next((x for x in orders if x["id"] == existing_id), None)
                                if existing_order and o["created_at"] < existing_order["created_at"]:
                                    insert_idx += 1
                                else:
                                    break

                        history_list.controls.insert(insert_idx, card)
                        rendered_order_controls[oid] = card
                        newly_created_controls.append(card)
                        new_added = True

                # Update PnL card value
                if db_ids:
                    total_pnl_val = sum(float(o["pnl"]) if o["pnl"] is not None else 0.0 for o in orders)
                    total_pnl_text.value = f"{total_pnl_val:+.2f}$"
                    total_pnl_text.color = "#10b981" if total_pnl_val >= 0 else "#ef4444"
                    summary_card.visible = True

                if deleted_ids or new_added:
                    try:
                        history_list.update()
                        summary_card.update()
                    except:
                        pass
                    
                    if newly_created_controls:
                        await asyncio.sleep(0.05)
                        for c in newly_created_controls:
                            c.opacity = 1.0
                            c.scale = 1.0
                        try:
                            history_list.update()
                        except:
                            pass
            except Exception as ex:
                print(f"History background refresher error: {ex}")

    page.run_task(history_refresher)
    
    return layout

