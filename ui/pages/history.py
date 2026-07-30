import flet as ft
import flet_charts as ftc
import db
import trading_engine
import datetime as _dt_mod
from ui.theme import *
from ui.styles import *
from ui.i18n import t
from ui.layout import build_layout

from ui.helpers import make_textfield, make_dropdown

def utc_to_local(ts_str, tz_offset_min=None):
    """Конвертирует UTC timestamp из БД в локальное время устройства для отображения."""
    if not ts_str:
        return "—"
    if tz_offset_min is None:
        tz_offset_min = db.get_host_tz_offset_min()
    try:
        clean_ts = str(ts_str).split(".")[0].replace("T", " ")
        utc_dt = _dt_mod.datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt_mod.timezone.utc)
        user_tz = _dt_mod.timezone(_dt_mod.timedelta(minutes=tz_offset_min))
        return utc_dt.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_str)

SAVED_HISTORY_FILTERS = {
    "pair": "",
    "status": "",
    "timeframe": "",
    "mode": "",
    "open_start": None,
    "open_end": None,
    "close_start": None,
    "close_end": None
}

def build_history_view(page: ft.Page, lang: str):
    global SAVED_HISTORY_FILTERS
    tz_offset = getattr(page, "tz_offset", None) or db.get_host_tz_offset_min()
    page.tz_offset = tz_offset
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
        global SAVED_HISTORY_FILTERS
        SAVED_HISTORY_FILTERS["pair"] = pair_field.value or ""
        SAVED_HISTORY_FILTERS["status"] = status_dd.value or ""
        SAVED_HISTORY_FILTERS["timeframe"] = timeframe_dd.value or ""
        SAVED_HISTORY_FILTERS["mode"] = mode_dd.value or ""
        SAVED_HISTORY_FILTERS["open_start"] = filter_state["open_start"]
        SAVED_HISTORY_FILTERS["open_end"] = filter_state["open_end"]
        SAVED_HISTORY_FILTERS["close_start"] = filter_state["close_start"]
        SAVED_HISTORY_FILTERS["close_end"] = filter_state["close_end"]
        page.run_task(apply_filters, None)

    # State variables for date ranges - подтягиваем сохраненные значения
    filter_state = {
        "open_start": SAVED_HISTORY_FILTERS["open_start"] or today_str,
        "open_end": SAVED_HISTORY_FILTERS["open_end"] or today_str,
        "close_start": SAVED_HISTORY_FILTERS["close_start"] or today_str,
        "close_end": SAVED_HISTORY_FILTERS["close_end"] or today_str
    }

    status_options = [
        ("", t("all_statuses", lang)),
        ("CLOSED_TP", t("status_tp", lang)),
        ("CLOSED_SL", t("status_sl", lang)),
        ("CLOSED_AI", "Закрыто по ИИ" if lang == "ru" else "Closed by AI"),
        ("CLOSED_MANUAL", t("status_manual", lang)),
        ("CANCELED", t("status_canceled", lang))
    ]

    pair_field = make_textfield(hint_text=t("col_pair", lang), value=SAVED_HISTORY_FILTERS["pair"], width=100, on_change=run_apply)
    status_dd = make_dropdown(
        label=None,
        options=[ft.dropdown.Option(k, v) for k, v in status_options],
        width=155,
        value=SAVED_HISTORY_FILTERS["status"],
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
        value=SAVED_HISTORY_FILTERS["timeframe"],
        on_change=run_apply
    )

    mode_options = [
        ("", "Все типы" if lang == "ru" else "All Types"),
        ("LIVE", "LIVE"),
        ("DEMO", "DEMO")
    ]
    mode_dd = make_dropdown(
        label=None,
        options=[ft.dropdown.Option(k, v) for k, v in mode_options],
        width=135,
        value=SAVED_HISTORY_FILTERS["mode"],
        on_change=run_apply
    )
    
    pair_field.height = 48
    status_dd.height = 48
    status_dd.width = 155
    timeframe_dd.height = 48
    mode_dd.height = 48
    mode_dd.width = 135
    pair_field.margin = ft.Margin.all(0)
    
    # Wrap dropdowns in Containers to properly apply margin/alignment in the Row
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

    mode_container = ft.Container(
        content=mode_dd,
        margin=ft.Margin.all(0),
        padding=0
    )
    
    pair_field.content_padding = ft.Padding(10, 14, 10, 14)
    status_dd.content_padding = ft.Padding(10, 14, 10, 14)
    timeframe_dd.content_padding = ft.Padding(10, 14, 10, 14)
    mode_dd.content_padding = ft.Padding(10, 14, 10, 14)
    pair_field.text_size = 10
    status_dd.text_style = ft.TextStyle(size=10)
    timeframe_dd.text_style = ft.TextStyle(size=10)
    mode_dd.text_style = ft.TextStyle(size=10)

    def set_date_and_apply(picker_control):
        if picker_control.value:
            dt = picker_control.value
            key, text_control, container = picker_control.user_data
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt_mod.timezone.utc)
            local_dt = dt.astimezone(user_tz)
            formatted_date = local_dt.strftime("%Y-%m-%d")
            filter_state[key] = formatted_date
            text_control.value = formatted_date
            text_control.color = "#f8fafc"
            container.update()
            run_apply(None)

    init_dt = _dt_mod.datetime.now(_dt_mod.timezone.utc).astimezone(user_tz).replace(hour=12, minute=0, second=0)
    open_start_picker = ft.DatePicker(value=init_dt, on_change=lambda e: set_date_and_apply(e.control))
    open_end_picker = ft.DatePicker(value=init_dt, on_change=lambda e: set_date_and_apply(e.control))
    close_start_picker = ft.DatePicker(value=init_dt, on_change=lambda e: set_date_and_apply(e.control))
    close_end_picker = ft.DatePicker(value=init_dt, on_change=lambda e: set_date_and_apply(e.control))
    
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
            if filter_state[key]:
                try:
                    parsed = _dt_mod.datetime.strptime(filter_state[key], "%Y-%m-%d")
                    picker.value = parsed.replace(hour=12, minute=0, second=0, tzinfo=user_tz)
                except Exception:
                    pass
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
        # Показываем спиннер загрузки только при пустом списке (первичная загрузка)
        if not rendered_order_controls and not history_list.controls:
            history_list.controls.clear()
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
        import trading_engine
        # Синхронизируем реальные ордера с Binance перед отрисовкой
        await asyncio.to_thread(trading_engine.sync_live_orders_from_binance)

        # Загружаем данные в фоновом потоке, не блокируя UI
        orders = await asyncio.to_thread(
            db.get_filtered_orders,
            pair=pair_field.value.upper().strip() if pair_field.value.strip() else None,
            timeframe=timeframe_dd.value if timeframe_dd.value else None,
            trading_mode=mode_dd.value if mode_dd.value else None,
            status=status_dd.value if status_dd.value else None,
            open_start=filter_state["open_start"] if filter_state["open_start"] else None,
            open_end=filter_state["open_end"] if filter_state["open_end"] else None,
            close_start=filter_state["close_start"] if filter_state["close_start"] else None,
            close_end=filter_state["close_end"] if filter_state["close_end"] else None,
            tz_offset_min=tz_offset
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
            total_pnl_val = sum(
                float(o["pnl"]) 
                for o in orders 
                if (o.get("status") in ["CLOSED_TP", "CLOSED_SL", "CLOSED_MANUAL"] or (o.get("status") and str(o.get("status")).startswith("CLOSED_AI"))) 
                and o.get("pnl") is not None
            )
            total_pnl_text.value = f"{total_pnl_val:+.2f}$"
            total_pnl_text.color = "#10b981" if total_pnl_val >= 0 else "#ef4444"
            summary_card.visible = True
            
            def make_delete_handler(order_id):
                async def handler(e):
                    await asyncio.to_thread(db.delete_order, order_id)
                    await apply_filters(None)
                return handler

            for o in orders:
                is_canceled = (o.get("status") == "CANCELED")
                pnl_val = float(o["pnl"]) if (o["pnl"] is not None and not is_canceled) else 0.0
                pnl_color = "#94a3b8" if is_canceled else ("#10b981" if pnl_val >= 0 else "#ef4444")
                pnl_display_str = "$0.00" if is_canceled else f"{pnl_val:+.2f}$"
                
                # Фиолетово-синий плашка для ордеров, закрытых по ИИ
                st_str = str(o.get("status", ""))
                if is_canceled:
                    status_bg = "#64748b"
                elif "AI" in st_str:
                    status_bg = "#8b5cf6"
                elif "MANUAL" in st_str:
                    status_bg = "#334155"
                elif "TP" in st_str:
                    status_bg = "#10b981"
                else:
                    status_bg = "#ef4444"

                # Парсинг 5-7 свечей штампа закрытия (или генерирование вектора движения от входа к выходу)
                # 100% Высокая отчетливость штампа: нормализация цен 10..90 по высоте
                snap_raw_prices = []
                try:
                    if o.get("chart_snapshot"):
                        import json as _json
                        vals = _json.loads(o["chart_snapshot"])
                        if isinstance(vals, list) and vals:
                            snap_raw_prices = [float(v) for v in vals]
                except Exception:
                    pass

                if len(snap_raw_prices) < 3 or (max(snap_raw_prices) == min(snap_raw_prices)):
                    e_p = float(o['entry_price'])
                    c_p = float(o['close_price']) if (o.get('close_price') is not None and not is_canceled) else e_p
                    diff = c_p - e_p
                    if abs(diff) < 0.001:
                        diff = (e_p * 0.0015) if pnl_val >= 0 else (-e_p * 0.0015)
                    snap_raw_prices = [
                        e_p,
                        e_p + diff * 0.35,
                        e_p + diff * 0.15,
                        e_p + diff * 0.75,
                        e_p + diff * 0.50,
                        e_p + diff * 1.15,
                        c_p
                    ]

                # 🎯 Схема главного рабочего графика trading_chart.py для 100% красивой кривой штампа!
                e_p = float(o['entry_price'])
                c_p = float(o['close_price']) if (o.get('close_price') is not None and not is_canceled) else e_p

                min_sp = min(snap_raw_prices) if snap_raw_prices else e_p
                max_sp = max(snap_raw_prices) if snap_raw_prices else e_p
                sp_span = (max_sp - min_sp)

                if sp_span < (e_p * 0.0005):
                    direction = 1.0 if (pnl_val >= 0) else -1.0
                    base_delta = e_p * 0.0025
                    multipliers = [0.0, 0.45, 0.15, 0.75, 0.35, 0.95, 0.55, 0.85, 0.65, 1.0] if direction > 0 else [0.0, -0.45, -0.15, -0.75, -0.35, -0.95, -0.55, -0.85, -0.65, -1.0]
                    snap_raw_prices = [e_p + base_delta * m for m in multipliers]
                    min_sp = min(snap_raw_prices)
                    max_sp = max(snap_raw_prices)
                    sp_span = max_sp - min_sp

                snap_pts = [ftc.LineChartDataPoint(i, snap_raw_prices[i]) for i in range(len(snap_raw_prices))]
                
                min_sy_val = min_sp - sp_span * 0.15
                max_sy_val = max_sp + sp_span * 0.15
                max_sx_val = len(snap_raw_prices) - 1

                snap_fill_bg = ft.Colors.with_opacity(0.18, pnl_color)

                snap_mini_chart = ftc.LineChart(
                    data_series=[
                        ftc.LineChartData(
                            points=snap_pts,
                            stroke_width=2.5,
                            color=pnl_color,
                            curved=True,
                            below_line_bgcolor=snap_fill_bg
                        )
                    ],
                    interactive=False,
                    border=ft.Border.all(0, ft.Colors.TRANSPARENT),
                    min_x=0,
                    max_x=max_sx_val,
                    min_y=min_sy_val,
                    max_y=max_sy_val,
                    left_axis=None,
                    bottom_axis=None,
                    top_axis=None,
                    right_axis=None,
                    horizontal_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
                    vertical_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
                    height=42,
                    expand=True
                )

                b_id = str(o.get("binance_order_id")) if o.get("binance_order_id") else None
                id_label_str = f"#{o.get('id')} • B: {b_id}" if b_id else f"#{o.get('id')}"

                card = ft.Container(
                    content=ft.Row(
                        [
                            # Col 1: Asset Info
                            ft.Column([
                                ft.Text(id_label_str, size=9, color="#64748b", weight=ft.FontWeight.W_500),
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
                            ], spacing=2, width=150),
                            
                            # Col 2: Date (ПЕРЕД ЦЕНОЙ ВХОДА)
                            ft.Column([
                                ft.Text("DATE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(utc_to_local(o['created_at'], tz_offset).split(" ")[0], size=11, color="#f8fafc"),
                                ft.Text(utc_to_local(o['created_at'], tz_offset).split(" ")[1] if " " in utc_to_local(o['created_at'], tz_offset) else "", size=10, color="#94a3b8")
                            ], spacing=2, width=90),

                            # Col 3: Entry / Exit
                            ft.Column([
                                ft.Text("ENTRY / EXIT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"${float(o['entry_price']):.2f}", size=12, color="#f8fafc"),
                                ft.Text(f"${float(o['close_price']):.2f}" if (o.get('close_price') is not None and not is_canceled) else "—", size=11, color="#94a3b8")
                            ], spacing=2, width=100),
                            
                            # Col 4: Position Details (STAKE & Leverage - ПЕРЕД СТОПАМИ)
                            ft.Column([
                                ft.Text("STAKE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"${float(o['size_usdt']):.2f}", size=12, color="#f8fafc"),
                                ft.Text(f"Lev: {o['leverage']}x" if o.get('leverage') else "Spot", size=11, color="#94a3b8")
                            ], spacing=2, width=75),

                            # Col 5: Targets (SL / TP)
                            ft.Column([
                                ft.Text("SL / TP", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(f"SL: ${float(o['stop_loss']):.2f}" if o.get('stop_loss') else "SL: —", size=11, color="#f43f5e"),
                                ft.Text(f"TP: ${float(o['take_profit']):.2f}" if o.get('take_profit') else "TP: —", size=11, color="#10b981")
                            ], spacing=2, width=105),
                            
                            # Col 6: Чистый график кривой свечей без выпирающего текста
                            ft.Container(
                                content=snap_mini_chart,
                                padding=ft.Padding.symmetric(horizontal=4, vertical=2),
                                expand=True
                            ),
                            
                            # Col 7: PnL, Status & Action (Результат и кнопка удаления ордера аккуратно рядом)
                            ft.Column([
                                ft.Text("RESULT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                ft.Text(pnl_display_str, size=13, weight=ft.FontWeight.BOLD, color=pnl_color),
                                ft.Row([
                                    ft.Container(
                                        content=ft.Text(o["status"], size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                        bgcolor=status_bg,
                                        padding=ft.Padding.symmetric(vertical=2, horizontal=5),
                                        border_radius=4
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                        icon_size=18,
                                        icon_color="#f43f5e",
                                        tooltip=t_delete_tooltip,
                                        on_click=make_delete_handler(o["id"]),
                                        padding=0,
                                        width=24,
                                        height=24
                                    )
                                ], spacing=6, alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                            ], spacing=3, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END, width=125)
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
            # Left Group: Symbol, Timeframe, Mode, and Status Dropdown
            ft.Row([
                pair_field,
                timeframe_container,
                mode_container,
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
            await asyncio.sleep(2.0)
            if page.route != "/history":
                continue
            
            try:
                await asyncio.to_thread(trading_engine.sync_live_orders_from_binance)
                orders = await asyncio.to_thread(
                    db.get_filtered_orders,
                    pair=pair_field.value.upper().strip() if pair_field.value.strip() else None,
                    timeframe=timeframe_dd.value if timeframe_dd.value else None,
                    trading_mode=mode_dd.value if mode_dd.value else None,
                    status=status_dd.value if status_dd.value else None,
                    open_start=filter_state["open_start"] if filter_state["open_start"] else None,
                    open_end=filter_state["open_end"] if filter_state["open_end"] else None,
                    close_start=filter_state["close_start"] if filter_state["close_start"] else None,
                    close_end=filter_state["close_end"] if filter_state["close_end"] else None,
                    tz_offset_min=tz_offset
                )
                
                if page.route != "/history":
                    continue

                db_pnl_hash = tuple((o["id"], o.get("pnl"), o.get("close_price")) for o in (orders or []))
                if not hasattr(page, "_last_orders_hash") or page._last_orders_hash != db_pnl_hash:
                    page._last_orders_hash = db_pnl_hash
                    await apply_filters_internal()
            except Exception as e_refr:
                print(f"History background refresher error: {e_refr}")

    page.run_task(history_refresher)
    
    return layout

