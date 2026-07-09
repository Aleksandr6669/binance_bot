import flet as ft
import flet_charts as ftc
import db
import json
import asyncio
from datetime import datetime
from ui.theme import *
from ui.i18n import t, get_lang
from ui.layout import build_layout

def build_dashboard_view(page: ft.Page, lang: str):
    # Хранение текущих данных для графиков и инференса
    current_pair_data = {"klines": [], "price": 0.0}

    # --- Компоненты UI для Dashboard ---
    balance_text = ft.Text("$0.00 USDT", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
    collateral_text = ft.Text("$0.00 USDT", size=14, color="#94a3b8")
    pnl_text = ft.Text("$0.00 (0.00%)", size=18, weight=ft.FontWeight.BOLD, color="#10b981")
    bot_status_label = ft.Text("Strategy Status", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    bot_status_desc = ft.Text("Stopped", size=14, color="#94a3b8")
    bot_toggle_btn = ft.ElevatedButton("Start Bot", color="#ffffff", bgcolor="#0284c7")

    # TA Indicators
    indicator_rsi = ft.Text("RSI: N/A", size=14, color="#f1f5f9")
    indicator_atr = ft.Text("ATR%: N/A", size=14, color="#f1f5f9")
    indicator_macd = ft.Text("MACD: N/A", size=14, color="#f1f5f9")
    indicator_bb = ft.Text("Bollinger Bands: N/A", size=14, color="#f1f5f9")

    # Active Orders
    active_orders_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE)

    # ML Logs
    ml_logs_stage1 = ft.Text("Stage 1 details...", size=13, color="#cbd5e1")
    ml_logs_stage2 = ft.Text("Stage 2 details...", size=13, color="#cbd5e1")
    ml_logs_stage3 = ft.Text("Stage 3 details...", size=13, color="#cbd5e1")
    ml_log_time = ft.Text("Last run: N/A", size=11, italic=True, color="#64748b")

    # Chart Control
    chart_series = []
    price_chart = ftc.LineChart(
        data_series=chart_series,
        border=ft.Border(
            bottom=ft.BorderSide(1, "#334155"),
            left=ft.BorderSide(1, "#334155")
        ),
        left_axis=ftc.ChartAxis(label_size=40),
        bottom_axis=ftc.ChartAxis(label_size=30),
        interactive=True,
        expand=True,
        min_y=0,
        max_y=1
    )
    chart_container = ft.Container(
        content=ft.Text("Загрузка графика...", color="#94a3b8", size=16, weight=ft.FontWeight.BOLD),
        alignment=ft.alignment.Alignment(0, 0),
        bgcolor=CARD_COLOR,
        border_radius=12,
        padding=20,
        height=320,
        expand=True
    )


    async def fetch_dashboard_data():
        user_id = page.session.store.get("user_id")
        if not user_id or page.route != "/dashboard":
            return
        
        settings = dict(db.get_user_settings(user_id) or {})
        pair = settings.get("trading_pair", "BTCUSDT")
        timeframe = settings.get("timeframe", "1m")
        market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
        trading_mode = dict(settings).get("trading_mode", "DEMO") or "DEMO"
        is_live = (trading_mode == "LIVE")
    
        # 1. Загрузка балансов
        if is_live:
            bal = trading_engine.fetch_binance_balance(user_id, market_type)
            balance_val = float(bal) if bal is not None else 0.0
            balance_text.value = f"${balance_val:,.2f} USDT"
            collateral_text.value = "Live Account Balance (Binance)"
        else:
            demo_bal = float(settings.get("demo_balance") or 10000.0)
            balance_text.value = f"${demo_bal:,.2f} USDT"
        
            # Рассчитаем задействованную маржу/обеспечение
            active_orders = db.get_active_orders(user_id)
            collateral_val = sum(float(o["size_usdt"]) for o in active_orders)
            collateral_text.value = f"{t('wallet_collateral', get_lang(page))}: ${collateral_val:,.2f} USDT"
        
        # 2. Расчет заработка/PnL
        daily_pnl = db.get_daily_pnl(user_id, trading_mode=trading_mode)
        pnl_val = float(daily_pnl.get("pnl", 0.0))
        pnl_pct = float(daily_pnl.get("pct", 0.0))
        pnl_text.value = f"${pnl_val:+.2f} ({pnl_pct:+.2f}%)"
        pnl_text.color = "#10b981" if pnl_val >= 0 else "#ef4444"
    
        # 3. Активные ордера
        active_orders = db.get_active_orders(user_id)
        active_orders_column.controls.clear()
    
        current_price = 0.0
        try:
            current_price = trading_engine.fetch_current_price(pair, market_type)
        except:
            pass
        
        if not active_orders:
            active_orders_column.controls.append(ft.Text(t("no_active_orders", get_lang(page)), color="#94a3b8", italic=True))
        else:
            for o in active_orders:
                amount = float(o["amount"])
                entry = float(o["entry_price"])
                side = o["side"]
            
                # Нереализованный PNL
                unrealized = 0.0
                if current_price > 0:
                    if side == "BUY":
                        unrealized = amount * (current_price - entry)
                    else:
                        unrealized = amount * (entry - current_price)
                    
                unrealized_color = "#10b981" if unrealized >= 0 else "#ef4444"
            
                def make_close_handler(order_id):
                    def handler(e):
                        threading.Thread(
                            target=lambda: trading_engine.liquidate_order_manually(order_id),
                            daemon=True
                        ).start()
                    return handler

                order_row = ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(f"{o['pair']} ({o['side']})", weight=ft.FontWeight.BOLD, size=14),
                                    ft.Text(f"Entry: ${entry:.2f} | Current: ${current_price:.2f}", size=11, color="#94a3b8")
                                ],
                                spacing=3,
                                expand=True
                            ),
                            ft.Text(f"${unrealized:+.2f}", weight=ft.FontWeight.BOLD, color=unrealized_color, size=13),
                            ft.IconButton(
                                icon=ft.Icons.CANCEL_ROUNDED,
                                icon_color="#ef4444",
                                tooltip="Close Order",
                                on_click=make_close_handler(o["id"])
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    padding=10,
                    bgcolor=BG_COLOR,
                    border_radius=8,
                    border=ft.Border.all(1, "#334155")
                )
                active_orders_column.controls.append(order_row)
            
        # 4. Технические Индикаторы
        try:
            klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=100, market_type=market_type)
            from indicators import get_latest_indicators
            latest_ti = get_latest_indicators(klines)
            if latest_ti and "error" not in latest_ti:
                indicator_rsi.value = f"RSI: {latest_ti.get('rsi', 0.0):.2f}"
                indicator_atr.value = f"ATR%: {latest_ti.get('atr_pct', 0.0):.4f}%"
                indicator_macd.value = f"MACD: {latest_ti.get('macd', 'N/A')}"
                indicator_bb.value = f"Bollinger Bands: {latest_ti.get('bb_signal', 'N/A')}"
        except Exception as ex:
            pass

        # 5. Логи ИИ
        latest_log = db.get_latest_analysis_log(user_id, pair)
        if latest_log:
            ml_logs_stage1.value = latest_log["stage1_output"]
            ml_logs_stage2.value = latest_log["stage2_output"]
            ml_logs_stage3.value = latest_log["stage3_output"]
            ml_log_time.value = f"Last run: {latest_log['created_at']}"
        else:
            ml_logs_stage1.value = t("no_logs", get_lang(page))
            ml_logs_stage2.value = ""
            ml_logs_stage3.value = ""
            ml_log_time.value = ""
        
        # 6. Отрисовка графика
        try:
            chart_klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=50, market_type=market_type)
            if chart_klines:
                closes = [float(k[4]) for k in chart_klines]
                times = [datetime.fromtimestamp(k[0]/1000).strftime("%H:%M") for k in chart_klines]
            
                min_c = min(closes)
                max_c = max(closes)
                spread = max_c - min_c
            
                # Добавим небольшой отступ
                min_y_val = min_c - spread * 0.1 if spread > 0 else min_c * 0.99
                max_y_val = max_c + spread * 0.1 if spread > 0 else max_c * 1.01
            
                # Основная серия цены
                price_points = [ftc.LineChartDataPoint(i, closes[i]) for i in range(len(closes))]
                price_series = ftc.LineChartData(
                    data_points=price_points,
                    stroke_width=3,
                    color="#0284c7",
                    curved=True,
                    below_line_fill_color=ft.Colors.with_opacity(0.15, "#0284c7"),
                    below_line_fill_type=ftc.ExtraLineChartFillType.SOLID
                )
            
                series_list = [price_series]
            
                # Горизонтальные линии для активных ордеров
                for o in active_orders:
                    entry = float(o["entry_price"])
                    # Линия входа (голубая)
                    series_list.append(
                        ftc.LineChartData(
                            data_points=[ftc.LineChartDataPoint(0, entry), ftc.LineChartDataPoint(len(closes)-1, entry)],
                            stroke_width=1.5,
                            color="#38bdf8",
                            stroke_dash_array=[5, 5]
                        )
                    )
                
                    if o["take_profit"]:
                        tp = float(o["take_profit"])
                        # Линия TP (зеленая)
                        series_list.append(
                            ftc.LineChartData(
                                data_points=[ftc.LineChartDataPoint(0, tp), ftc.LineChartDataPoint(len(closes)-1, tp)],
                                stroke_width=1,
                                color="#10b981",
                                stroke_dash_array=[3, 3]
                            )
                        )
                    
                    if o["stop_loss"]:
                        sl = float(o["stop_loss"])
                        # Линия SL (красная)
                        series_list.append(
                            ftc.LineChartData(
                                data_points=[ftc.LineChartDataPoint(0, sl), ftc.LineChartDataPoint(len(closes)-1, sl)],
                                stroke_width=1,
                                color="#ef4444",
                                stroke_dash_array=[3, 3]
                            )
                        )
            
                # Обновление осей
                price_chart.data_series = series_list
                price_chart.min_y = min_y_val
                price_chart.max_y = max_y_val
                price_chart.bottom_axis = ftc.ChartAxis(
                    labels=[
                        ftc.ChartAxisLabel(value=i, label=ft.Text(times[i], size=9, color="#64748b"))
                        for i in range(0, len(times), 10)
                    ],
                    label_size=30
                )
            
                # Если в контейнере текст, заменяем его на график
                if not isinstance(chart_container.content, ftc.LineChart):
                    chart_container.content = price_chart
            else:
                chart_container.content = ft.Text("Ошибка получения свечей с Binance", color="#ef4444", size=14)
        except Exception as e:
            chart_container.content = ft.Text(f"Ошибка загрузки графика: {str(e)}", color="#ef4444", size=12)

        page.update()



    async def dashboard_refresher():
        import asyncio
        while True:
            await asyncio.sleep(2)
            try:
                _ = balance_text.page
            except:
                break
            if not _: # view was destroyed
                break
            if page.route == "/dashboard" and page.session.store.get("user_id"):
                try:
                    await fetch_dashboard_data()
                except Exception as e:
                    print(f"Error in dashboard refresher: {e}")
                    
    page.run_task(dashboard_refresher)


    user_id = page.session.store.get("user_id")
    settings = dict(db.get_user_settings(user_id) or {})

    # Обновление состояния кнопки старта/останова бота
    is_enabled = settings.get("bot_enabled", 0) == 1
    bot_toggle_btn.text = t("stop_bot", lang) if is_enabled else t("start_bot", lang)
    bot_toggle_btn.bgcolor = "#ef4444" if is_enabled else "#0284c7"

    bot_status_desc.value = t("bot_active", lang, pair=settings.get("trading_pair", "N/A")) if is_enabled else t("bot_stopped", lang)
    bot_status_desc.color = "#10b981" if is_enabled else "#94a3b8"

    def toggle_bot_click(e):
        new_val = 0 if settings.get("bot_enabled", 0) == 1 else 1
        db.update_user_settings(user_id, "bot_enabled", new_val)
        # перезагрузить view
        page.go("/loading"); page.go(page.route)
    
    bot_toggle_btn.on_click = toggle_bot_click

    # Секция быстрых действий
    def trigger_analysis(e):
        e.control.disabled = True
        page.update()
        # Запуск в потоке, чтобы не вешать UI
        threading.Thread(
            target=lambda: trading_engine.evaluate_market_signal(user_id, persist_log=True, place_order=True),
            daemon=True
        ).start()
    
    action_btn = ft.ElevatedButton(
        t("trigger_ml", lang),
        on_click=trigger_analysis,
        bgcolor="#8b5cf6",
        color="#ffffff"
    )

    # Компоновка дашборда на базе ft.ResponsiveRow (адаптивная сетка)
    # Карта баланса
    balance_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(t("demo_balance", lang), size=14, color="#94a3b8"),
                balance_text,
                collateral_text,
                pnl_text
            ],
            spacing=5
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 6}
    )

    # Карта управления ботом
    bot_card = ft.Container(
        content=ft.Column(
            [
                bot_status_label,
                bot_status_desc,
                bot_toggle_btn,
                ft.Divider(color="#334155"),
                action_btn
            ],
            spacing=10
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 6}
    )

    # Сетка индикаторов
    indicators_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(t("ta_indicators", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SHOW_CHART_ROUNDED, color="#0284c7"),
                        indicator_rsi
                    ]
                ),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TIMELAPSE_ROUNDED, color="#0284c7"),
                        indicator_atr
                    ]
                ),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.ALIGN_VERTICAL_BOTTOM_ROUNDED, color="#0284c7"),
                        indicator_macd
                    ]
                ),
                ft.Row(
                    [
                        ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, color="#0284c7"),
                        indicator_bb
                    ]
                ),
            ],
            spacing=10
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 4}
    )

    # Секция графика
    chart_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(t("price_chart", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                chart_container
            ],
            expand=True
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 12}
    )

    # Логи ИИ
    logs_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(t("ml_pipeline_log", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                ft.Text(t("stage1_title", lang), size=13, weight=ft.FontWeight.BOLD, color="#38bdf8"),
                ml_logs_stage1,
                ft.Text(t("stage2_title", lang), size=13, weight=ft.FontWeight.BOLD, color="#fbbf24"),
                ml_logs_stage2,
                ft.Text(t("stage3_title", lang), size=13, weight=ft.FontWeight.BOLD, color="#f43f5e"),
                ml_logs_stage3,
                ml_log_time
            ],
            spacing=8
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 12}
    )

    # Активные ордера
    orders_card = ft.Container(
        content=ft.Column(
            [
                ft.Text(t("active_orders", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                active_orders_column
            ],
            spacing=10
        ),
        bgcolor=CARD_COLOR,
        padding=20,
        border_radius=12,
        col={"xs": 12, "md": 8}
    )

    main_layout = ft.ResponsiveRow(
        [
            balance_card,
            bot_card,
            chart_card,
            orders_card,
            indicators_card,
            logs_card
        ],
        spacing=16
    )

    # Форсированный первый апдейт данных при входе на дашборд
    page.run_task(fetch_dashboard_data)

    return build_layout(page, main_layout, 0, lang)

