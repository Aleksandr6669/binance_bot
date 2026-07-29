import os
import flet as ft
import flet_charts as ftc
import db
import json
import trading_engine
import scalping_ensemble
import cast_manager
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from ui.theme import *
from ui.i18n import t, get_lang
from ui.layout import build_layout

def is_destroyed_session_error(e):
    err = str(e).lower()
    return any(x in err for x in [
        "session closed", "destroyed session",
        "has been closed", "connection closed",
        "websocket", "broken pipe"
    ])

SAVED_ORDERBOOK_STEP = "0.01"
SAVED_CHART_LIMIT = 50
SAVED_CHART_OFFSET = 0
SAVED_CHART_Y_SHIFT = 0.0

def build_dashboard_view(page: ft.Page, lang: str):
    global SAVED_ORDERBOOK_STEP, SAVED_CHART_LIMIT, SAVED_CHART_OFFSET, SAVED_CHART_Y_SHIFT
    # Хранение текущих данных для графиков и инференса
    current_pair_data = {"klines": [], "price": 0.0}
    cached_raw_klines = []
    rendered_orders = {}

    # --- Компоненты UI для Dashboard ---
    balance_card_title = ft.Text(t("demo_balance", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    balance_text = ft.Text("$0.00 USDT", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
    collateral_text = ft.Text("$0.00 USDT", size=14, color="#94a3b8")
    pnl_text = ft.Text("$0.00 (0.00%)", size=18, weight=ft.FontWeight.BOLD, color="#10b981")
    pnl_7d_val_text = ft.Text("$0.00", size=12, weight=ft.FontWeight.BOLD, color="#10b981")
    pnl_30d_val_text = ft.Text("$0.00", size=12, weight=ft.FontWeight.BOLD, color="#10b981")
    
    equity_chart_series = []
    equity_mini_chart = ftc.LineChart(
        data_series=equity_chart_series,
        border=ft.Border.all(0, ft.Colors.TRANSPARENT),
        left_axis=ftc.ChartAxis(labels=[]),
        bottom_axis=ftc.ChartAxis(labels=[]),
        top_axis=ftc.ChartAxis(labels=[]),
        right_axis=ftc.ChartAxis(labels=[]),
        horizontal_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
        vertical_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
        expand=True,
        height=45,
        interactive=True
    )
    bot_status_label = ft.Text("Strategy Status", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    bot_status_desc = ft.Text("Stopped", size=14, color="#94a3b8")
    bot_toggle_btn_text = ft.Text("Start Bot", color="#ffffff")
    bot_toggle_btn = ft.ElevatedButton(content=bot_toggle_btn_text, bgcolor="#0284c7")

    # AI Live Widget Controls (for Bot Management Card)
    ai_live_action_text = ft.Text("⏸ НЕЙТРАЛЬНО", size=11, weight=ft.FontWeight.BOLD, color="#94a3b8")
    ai_live_action_badge = ft.Container(
        content=ai_live_action_text,
        padding=ft.Padding.symmetric(vertical=2, horizontal=7),
        border_radius=6,
        bgcolor=ft.Colors.with_opacity(0.12, "#94a3b8"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.25, "#94a3b8"))
    )
    ai_live_clock_text = ft.Text("00:00:00 (UTC+3)", size=10, weight=ft.FontWeight.BOLD, color="#10b981")
    ai_live_trend_text = ft.Text("📊 Тренд: —  ⚡ ATR: —", size=11, weight=ft.FontWeight.W_500, color="#94a3b8")
    ai_live_confidence_text = ft.Text("Уверенность: 0.0%", size=12, weight=ft.FontWeight.BOLD, color="#f8fafc")
    ai_live_threshold_text = ft.Text("Порог: 65.0%", size=11, color="#94a3b8")
    ai_live_progress_bar = ft.ProgressBar(value=0.0, color="#10b981", bgcolor=ft.Colors.with_opacity(0.1, "#ffffff"), height=4, border_radius=2)

    t_chart = t("price_chart", lang)
    t_ai_strat = t("ai_strategy", lang)
    t_wait_data = t("waiting_data", lang)

    # Chart & Price
    chart_title = ft.Text(t_chart, size=14, weight=ft.FontWeight.BOLD, color="#f8fafc", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    indicator_price = ft.Text("Price: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")

    # TA Indicators
    indicator_rsi = ft.Text("RSI: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_atr = ft.Text("ATR%: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_macd = ft.Text("MACD: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_bb = ft.Text("Bollinger Bands: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")

    # Active Orders
    active_orders_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE)
    orders_card_title_text = ft.Text(t("active_orders", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    order_history_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE, height=200)
    logs_history_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE, height=250)

    # Order Book & Walls components
    orderbook_bids_col = ft.Column(spacing=4, expand=True)
    orderbook_asks_col = ft.Column(spacing=4, expand=True)
    orderbook_wall_badge = ft.Text("Анализ плотностей стакана...", size=11, color="#38bdf8", weight=ft.FontWeight.W_500)

    # Liquidation Map components
    liq_map_shorts_col = ft.Column(spacing=4, expand=True)
    liq_map_longs_col = ft.Column(spacing=4, expand=True)
    liq_map_magnet_badge = ft.Text("Моделирование ликвидности...", size=11, color="#a78bfa", weight=ft.FontWeight.W_500)

    # ML Logs
    ml_strategy_title = ft.Text(t_ai_strat, size=15, weight=ft.FontWeight.BOLD, color="#f8fafc", expand=True)
    ml_logs_stage1 = ft.Text(t_wait_data, size=12, color="#94a3b8", selectable=True, no_wrap=False, font_family="monospace")
    ml_logs_stage2 = ft.Text(t_wait_data, size=12, color="#94a3b8", selectable=True, no_wrap=False, font_family="monospace")
    ml_logs_stage3 = ft.Text(t_wait_data, size=12, color="#94a3b8", selectable=True, no_wrap=False, font_family="monospace")
    ml_log_time = ft.Text("Last run: —", size=11, italic=True, color="#475569")

    # Chart Control
    chart_series = []
    price_chart = ftc.LineChart(
        data_series=chart_series,
        border=ft.Border(
            bottom=ft.BorderSide(1, "#334155"),
            right=ft.BorderSide(1, "#334155")
        ),
        interactive=True,
        expand=True,
        min_y=0,
        max_y=1,
        tooltip=ftc.LineChartTooltip(bgcolor="#020617", fit_inside_horizontally=True),
        right_axis=ftc.ChartAxis(label_size=80),
        bottom_axis=ftc.ChartAxis(label_size=60)
    )
    t_load_chart = t("loading_chart", lang)
    chart_container = ft.Container(
        content=ft.Text(t_load_chart, color="#94a3b8", size=16, weight=ft.FontWeight.BOLD),
        alignment=ft.alignment.Alignment(0, 0),
        border_radius=12,
        padding=20,
        expand=True
    )


    async def fetch_dashboard_data():
        if page.route != "/dashboard":
            return
        
        settings = dict(db.get_settings() or {})
        pair = settings.get("trading_pair", "BTCUSDT")
        timeframe = settings.get("timeframe", "1m")
        market_type = dict(settings).get("market_type", "SPOT") or "SPOT"
        trading_mode = dict(settings).get("trading_mode", "DEMO") or "DEMO"
        is_live = (trading_mode == "LIVE")

        if is_live:
            orders_card_title_text.value = "🔥 Активные ордера (LIVE Binance)" if lang == "ru" else "🔥 Active Live Orders (Binance)"
        else:
            orders_card_title_text.value = "🎮 Активные демо-ордера (DEMO)" if lang == "ru" else "🎮 Active Demo Orders (DEMO)"
        
        # Обновляем заголовки графиков и аналитики (мнемо-индикаторы)
        chart_title.value = f"График {pair} ({timeframe} • {market_type})" if lang == "ru" else f"Chart {pair} ({timeframe} • {market_type})"
        ml_strategy_title.value = f"{t_ai_strat} ({pair} • {timeframe} • {market_type})"
        
        # 1. Загрузка цен и активных ордеров для PnL и балансов
        active_orders = []
        current_price = 0.0
        try:
            active_orders = await asyncio.to_thread(db.get_active_orders)
            current_price = await asyncio.to_thread(trading_engine.fetch_current_price, pair, market_type)
            indicator_price.value = f"Price: {current_price:,.2f}"
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error loading price/orders on dashboard: {e}")

        # Загрузка живых позиций с биржи Binance для 100% точного Unrealized PnL
        live_positions_map = {}
        if is_live:
            try:
                live_pos_list = await asyncio.to_thread(trading_engine.fetch_binance_positions, market_type)
                if live_pos_list:
                    for lp in live_pos_list:
                        if lp.get("pair"):
                            live_positions_map[lp["pair"].upper()] = lp
                        if lp.get("id"):
                            live_positions_map[str(lp["id"]).upper()] = lp
            except Exception:
                pass

        # Рассчитаем нереализованный PNL только для исполненных АКТИВНЫХ ордеров (status == "ACTIVE")
        active_positions = [o for o in active_orders if str(o.get("status", "ACTIVE")).upper() == "ACTIVE"]
        unrealized_pnl = 0.0
        if active_positions:
            for o in active_positions:
                p_sym = o.get("pair", pair).upper()
                if is_live and p_sym in live_positions_map:
                    # 🎯 В LIVE режиме берём 100% точный Unrealized PnL напрямую с Binance API
                    unrealized_pnl += float(live_positions_map[p_sym].get("unrealized_pnl", 0.0))
                elif current_price > 0:
                    amount = float(o["amount"])
                    entry = float(o["entry_price"])
                    side = o["side"]
                    if side == "BUY":
                        unrealized_pnl += amount * (current_price - entry)
                    else:
                        unrealized_pnl += amount * (entry - current_price)

        # 3. Расчет сегодняшнего суточного PnL (автоматическое считывание с Binance в LIVE режиме)
        realized_pnl = 0.0
        try:
            if is_live:
                realized_pnl = await asyncio.to_thread(trading_engine.fetch_binance_today_pnl, market_type)
            else:
                tz_offset = getattr(page, "tz_offset", 180)
                realized_pnl = await asyncio.to_thread(db.get_today_pnl, trading_mode=trading_mode, tz_offset_min=tz_offset)
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error fetching today PNL: {e}")

        # 2. Обновление балансов и Equity (Баланс + плавающий PnL только по ACTIVE позициям)
        balance_val = 0.0
        try:
            if is_live:
                balance_card_title.value = "Реальный баланс (Binance API)"
                bal = await asyncio.to_thread(trading_engine.fetch_binance_balance, market_type)
                balance_val = float(bal) if bal is not None else 0.0
                display_bal = balance_val + unrealized_pnl
                balance_text.value = f"${display_bal:,.2f} USDT"
                collateral_text.value = "Live Account Equity (Binance)"
            else:
                balance_card_title.value = t("demo_balance", lang)
                raw_demo = settings.get("demo_balance")
                balance_val = float(raw_demo) if (raw_demo is not None and float(raw_demo) > 0) else 10000.0
                display_bal = balance_val + unrealized_pnl
                balance_text.value = f"${display_bal:,.2f} USDT"
                
                # Рассчитаем задействованное обеспечение только для реально открытых ордеров ACTIVE
                collateral_val = sum(float(o["size_usdt"]) for o in active_positions)
                collateral_text.value = f"{t('wallet_collateral', get_lang(page))}: ${collateral_val:,.2f} USDT"
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error fetching balances: {e}")

        # Суммируем реализованный PNL и нереализованный PNL текущих позиций
        total_pnl = realized_pnl + unrealized_pnl
        base_bal = display_bal if display_bal > 0 else (balance_val if balance_val > 0 else 100.0)
        pnl_pct = (total_pnl / base_bal) * 100.0

        pnl_text.value = f"${total_pnl:+.2f} ({pnl_pct:+.2f}%)"
        pnl_text.color = "#10b981" if total_pnl >= 0 else "#ef4444"

        # Загрузка точной статистики PnL за 7 дней и за 30 дней
        try:
            pnl_stats = db.get_pnl_stats(trading_mode="LIVE" if is_live else "DEMO")
            p7d = pnl_stats["pnl_7d"]
            p30d = pnl_stats["pnl_30d"]

            pnl_7d_val_text.value = f"${p7d:+.2f}"
            pnl_7d_val_text.color = "#10b981" if p7d >= 0 else "#ef4444"

            pnl_30d_val_text.value = f"${p30d:+.2f}"
            pnl_30d_val_text.color = "#10b981" if p30d >= 0 else "#ef4444"
        except Exception as ex_pnl_st:
            print(f"Error updating PnL stats widgets: {ex_pnl_st}")

        # Обновление мини-графика динамики эквити/депозита по дням
        try:
            eq_hist = db.get_daily_equity_history(trading_mode="LIVE" if is_live else "DEMO")
            if eq_hist:
                eq_pts = [ftc.LineChartDataPoint(0, 0.0)]
                for item in eq_hist:
                    eq_pts.append(ftc.LineChartDataPoint(item["idx"] + 1, item["cum_pnl"]))
                
                last_cum = eq_hist[-1]["cum_pnl"]
                line_color = "#10b981" if last_cum >= 0 else "#ef4444"
                fill_color = ft.Colors.with_opacity(0.12, line_color)
                
                equity_mini_chart.data_series = [
                    ftc.LineChartData(
                        points=eq_pts,
                        stroke_width=2.5,
                        color=line_color,
                        curved=True,
                        below_line_bgcolor=fill_color
                    )
                ]
                equity_mini_chart.update()
        except Exception as ex_eq:
            pass
    
        # 4. Отрисовка списка активных ордеров с плавными анимациями
        try:
            active_ids = {o["id"] for o in active_orders}
            
            # Анимация закрытия (удаления) ордеров
            removed_ids = []
            for order_id, order_info in list(rendered_orders.items()):
                if order_id not in active_ids:
                    # Ордер был закрыт, запускаем fade-out
                    order_info["control"].opacity = 0
                    order_info["control"].scale = 0.8
                    removed_ids.append(order_id)
            
            if removed_ids:
                page.update()
                await asyncio.sleep(0.3)  # Даем время отработать анимации закрытия
                for order_id in removed_ids:
                    if order_id in rendered_orders:
                        control_to_remove = rendered_orders[order_id]["control"]
                        if control_to_remove in active_orders_column.controls:
                            active_orders_column.controls.remove(control_to_remove)
                        del rendered_orders[order_id]
                page.update()

            # Убираем надпись "Нет активных ордеров", если появились ордера
            if active_orders:
                # Если в списке была заглушка-текст, очищаем ее
                if len(active_orders_column.controls) == 1 and isinstance(active_orders_column.controls[0], ft.Text):
                    active_orders_column.controls.clear()
            else:
                if not rendered_orders:
                    active_orders_column.controls.clear()
                    active_orders_column.controls.append(
                        ft.Text(t("no_active_orders", get_lang(page)), color="#94a3b8", italic=True)
                    )

            # Добавление новых ордеров и обновление существующих
            new_controls_added = False
            for o in active_orders:
                order_id = o["id"]
                amount = float(o["amount"])
                entry = float(o["entry_price"])
                side = o["side"]
                
                # Индивидуальный нереализованный PNL ордера (только для ACTIVE)
                order_status = str(o.get("status", "ACTIVE")).upper()
                unrealized = 0.0
                p_sym = o.get("pair", pair).upper()
                if order_status == "ACTIVE":
                    if is_live and p_sym in live_positions_map:
                        # 🎯 Берём точный живой Unrealized PnL напрямую с Binance API
                        unrealized = float(live_positions_map[p_sym].get("unrealized_pnl", 0.0))
                    elif current_price > 0:
                        if side == "BUY":
                            unrealized = amount * (current_price - entry)
                        else:
                            unrealized = amount * (entry - current_price)

                stake_val = float(o.get("size_usdt") or (entry * amount))

                is_active = (order_status == "ACTIVE")
                if is_active:
                    live_roi = (unrealized / stake_val * 100.0) if stake_val > 0 else 0.0
                    pnl_display_str = f"${unrealized:+.2f} ({live_roi:+.1f}%)"
                    pnl_color = "#10b981" if unrealized >= 0 else "#ef4444"
                else:
                    pnl_display_str = "$0.00 (0.0%)"
                    pnl_color = "#eab308"

                leverage_str = f" | Lev: {o['leverage']}x" if (dict(o).get("market_type", "SPOT") or "SPOT").upper() == "FUTURES" else ""
                
                # 1. Расчет потенциальной прибыли по Take Profit (с учетом плеча и ROI от маржи)
                if o.get("take_profit"):
                    tp_val = float(o["take_profit"])
                    tp_pnl = amount * (tp_val - entry) if side == "BUY" else amount * (entry - tp_val)
                    tp_str = f"TP: ${tp_val:.2f} ({tp_pnl:+.2f}$)"
                else:
                    tp_str = "TP: —"

                # 2. Расчет потенциального убытка / прибыли по Stop Loss (с учетом плеча и ROI от маржи)
                if o.get("stop_loss"):
                    sl_val = float(o["stop_loss"])
                    sl_pnl = amount * (sl_val - entry) if side == "BUY" else amount * (entry - sl_val)
                    sl_color = "#10b981" if sl_pnl >= 0 else "#f43f5e"
                    sl_str = f"SL: ${sl_val:.2f} ({sl_pnl:+.2f}$)"
                else:
                    sl_str = "SL: —"
                    sl_color = "#94a3b8"

                status_bg = "#0284c7" if is_active else "#eab308"

                # 🎯 Гарантированное считывание настоящих свечей именно пары данного ордера
                order_pair = o.get("pair", pair)
                order_tf = o.get("timeframe") or "1m"
                
                pair_klines = trading_engine.get_klines(order_pair, order_tf) if hasattr(trading_engine, "get_klines") else []
                if not pair_klines:
                    pair_klines = current_pair_data.get("klines", [])
                
                kline_slice = pair_klines[-25:] if len(pair_klines) >= 25 else pair_klines
                
                # 🎯 ВСЯ ЛОГИКА НА БЭКЕНДЕ: Забираем траекторию свечей строго за время жизни ордера от created_at!
                if hasattr(trading_engine, "get_active_order_chart_prices"):
                    raw_prices = trading_engine.get_active_order_chart_prices(
                        order_id, entry, current_price, unrealized, 
                        pair=order_pair, timeframe=order_tf, created_at=o.get("created_at")
                    )
                else:
                    raw_prices = [entry, current_price if current_price > 0 else entry]
                
                min_p = min(raw_prices)
                max_p = max(raw_prices)
                p_span = (max_p - min_p)
                if p_span < (entry * 0.0001):
                    p_span = entry * 0.002

                chart_pts = [ftc.LineChartDataPoint(i, raw_prices[i]) for i in range(len(raw_prices))]
                
                min_y_val = min_p - p_span * 0.02 if p_span > 0 else min_p * 0.999
                max_y_val = max_p + p_span * 0.02 if p_span > 0 else max_p * 1.001
                max_x_val = len(raw_prices) - 1

                fill_bg = ft.Colors.with_opacity(0.18, pnl_color)

                if order_id in rendered_orders:
                    # Обновляем тексты и выразительную кривую волн ордера
                    info = rendered_orders[order_id]
                    info["price_text"].value = f"${current_price:.2f}"
                    info["pnl_text"].value = pnl_display_str
                    info["pnl_text"].color = pnl_color
                    info["sl_text"].value = sl_str
                    info["sl_text"].color = sl_color
                    info["tp_text"].value = tp_str
                    
                    if "mini_chart" in info and chart_pts:
                        info["mini_chart"].min_x = 0
                        info["mini_chart"].max_x = max_x_val
                        info["mini_chart"].min_y = min_y_val
                        info["mini_chart"].max_y = max_y_val
                        info["mini_chart"].data_series = [
                            ftc.LineChartData(
                                points=chart_pts,
                                stroke_width=2.5,
                                color=pnl_color,
                                curved=True,
                                below_line_bgcolor=fill_bg
                            )
                        ]
                else:
                    # Создаем виджеты и волнистый график с точным min_x=0/max_x=max_x_val и min_y=min_y_val/max_y=max_y_val
                    price_text = ft.Text(f"${current_price:.2f}", size=11, color="#94a3b8")
                    sl_text = ft.Text(sl_str, size=11, color=sl_color)
                    tp_text = ft.Text(tp_str, size=11, color="#10b981")

                    order_pnl_text = ft.Text(pnl_display_str, weight=ft.FontWeight.BOLD, color=pnl_color, size=13)
                    
                    order_mini_chart = ftc.LineChart(
                        data_series=[
                            ftc.LineChartData(
                                points=chart_pts,
                                stroke_width=2.5,
                                color=pnl_color,
                                curved=True,
                                below_line_bgcolor=fill_bg
                            )
                        ],
                        interactive=False,
                        border=ft.Border.all(0, ft.Colors.TRANSPARENT),
                        min_x=0,
                        max_x=max_x_val,
                        min_y=min_y_val,
                        max_y=max_y_val,
                        left_axis=None,
                        bottom_axis=None,
                        top_axis=None,
                        right_axis=None,
                        horizontal_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
                        vertical_grid_lines=ftc.ChartGridLines(color=ft.Colors.TRANSPARENT),
                        height=42,
                        expand=True
                    )
                    
                    def make_close_handler(oid):
                        def handler(e):
                            threading.Thread(
                                target=lambda: trading_engine.liquidate_order_manually(oid),
                                daemon=True
                            ).start()
                        return handler

                    order_row = ft.Container(
                        content=ft.Row(
                            [
                                # Col 1: Asset Info
                                ft.Column([
                                    ft.Row([
                                        ft.Text(f"{o['pair']} ({order_tf})", weight=ft.FontWeight.BOLD, size=14, color="#f8fafc"),
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
                                ], spacing=4, width=145),
                                
                                # Col 2: Entry / Current
                                ft.Column([
                                    ft.Text("ENTRY / CURRENT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"${entry:.2f}", size=12, color="#f8fafc"),
                                    price_text
                                ], spacing=2, width=105),
                                
                                # Col 3: Stake details (ПЕРЕД СТОПАМИ)
                                ft.Column([
                                    ft.Text("STAKE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"${float(o['size_usdt']):.2f}", size=12, color="#f8fafc"),
                                    ft.Text(f"Lev: {o['leverage']}x" if o.get('leverage') else "Spot", size=11, color="#94a3b8")
                                ], spacing=2, width=80),

                                # Col 4: Targets (SL / TP с аккуратным выводом)
                                ft.Column([
                                    ft.Text("SL / TP (EST. PNL)", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    sl_text,
                                    tp_text
                                ], spacing=2, width=140),
                                
                                # Col 5: Чистый график кривой свечей без выпирающего текста
                                ft.Container(
                                    content=order_mini_chart,
                                    padding=ft.Padding.symmetric(horizontal=4, vertical=2),
                                    expand=True
                                ),
                                
                                # Col 6: Result & Action (Зароботок и кнопку закрытия аккуратно без наложений)
                                ft.Column([
                                    ft.Text("LIVE RESULT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    order_pnl_text,
                                    ft.Row([
                                        ft.Container(
                                            content=ft.Text(order_status, size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                            bgcolor=status_bg,
                                            padding=ft.Padding.symmetric(vertical=2, horizontal=5),
                                            border_radius=4
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.CANCEL_ROUNDED,
                                            icon_size=18,
                                            icon_color="#ef4444",
                                            tooltip="Закрыть позицию вручную",
                                            on_click=make_close_handler(order_id),
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
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
                        opacity=0,          # Стартовая прозрачность для анимации появления
                        scale=0.8,          # Стартовый масштаб для анимации появления
                        animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                        animate_scale=ft.Animation(300, ft.AnimationCurve.EASE_OUT_BACK)
                    )
                    
                    active_orders_column.controls.append(order_row)
                    rendered_orders[order_id] = {
                        "control": order_row,
                        "price_text": price_text,
                        "pnl_text": order_pnl_text,
                        "sl_text": sl_text,
                        "tp_text": tp_text,
                        "mini_chart": order_mini_chart
                    }
                    new_controls_added = True

            # Запускаем анимацию появления для новых ордеров и высылаем обновления контролов
            if new_controls_added:
                page.update()
                await asyncio.sleep(0.05)  # Небольшая пауза, чтобы Flet зарегистрировал начальное состояние
                for order_id, order_info in rendered_orders.items():
                    order_info["control"].opacity = 1
                    order_info["control"].scale = 1.0
                page.update()
            elif rendered_orders:
                page.update()
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error updating active orders layout: {e}")

        # 4. История ордеров
        try:
            history_orders = await asyncio.to_thread(db.get_order_history)
            order_history_column.controls.clear()
            if not history_orders:
                t_no_ord_hist = t("no_ord_hist", lang)
                order_history_column.controls.append(ft.Text(t_no_ord_hist, color="#94a3b8", italic=True))
            else:
                for o in history_orders[:10]:
                    pnl = float(o.get('pnl', 0) or 0)
                    pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
                    order_history_column.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Text(f"{o['pair']} {o['side']} ({o['status']})", size=13, weight=ft.FontWeight.BOLD),
                                ft.Text(f"PnL: {pnl:+.2f}$", size=13, color=pnl_color, weight=ft.FontWeight.BOLD)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            padding=10, border_radius=8,
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.05, "#ffffff"))
                        )
                    )
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error fetching order history: {e}")

        # 5. История логов нейросети
        tz_offset = getattr(page, "tz_offset", None) or db.get_host_tz_offset_min()
        user_tz = timezone(timedelta(minutes=tz_offset))

        def to_client_local_str(ts_str):
            if not ts_str:
                return "—"
            try:
                clean_ts = str(ts_str).split(".")[0].replace("T", " ")
                utc_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                return utc_dt.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(ts_str)

        try:
            analysis_logs = await asyncio.to_thread(db.get_all_analysis_logs)
            logs_history_column.controls.clear()
            if not analysis_logs:
                t_no_log_hist = t("no_log_hist", lang)
                logs_history_column.controls.append(ft.Text(t_no_log_hist, color="#94a3b8", italic=True))
            else:
                import json as _json
                for l in analysis_logs[-10:][::-1]:
                    ts = to_client_local_str(l.get('created_at', ''))
                    pair_lbl = l.get('pair', '')
                    try:
                        s3 = _json.loads(l.get('stage3_output', '{}'))
                        action = s3.get('action', 'HOLD')
                        prob = s3.get('probability', 0)
                        price = s3.get('price', 0)
                    except Exception:
                        action, prob, price = 'HOLD', 0, 0
                    action_color = "#10b981" if action == "BUY" else ("#ef4444" if action == "SELL" else "#94a3b8")
                    logs_history_column.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Container(
                                    ft.Text(action, size=11, color="#ffffff", weight=ft.FontWeight.BOLD),
                                    bgcolor=action_color, border_radius=4, padding=ft.Padding.only(left=6, top=3, right=6, bottom=3)
                                ),
                                ft.Column([
                                    ft.Text(f"{pair_lbl}  ${price:,.2f}  ({prob*100:.1f}%)", size=12, color="#e2e8f0", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{ts}", size=10, color="#64748b"),
                                ], spacing=1, expand=True)
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.Padding.only(left=10, top=8, right=10, bottom=8), border_radius=8,
                            bgcolor=ft.Colors.with_opacity(0.04, "#ffffff"),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.08, "#ffffff"))
                        )
                    )
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error fetching logs history: {e}")

            
        # 4. Технические Индикаторы
        try:
            klines = await asyncio.to_thread(trading_engine.fetch_binance_klines, pair, timeframe, limit=100, market_type=market_type)
            from indicators import get_latest_indicators
            latest_ti = get_latest_indicators(klines)
            if latest_ti and "error" not in latest_ti:
                indicator_rsi.value = f"RSI: {latest_ti.get('rsi', 0.0):.2f}"
                indicator_atr.value = f"ATR%: {latest_ti.get('atr_pct', 0.0):.4f}%"
                indicator_macd.value = f"MACD: {latest_ti.get('macd', 'N/A')}"
                indicator_bb.value = f"Bollinger Bands: {latest_ti.get('bb_signal', 'N/A')}"
        except Exception as ex:
            pass

        # 4.5 Стакан цен и Крупные плотности
        try:
            step_val = float(orderbook_group_step) if 'orderbook_group_step' in locals() else 0.01
            ob_data = await asyncio.to_thread(trading_engine.get_live_orderbook_details, pair, market_type, step_val)
            bids = ob_data.get("bids_grouped", ob_data.get("bids", []))[:12]
            asks = ob_data.get("asks_grouped", ob_data.get("asks", []))[:12]
            max_bid_p = ob_data.get("max_bid_price", 0.0)
            max_ask_p = ob_data.get("max_ask_price", 0.0)
            max_bid_v = ob_data.get("max_bid_vol", 1.0)
            max_ask_v = ob_data.get("max_ask_vol", 1.0)

            top_bid_v = max([v for _, v in bids], default=1.0)
            top_ask_v = max([v for _, v in asks], default=1.0)
            max_bid_tuple = max(bids, key=lambda x: x[1]) if bids else (0.0, 0.0)
            max_ask_tuple = max(asks, key=lambda x: x[1]) if asks else (0.0, 0.0)

            bid_rows = []
            for p_val, v_val in bids:
                is_w = (p_val == max_bid_tuple[0] and v_val == max_bid_tuple[1] and v_val > 0)
                fill_ratio = float(min(1.0, max(0.05, v_val / (top_bid_v + 1e-9))))
                w_tag = " 🏆 СТЕНКА" if is_w else ""
                # Чем больше объем, тем более насыщенный зеленый фон плашки
                bg_op = 0.38 if is_w else (0.05 + 0.22 * fill_ratio)
                
                bid_rows.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"${p_val:,.2f}{w_tag}", size=11, weight=ft.FontWeight.BOLD if is_w else ft.FontWeight.NORMAL, color="#34d399"),
                            ft.Text(f"{v_val:.3f}", size=11, color="#e2e8f0", weight=ft.FontWeight.BOLD if is_w else ft.FontWeight.NORMAL)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor=ft.Colors.with_opacity(bg_op, "#10b981"),
                        border=ft.Border.all(2, "#34d399") if is_w else ft.Border.all(1, ft.Colors.with_opacity(0.08, "#10b981")),
                        padding=ft.Padding(8, 5, 8, 5),
                        border_radius=6
                    )
                )
            orderbook_bids_col.controls = bid_rows

            ask_rows = []
            for p_val, v_val in asks:
                is_w = (p_val == max_ask_tuple[0] and v_val == max_ask_tuple[1] and v_val > 0)
                fill_ratio = float(min(1.0, max(0.05, v_val / (top_ask_v + 1e-9))))
                w_tag = " 🏆 СТЕНКА" if is_w else ""
                bg_op = 0.38 if is_w else (0.05 + 0.22 * fill_ratio)
                
                ask_rows.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"${p_val:,.2f}{w_tag}", size=11, weight=ft.FontWeight.BOLD if is_w else ft.FontWeight.NORMAL, color="#f87171"),
                            ft.Text(f"{v_val:.3f}", size=11, color="#e2e8f0", weight=ft.FontWeight.BOLD if is_w else ft.FontWeight.NORMAL)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor=ft.Colors.with_opacity(bg_op, "#ef4444"),
                        border=ft.Border.all(2, "#f87171") if is_w else ft.Border.all(1, ft.Colors.with_opacity(0.08, "#ef4444")),
                        padding=ft.Padding(8, 5, 8, 5),
                        border_radius=6
                    )
                )
            orderbook_asks_col.controls = ask_rows

            orderbook_wall_badge.value = f"🟢 Стенка Bids: ${max_bid_tuple[0]:,.2f} ({max_bid_tuple[1]:.2f})  |  🔴 Стенка Asks: ${max_ask_tuple[0]:,.2f} ({max_ask_tuple[1]:.2f})"
        except Exception as ob_err:
            print(f"[ERROR] Orderbook render error: {ob_err}")

        # 4.8 Карта Ликвидаций фьючерсов
        try:
            liq_data = await asyncio.to_thread(trading_engine.get_live_liquidation_map_details, pair, market_type)
            shorts = liq_data.get("short_levels", [])
            longs = liq_data.get("long_levels", [])
            max_s_price = liq_data.get("max_short_price", 0.0)
            max_s_vol = liq_data.get("max_short_vol", 1.0)
            max_l_price = liq_data.get("max_long_price", 0.0)
            max_l_vol = liq_data.get("max_long_vol", 1.0)

            top_short_v = max([v for _, v, _ in shorts], default=1.0)
            top_long_v = max([v for _, v, _ in longs], default=1.0)

            s_rows = []
            for p_val, v_val, lev_tag in shorts:
                is_m = (p_val == max_s_price)
                fill_ratio = float(min(1.0, max(0.05, v_val / (top_short_v + 1e-9))))
                m_tag = f" 🎯 [{lev_tag}]" if is_m else f" [{lev_tag}]"
                bg_op = 0.35 if is_m else (0.05 + 0.22 * fill_ratio)
                
                s_rows.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"${p_val:,.2f}{m_tag}", size=11, weight=ft.FontWeight.BOLD if is_m else ft.FontWeight.NORMAL, color="#34d399"),
                            ft.Text(f"${v_val:,.0f}", size=11, color="#e2e8f0", weight=ft.FontWeight.BOLD if is_m else ft.FontWeight.NORMAL)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor=ft.Colors.with_opacity(bg_op, "#10b981"),
                        border=ft.Border.all(1.5, "#10b981") if is_m else ft.Border.all(1, ft.Colors.with_opacity(0.08, "#10b981")),
                        padding=ft.Padding(8, 5, 8, 5),
                        border_radius=6
                    )
                )
            liq_map_shorts_col.controls = s_rows

            l_rows = []
            for p_val, v_val, lev_tag in longs:
                is_m = (p_val == max_l_price)
                fill_ratio = float(min(1.0, max(0.05, v_val / (top_long_v + 1e-9))))
                m_tag = f" 🎯 [{lev_tag}]" if is_m else f" [{lev_tag}]"
                bg_op = 0.35 if is_m else (0.05 + 0.22 * fill_ratio)
                
                l_rows.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"${p_val:,.2f}{m_tag}", size=11, weight=ft.FontWeight.BOLD if is_m else ft.FontWeight.NORMAL, color="#f87171"),
                            ft.Text(f"${v_val:,.0f}", size=11, color="#e2e8f0", weight=ft.FontWeight.BOLD if is_m else ft.FontWeight.NORMAL)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor=ft.Colors.with_opacity(bg_op, "#ef4444"),
                        border=ft.Border.all(1.5, "#ef4444") if is_m else ft.Border.all(1, ft.Colors.with_opacity(0.08, "#ef4444")),
                        padding=ft.Padding(8, 5, 8, 5),
                        border_radius=6
                    )
                )
            liq_map_longs_col.controls = l_rows

            main_mag = f"🟢 Магнит Short Liqs: ${max_s_price:,.2f} (${max_s_vol:,.0f})" if max_s_vol >= max_l_vol else f"🔴 Магнит Long Liqs: ${max_l_price:,.2f} (${max_l_vol:,.0f})"
            liq_map_magnet_badge.value = f"🎯 {main_mag}"
        except Exception as liq_err:
            print(f"[ERROR] LiqMap render error: {liq_err}")

        # 5. Логи ИИ и динамический живой виджет аналитики ИИ (~3 раза/сек)
        try:
            try:
                now_dt = datetime.now(user_tz)
                offset_sec = now_dt.utcoffset().total_seconds()
                offset_h = int(offset_sec / 3600)
                tz_str = f"UTC{offset_h:+d}"
                curr_clock_str = now_dt.strftime("%H:%M:%S")
                ai_live_clock_text.value = f"{curr_clock_str} ({tz_str})"
            except Exception:
                pass

            latest_log = trading_engine.LATEST_LIVE_SIGNAL
            source_desc = "Live online prediction"

            raw_thresh = settings.get("min_probability_threshold")
            curr_thresh = float(raw_thresh) if raw_thresh is not None else 0.65
            thresh_pct = curr_thresh * 100.0
            
            if latest_log:
                ml_logs_stage1.value = latest_log.get("stage1_output") or "—"
                ml_logs_stage2.value = latest_log.get("stage2_output") or "—"
                try:
                    import json as _json
                    s3 = _json.loads(latest_log.get("stage3_output") or "{}")
                    # Читаем живые поля инференса напрямую (обновляются 3 раза/сек)
                    prob = float(latest_log.get("live_probability", float(s3.get("probability", 0.0))))
                    action = latest_log.get("live_action", s3.get("action", "HOLD"))
                    price = float(s3.get("price", 0.0))
                    order_type = s3.get("order_type", "")

                    # Обновление средних аналитик (Тренд / ATR)
                    stage1_text = latest_log.get("stage1_output") or ""
                    trend_dir = latest_log.get("live_trend_direction", s3.get("trend_direction", "UP"))
                    is_vol_blocked = latest_log.get("live_vol_blocked", s3.get("vol_blocked", "BLOCKED" in stage1_text))

                    trend_str = "UP 🟢" if trend_dir == "UP" else "DOWN 🔴"
                    vol_str = "BLOCKED ⚠️" if is_vol_blocked else "OK 🟢"
                    ai_live_trend_text.value = f"📊 Тренд: {trend_str}    ⚡ ATR: {vol_str}"

                    vol_blocked = ("BLOCKED" in (latest_log.get("stage1_output") or ""))
                    if not vol_blocked and prob > curr_thresh:
                        if action not in ["BUY", "SELL"]:
                            action = "BUY"
                        reason = "Сигнал на покупку по тренду!" if action == "BUY" else "Сигнал на продажу по тренду!"
                        reason2 = f"Вероятность {prob:.4f} > {curr_thresh:.2f}."
                    elif not vol_blocked:
                        action = "HOLD"
                        reason = "Вероятность классификатора:"
                        reason2 = f"{prob:.4f} <= {curr_thresh:.2f}."
                    else:
                        reason = s3.get("reason", "")
                        reason2 = s3.get("reason2", "")

                    action_icon = "🟢" if action == "BUY" else ("🔴" if action == "SELL" else "⏸")

                    # Обновление живого виджета ИИ (приоритет — сделать до ml_logs_stage3)
                    prob_pct = prob * 100.0
                    if action == "BUY":
                        act_label = "🟢 ПОКУПКА"
                        act_color = "#10b981"
                    elif action == "SELL":
                        act_label = "🔴 ПРОДАЖА"
                        act_color = "#ef4444"
                    else:
                        act_label = "⏸ НЕЙТРАЛЬНО"
                        act_color = "#94a3b8"

                    ai_live_action_text.value = act_label
                    ai_live_action_text.color = act_color
                    ai_live_action_badge.bgcolor = ft.Colors.with_opacity(0.15, act_color)
                    ai_live_action_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.35, act_color))

                    ai_live_confidence_text.value = f"Уверенность: {prob_pct:.2f}%"
                    ai_live_threshold_text.value = f"Порог: {thresh_pct:.1f}%"
                    ai_live_progress_bar.value = min(1.0, max(0.0, prob))
                    ai_live_progress_bar.color = act_color

                    # Логи (второстепенные — обновляем отдельно)
                    try:
                        t_act = t("action_lbl", lang)
                        t_ord = t("order_lbl", lang)
                        t_prc = t("price_lbl", lang)
                        t_prob = t("probability_lbl", lang)
                        ml_logs_stage3.value = (
                            f"{action_icon}  {t_act}{action}  |  {t_ord}{order_type}\n"
                            f"💰  {t_prc}${price:,.4f}\n"
                            f"📊  {t_prob}{prob*100:.2f}%\n"
                            f"📝  {reason} {reason2}"
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
                
                ts = to_client_local_str(latest_log.get("created_at", "—"))
                ml_log_time.value = f"🕐  Last run: {ts} ({source_desc})"
                ml_strategy_title.value = f"{t_ai_strat} ({pair} • {timeframe} • {market_type})"
            else:
                # Сигнала ещё нет — определяем точную причину
                is_tr_active = scalping_ensemble.training_status.get("active", False)
                tr_msg = scalping_ensemble.training_status.get("msg", "")
                is_warmup = getattr(trading_engine, "WARMUP_IN_PROGRESS", False)

                try:
                    now_dt = datetime.now(user_tz)
                    offset_sec = now_dt.utcoffset().total_seconds()
                    offset_h = int(offset_sec / 3600)
                    tz_str = f"UTC{offset_h:+d}"
                    curr_clock_str = now_dt.strftime("%H:%M:%S")
                    ai_live_clock_text.value = f"{curr_clock_str} ({tz_str})"
                except Exception:
                    pass
                
                if is_tr_active:
                    ml_logs_stage1.value = "⏳ Идёт автоматическое обучение нейросети на истории рынка...\nПожалуйста, подождите." if lang == "ru" else "⏳ AI model training on market history in progress...\nPlease wait."
                    ml_logs_stage2.value = f"⚙️ {tr_msg or 'Сбор данных и обучение...'}"
                    ml_logs_stage3.value = "🤖 Нейросеть адаптируется под рыночный тренд. После обучения сигнал появится автоматически." if lang == "ru" else "🤖 AI is adapting to market. Signal will appear automatically after training."
                    ml_log_time.value = "🕐 Статус: Обучение нейросети..." if lang == "ru" else "🕐 Status: Training AI..."
                    
                    ai_live_action_text.value = "⚙️ ОБУЧЕНИЕ..."
                    ai_live_action_text.color = "#f59e0b"
                    ai_live_confidence_text.value = "Уверенность: —"
                    ai_live_threshold_text.value = f"Порог: {thresh_pct:.1f}%"
                elif is_warmup:
                    ml_logs_stage1.value = "🔄 Выполняется первичный расчёт сигнала нейросети..." if lang == "ru" else "🔄 Running initial AI signal calculation..."
                    ml_logs_stage2.value = "⚙️ Загрузка свечей и применение индикаторов..." if lang == "ru" else "⚙️ Loading candles and applying indicators..."
                    ml_logs_stage3.value = "🤖 Первый сигнал появится через несколько секунд." if lang == "ru" else "🤖 First signal will appear in a few seconds."
                    ml_log_time.value = "🕐 Статус: Первичный расчёт..." if lang == "ru" else "🕐 Status: Initial calculation..."

                    ai_live_action_text.value = "🔄 РАСЧЁТ..."
                    ai_live_action_text.color = "#38bdf8"
                    ai_live_confidence_text.value = "Уверенность: —"
                    ai_live_threshold_text.value = f"Порог: {thresh_pct:.1f}%"
                else:
                    ml_logs_stage1.value = "✅ Нейросеть загружена. Ожидание первого сигнала от торгового цикла..." if lang == "ru" else "✅ AI loaded. Waiting for first signal from trading cycle..."
                    ml_logs_stage2.value = "⚙️ Фоновый торговый цикл анализирует рынок..." if lang == "ru" else "⚙️ Background trading cycle is analyzing the market..."
                    ml_logs_stage3.value = "🤖 Сигнал обновляется каждые ~0.3 секунды автоматически." if lang == "ru" else "🤖 Signal updates every ~0.3s automatically."
                    ml_log_time.value = "🕐 Статус: Анализ рынка..." if lang == "ru" else "🕐 Status: Analyzing market..."

                    ai_live_action_text.value = "⏳ АНАЛИЗ..."
                    ai_live_action_text.color = "#0284c7"
                    ai_live_confidence_text.value = "Уверенность: —"
                    ai_live_threshold_text.value = f"Порог: {thresh_pct:.1f}%"
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            print(f"Error reading latest AI log: {e}")

        
        # 6. Отрисовка графика (с поддержкой зума и истории)
        try:
            fetch_limit = max(100, SAVED_CHART_LIMIT + SAVED_CHART_OFFSET + 20)
            raw_klines = await asyncio.to_thread(trading_engine.fetch_binance_klines, pair, timeframe, limit=fetch_limit, market_type=market_type)
            chart_klines = []
            if raw_klines:
                cached_raw_klines = raw_klines
                if SAVED_CHART_OFFSET > 0 and len(raw_klines) > SAVED_CHART_OFFSET:
                    chart_klines = raw_klines[:-SAVED_CHART_OFFSET][-SAVED_CHART_LIMIT:]
                else:
                    chart_klines = raw_klines[-SAVED_CHART_LIMIT:]

            if chart_klines:
                closes = [float(k[4]) for k in chart_klines]
                if current_price > 0 and closes and SAVED_CHART_OFFSET == 0:
                    closes[-1] = current_price
                opens = [float(k[1]) for k in chart_klines]
                times = [datetime.fromtimestamp(k[0]/1000).strftime("%H:%M") for k in chart_klines]
            
                y_points = list(closes)
                if current_price > 0 and SAVED_CHART_OFFSET == 0:
                    y_points.append(current_price)

                min_c = min(y_points)
                max_c = max(y_points)
                spread = max_c - min_c
            
                # 70% заполнения графика: padding = spread * 0.3 / 0.7 ~= 0.428 (пополам = 0.214)
                padding_y = spread * 0.25 if spread > 0 else min_c * 0.05
                min_y_val = min_c - padding_y
                max_y_val = max_c + padding_y
            
                # Основная серия цены
                price_points = [ftc.LineChartDataPoint(i, closes[i]) for i in range(len(closes))]
                price_series = ftc.LineChartData(
                    points=price_points,
                    stroke_width=3,
                    color="#0284c7",
                    curved=True,
                    below_line_bgcolor=ft.Colors.with_opacity(0.15, "#0284c7")
                )
            
                series_list = [price_series]
            
                # Горизонтальные линии и ТОЧКА АКТИВАЦИИ для активных и отложенных ордеров
                max_chart_x = len(closes) + int(len(closes) * 0.33)
                for o in active_orders:
                    entry = float(o["entry_price"])
                    side = str(o.get("side", "BUY")).upper()
                    order_status = str(o.get("status", "ACTIVE")).upper()
                    is_active_pos = (order_status == "ACTIVE")

                    marker_color = "#10b981" if side == "BUY" else "#ef4444"

                    if is_active_pos:
                        # Находим X-координату точки активации на графике (индекс свечи по времени активации)
                        act_x_index = 0
                        try:
                            c_at = str(o.get("created_at", ""))
                            if c_at:
                                act_dt = datetime.strptime(c_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                                act_ts = act_dt.timestamp()
                                for idx, k in enumerate(chart_klines):
                                    k_ts = k[0] / 1000
                                    if k_ts <= act_ts < k_ts + 60:
                                        act_x_index = idx
                                        break
                                    elif act_ts >= k_ts + 60 and idx == len(chart_klines) - 1:
                                        act_x_index = idx
                        except Exception:
                            act_x_index = 0

                        # 1. Линия входа по всей ширине графика (от 0 до max_chart_x)
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(0, entry), ftc.LineChartDataPoint(max_chart_x, entry)],
                                stroke_width=1.5,
                                color="#38bdf8",
                                dash_pattern=[5, 5]
                            )
                        )

                        # 2. ТОЧКА АКТИВАЦИИ (Яркий кружок на месте входа при сработавшем ордере ACTIVE)
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(act_x_index, entry)],
                                stroke_width=0,
                                color=marker_color,
                                point=ftc.ChartCirclePoint(radius=6, color=marker_color, stroke_width=2, stroke_color="#ffffff")
                            )
                        )

                        if o.get("take_profit"):
                            tp = float(o["take_profit"])
                            series_list.append(
                                ftc.LineChartData(
                                    points=[ftc.LineChartDataPoint(0, tp), ftc.LineChartDataPoint(max_chart_x, tp)],
                                    stroke_width=1,
                                    color="#10b981",
                                    dash_pattern=[3, 3]
                                )
                            )
                        
                        if o.get("stop_loss"):
                            sl = float(o["stop_loss"])
                            series_list.append(
                                ftc.LineChartData(
                                    points=[ftc.LineChartDataPoint(0, sl), ftc.LineChartDataPoint(max_chart_x, sl)],
                                    stroke_width=1,
                                    color="#ef4444",
                                    dash_pattern=[3, 3]
                                )
                            )
                    else:
                        # PENDING: Показываем только жёлтую пунктирную линию уровня отложенного ордера (без кружка и верт. линии)
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(0, entry), ftc.LineChartDataPoint(max_chart_x, entry)],
                                stroke_width=1.5,
                                color="#eab308",
                                dash_pattern=[4, 4]
                            )
                        )
            
                # Отступ справа в 8 пунктов только в LIVE-режиме (когда SAVED_CHART_OFFSET == 0)
                right_padding_x = 8 if SAVED_CHART_OFFSET == 0 else 0
                max_x_val = len(closes) - 1 + right_padding_x
                price_chart.max_x = max_x_val
                
                # Линия текущей цены (белая пунктирная) - протягиваем через весь экран и отступ
                current_p = current_price if current_price > 0 else closes[-1]
                series_list.append(
                    ftc.LineChartData(
                        points=[ftc.LineChartDataPoint(0, current_p), ftc.LineChartDataPoint(max_x_val, current_p)],
                        stroke_width=1.5,
                        color="#f8fafc",
                        dash_pattern=[4, 4]
                    )
                )
            
                # Обновление осей
                price_chart.data_series = series_list
                
                # Вычисляем красивый шаг для шкалы Y
                import math
                if spread == 0: spread = min_c * 0.01
                mag = 10 ** math.floor(math.log10(spread))
                ratio = spread / mag
                if ratio < 2:
                    step_y = mag / 5
                elif ratio < 5:
                    step_y = mag / 2
                else:
                    step_y = mag
                
                # Округляем min_y и max_y до точных кратных step_y
                min_y_val = math.floor((min_c - spread * 0.1) / step_y) * step_y
                max_y_val = math.ceil((max_c + spread * 0.1) / step_y) * step_y
                
                price_chart.min_y = min_y_val
                price_chart.max_y = max_y_val
                
                # Правая ось с нормальными числами, круглым шагом и дефисом (как пункт шкалы)
                y_labels = []
                val = min_y_val
                while val <= max_y_val + (step_y / 10):
                    if val < 1.0:
                        txt = f"- {val:,.4f}"
                    elif val < 10.0:
                        txt = f"- {val:,.3f}"
                    elif val < 1000.0:
                        txt = f"- {val:,.2f}"
                    else:
                        txt = f"- {val:,.0f}" if step_y == int(step_y) else f"- {val:,.2f}"
                    y_labels.append(
                        ftc.ChartAxisLabel(value=val, label=ft.Text(txt, size=11, color="#94a3b8", weight=ft.FontWeight.W_500))
                    )
                    val += step_y

                price_chart.left_axis = None
                price_chart.right_axis = ftc.ChartAxis(
                    labels=y_labels,
                    label_size=70,
                    label_spacing=step_y
                )
                
                price_chart.bottom_axis = ftc.ChartAxis(
                    labels=[
                        ftc.ChartAxisLabel(value=i, label=ft.Text(times[i], size=9, color="#64748b"))
                        for i in range(0, len(times), 10)
                    ],
                    label_size=30
                )
            
                # Расчет вертикального положения метки
                percent = (current_p - min_y_val) / (max_y_val - min_y_val) if max_y_val > min_y_val else 0.5
                y_align = 0.8 - (1.8 * percent)
                y_align = max(-1.0, min(1.0, y_align))
                
                is_green = closes[-1] >= opens[-1]
                tag_bg = "#10b981" if is_green else "#ef4444"
                
                # Если в контейнере текст, заменяем его на Stack с графиком и меткой текущей цены
                if current_p < 1.0:
                    price_str = f"{current_p:,.4f}"
                elif current_p < 10.0:
                    price_str = f"{current_p:,.3f}"
                elif current_p < 1000.0:
                    price_str = f"{current_p:,.2f}"
                else:
                    price_str = f"{current_p:,.0f}" if step_y == int(step_y) else f"{current_p:,.2f}"
                if not isinstance(chart_container.content, ft.Stack):
                    price_tag = ft.Container(
                        content=ft.Text(price_str, color="#ffffff", weight=ft.FontWeight.BOLD, size=11),
                        bgcolor=tag_bg,
                        padding=ft.padding.Padding(left=6, top=3, right=6, bottom=3),
                        border_radius=4,
                    )
                    price_tag_wrapper = ft.Container(
                        content=price_tag,
                        alignment=ft.alignment.Alignment(0.99, y_align),
                        left=0, right=0, top=0, bottom=0
                    )
                    chart_container.content = ft.Stack(
                        controls=[
                            price_chart,
                            price_tag_wrapper
                        ],
                        expand=True
                    )
                else:
                    tag_wrapper = chart_container.content.controls[1]
                    tag_wrapper.alignment = ft.alignment.Alignment(0.99, y_align)
                    tag = tag_wrapper.content
                    tag.bgcolor = tag_bg
                    tag.content.value = price_str
            else:
                chart_container.content = ft.Text("Ошибка получения свечей с Binance", color="#ef4444", size=14)
        except Exception as e:
            if is_destroyed_session_error(e):
                raise e
            chart_container.content = ft.Text(f"Ошибка загрузки графика: {str(e)}", color="#ef4444", size=12)

        try:
            page.update()
        except Exception as e:
            err = str(e)
            if "destroyed session" not in err.lower() and "session closed" not in err.lower():
                raise e



    async def dashboard_refresher():
        import asyncio

        # Начальная загрузка сразу при открытии
        try:
            await fetch_dashboard_data()
        except Exception as e:
            print(f"Initial dashboard fetch error: {e}")

        while True:
            await asyncio.sleep(0.4)

            # Пропускаем если не на дашборде, но не выходим
            if page.route != "/dashboard":
                continue

            try:
                await fetch_dashboard_data()
            except Exception as e:
                if is_destroyed_session_error(e):
                    break  # Сессия завершена — выходим
                else:
                    print(f"Dashboard refresh error: {e}")
    
    page.run_task(dashboard_refresher)


    settings = dict(db.get_settings() or {})

    # Обновление состояния кнопки старта/останова бота
    is_enabled = settings.get("bot_enabled", 0) == 1
    init_text = t("stop_bot", lang) if is_enabled else t("start_bot", lang)
    print(f"[DEBUG] init_button: is_enabled={is_enabled}, lang={lang}, init_text={init_text}")
    bot_toggle_btn_text.value = init_text
    bot_toggle_btn.bgcolor = "#ef4444" if is_enabled else "#0284c7"

    bot_status_desc.value = t("bot_active", lang, pair=settings.get("trading_pair", "N/A")) if is_enabled else t("bot_stopped", lang)
    bot_status_desc.color = "#10b981" if is_enabled else "#94a3b8"

    def toggle_bot_click(e):
        # Read fresh value from DB to be absolutely sure
        fresh_settings = dict(db.get_settings() or {})
        cur_enabled = fresh_settings.get("bot_enabled", 0)
        new_val = 0 if cur_enabled == 1 else 1
        db.update_settings("bot_enabled", new_val)
        
        pair = (fresh_settings.get("trading_pair", "BTCUSDT") or "BTCUSDT").upper()
        tf = fresh_settings.get("timeframe", "1m") or "1m"

        # Invalidate cache so next page entries are fresh
        
        # Invalidate cache so next page entries are fresh
        if hasattr(page, "_views_cache"):
            for k in list(page._views_cache.keys()):
                if k[0] in ["/dashboard", "/settings", "/history"]:
                    page._views_cache.pop(k, None)
                    
        # Update local dict reference
        settings["bot_enabled"] = new_val
        
        # Reactive UI update
        is_active = (new_val == 1)
        text_val = t("stop_bot", lang) if is_active else t("start_bot", lang)
        print(f"[DEBUG] toggle_bot_click: is_active={is_active}, lang={lang}, text_val={text_val}")
        bot_toggle_btn_text.value = text_val
        bot_toggle_btn.bgcolor = "#ef4444" if is_active else "#0284c7"
        bot_status_desc.value = t("bot_active", lang, pair=fresh_settings.get("trading_pair", "N/A")) if is_active else t("bot_stopped", lang)
        bot_status_desc.color = "#10b981" if is_active else "#94a3b8"
        bot_toggle_btn_text.update()
        bot_toggle_btn.update()
        bot_status_desc.update()
        page.update()
    
    bot_toggle_btn.on_click = toggle_bot_click


    # Секция быстрых действий
    def trigger_analysis(e):
        e.control.disabled = True
        page.update()
        # Запуск в потоке, чтобы не вешать UI
        threading.Thread(
            target=lambda: trading_engine.evaluate_market_signal(persist_log=True, place_order=True),
            daemon=True
        ).start()
    
    video_stream_url = os.environ.get("VIDEO_STREAM_URL", "http://127.0.0.1:8554/stream.mjpeg")

    cast_devices_col = ft.Column(spacing=8, scroll=ft.ScrollMode.ADAPTIVE)
    cast_status_text = ft.Text("Поиск поддерживаемых Smart TV / Android TV устройств...", size=12, color="#94a3b8")

    def close_cast_dialog(e):
        try:
            page.close(cast_modal)
        except Exception:
            cast_modal.open = False
            page.update()

    def select_cast_device(dev):
        dev_name = dev["name"]
        dev_ip = dev["ip"]
        cast_status_text.value = f"⏳ Подключение к {dev_name}..."
        page.update()
        
        success, msg = cast_manager.cast_video_to_device(dev_ip, video_stream_url)
        if success:
            cast_status_text.value = f"✅ Видеопоток успешно отправлен на {dev_name}!"
        else:
            cast_status_text.value = f"ℹ️ Ошибка подключения: {msg}. Откройте ссылку {video_stream_url} на ТВ."
        page.update()

    cast_modal = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.CAST_CONNECTED_ROUNDED, color="#a78bfa", size=24),
            ft.Text("Выберите устройство для трансляции", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                cast_status_text,
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.1, "#ffffff")),
                cast_devices_col
            ], spacing=10),
            width=500,
            height=300
        ),
        actions=[
            ft.TextButton("Закрыть", on_click=close_cast_dialog)
        ],
        actions_alignment=ft.MainAxisAlignment.END
    )

    def start_device_discovery(e=None):
        cast_devices_col.controls = [ft.ProgressRing(width=24, height=24, color="#a78bfa")]
        cast_status_text.value = "🔍 Сканирование локальной Wi-Fi сети..."
        try:
            page.open(cast_modal)
        except Exception:
            page.dialog = cast_modal
            cast_modal.open = True
            page.update()

        def _bg_scan():
            devices = cast_manager.discover_network_devices(timeout=1.5)
            dev_items = []
            for dev in devices:
                d_name = dev["name"]
                dev_items.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.TV_ROUNDED, color="#a78bfa", size=20),
                            ft.Text(d_name, size=13, weight=ft.FontWeight.BOLD, color="#f8fafc", expand=True),
                            ft.ElevatedButton(
                                "Транслировать",
                                icon=ft.Icons.PLAY_ARROW_ROUNDED,
                                bgcolor="#0284c7",
                                color="#ffffff",
                                on_click=lambda ex, d=dev: select_cast_device(d)
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor=ft.Colors.with_opacity(0.12, "#30363d"),
                        padding=10,
                        border_radius=8
                    )
                )
            cast_devices_col.controls = dev_items
            cast_status_text.value = f"Найдено устройств: {len(devices)}. Выберите устройство для 1-click трансляции:"
            try:
                page.update()
            except Exception:
                pass

        threading.Thread(target=_bg_scan, daemon=True).start()

    cast_btn = ft.ElevatedButton(
        "📡 Транслировать на TV",
        icon=ft.Icons.CAST_CONNECTED_ROUNDED,
        bgcolor="#7c3aed",
        color="#ffffff",
        on_click=start_device_discovery
    )

    # Компоновка дашборда на базе ft.ResponsiveRow (адаптивная сетка)
    
    # Общие стили для карточек (Glassmorphism)
    def make_glass_card(content_widget, col_sizes, height=None):
        return ft.Container(
            content=content_widget,
            bgcolor=ft.Colors.with_opacity(0.05, "#ffffff"),
            padding=20,
            border_radius=12,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#ffffff")),
            blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
            col=col_sizes,
            height=height
        )

    # Статистика PnL за 7 и 30 дней (чистый вертикальный текст по правому краю)
    stats_column = ft.Column([
        ft.Row([
            ft.Text("ПРИБЫЛЬ 7Д:", size=10, color="#94a3b8", weight=ft.FontWeight.BOLD),
            pnl_7d_val_text
        ], spacing=6, alignment=ft.MainAxisAlignment.END),
        ft.Row([
            ft.Text("ПРИБЫЛЬ 30Д:", size=10, color="#94a3b8", weight=ft.FontWeight.BOLD),
            pnl_30d_val_text
        ], spacing=6, alignment=ft.MainAxisAlignment.END)
    ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END)

    # Карта баланса с мини-графиком кривой депозита по дням
    balance_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color="#0284c7"), balance_card_title]),
                    stats_column
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    ft.Column([
                        balance_text,
                        collateral_text,
                        pnl_text
                    ], spacing=2),
                    ft.Container(
                        content=equity_mini_chart,
                        expand=True,
                        padding=ft.Padding.only(left=20, top=5)
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True)
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            expand=True
        ),
        {"xs": 12, "md": 6},
        height=190
    )

    # Виджет ИИ сигнала в реальном времени (4 четкие строчки без обрезки текста)
    ai_live_container = ft.Column([
        # Строчка 1: Заголовок ИИ + Живые часики
        ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=15, color="#a78bfa"),
                ft.Text("ИИ АНАЛИЗ", size=11, weight=ft.FontWeight.BOLD, color="#a78bfa")
            ], spacing=4),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SCHEDULE_ROUNDED, size=13, color="#10b981"),
                    ai_live_clock_text
                ], spacing=4),
                bgcolor=ft.Colors.with_opacity(0.12, "#10b981"),
                border_radius=6,
                padding=ft.Padding.symmetric(vertical=2, horizontal=7),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.25, "#10b981"))
            )
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        
        # Строчка 2: Сигнал ИИ (Плашка Покупка / Продажа / Нейтрально)
        ft.Row([
            ft.Text("СИГНАЛ ИИ:", size=10, weight=ft.FontWeight.BOLD, color="#64748b"),
            ai_live_action_badge
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),

        # Строчка 3: Фильтр тренда и волатильности (ATR)
        ft.Container(
            content=ft.Row([
                ai_live_trend_text
            ], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(vertical=3, horizontal=8),
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.04, "#ffffff"),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.08, "#ffffff"))
        ),

        # Строчка 4: Уверенность, Порог и Прогресс-бар
        ft.Column([
            ft.Row([
                ai_live_confidence_text,
                ai_live_threshold_text
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ai_live_progress_bar
        ], spacing=4)
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, expand=True)

    # Карта управления ботом с двумя колонками: Левая - Кнопка и статус, Правая - Живой ИИ Анализ
    bot_card = make_glass_card(
        ft.Row([
            # Левая колонка: Управление и кнопка
            ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color="#0284c7"), ft.Text("Управление ботом", size=15, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                    bot_status_label,
                    bot_status_desc,
                    ft.Row([bot_toggle_btn], spacing=10)
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                expand=True
            ),
            ft.VerticalDivider(width=1, color=ft.Colors.with_opacity(0.08, "#ffffff")),
            # Правая колонка: ИИ в реальном времени (без вложенной карточки)
            ft.Container(
                content=ai_live_container,
                padding=ft.Padding.only(left=4, right=4),
                expand=True
            )
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        {"xs": 12, "md": 6},
        height=190
    )

    # Сетка индикаторов
    indicators_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.ANALYTICS, color="#0284c7"), ft.Text(t("ta_indicators", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.ATTACH_MONEY_ROUNDED, color="#10b981"), indicator_price], spacing=15),
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.05, "#ffffff")
                ),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.SHOW_CHART_ROUNDED, color="#38bdf8"), indicator_rsi], spacing=15),
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.05, "#ffffff")
                ),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.TIMELAPSE_ROUNDED, color="#fbbf24"), indicator_atr], spacing=15),
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.05, "#ffffff")
                ),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.ALIGN_VERTICAL_BOTTOM_ROUNDED, color="#f43f5e"), indicator_macd], spacing=15),
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.05, "#ffffff")
                ),
                ft.Container(
                    content=ft.Row([ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, color="#a78bfa"), indicator_bb], spacing=15),
                    padding=10, border_radius=8, bgcolor=ft.Colors.with_opacity(0.05, "#ffffff")
                )
            ],
            spacing=10
        ),
        {"xs": 12, "md": 4},
        height=390
    )

    def render_chart_fast():
        if not cached_raw_klines:
            page.run_task(fetch_dashboard_data)
            return
        try:
            chart_klines = []
            if SAVED_CHART_OFFSET > 0 and len(cached_raw_klines) > SAVED_CHART_OFFSET:
                chart_klines = cached_raw_klines[:-SAVED_CHART_OFFSET][-SAVED_CHART_LIMIT:]
            else:
                chart_klines = cached_raw_klines[-SAVED_CHART_LIMIT:]

            if not chart_klines:
                return

            c_price = current_pair_data.get("price", 0.0)
            closes = [float(k[4]) for k in chart_klines]
            if c_price > 0 and closes and SAVED_CHART_OFFSET == 0:
                closes[-1] = c_price

            y_points = list(closes)
            if c_price > 0 and SAVED_CHART_OFFSET == 0:
                y_points.append(c_price)

            min_c = min(y_points)
            max_c = max(y_points)
            spread = max_c - min_c

            price_points = [ftc.LineChartDataPoint(i, closes[i]) for i in range(len(closes))]
            price_series = ftc.LineChartData(
                points=price_points,
                stroke_width=3,
                color="#0284c7",
                curved=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.15, "#0284c7")
            )

            series_list = [price_series]
            right_padding_x = 8 if SAVED_CHART_OFFSET == 0 else 0
            max_x_val = len(closes) - 1 + right_padding_x
            price_chart.max_x = max_x_val

            current_p = c_price if c_price > 0 else closes[-1]
            series_list.append(
                ftc.LineChartData(
                    points=[ftc.LineChartDataPoint(0, current_p), ftc.LineChartDataPoint(max_x_val, current_p)],
                    stroke_width=1.5,
                    color="#f8fafc",
                    dash_pattern=[4, 4]
                )
            )

            price_chart.data_series = series_list
            import math
            if spread == 0: spread = min_c * 0.01
            mag = 10 ** math.floor(math.log10(spread))
            ratio = spread / mag
            step_y = mag / 5 if ratio < 2 else (mag / 2 if ratio < 5 else mag)

            min_y_val = math.floor((min_c - spread * 0.1 + SAVED_CHART_Y_SHIFT) / step_y) * step_y
            max_y_val = math.ceil((max_c + spread * 0.1 + SAVED_CHART_Y_SHIFT) / step_y) * step_y

            price_chart.min_y = min_y_val
            price_chart.max_y = max_y_val

            y_labels = []
            val = min_y_val
            while val <= max_y_val + (step_y / 10):
                txt = f"- {val:,.2f}" if val >= 1000.0 else f"- {val:,.4f}"
                y_labels.append(ftc.ChartAxisLabel(value=val, label=ft.Text(txt, size=10, color="#94a3b8")))
                val += step_y

            price_chart.right_axis.labels = y_labels
            price_chart.update()
        except Exception as ex:
            print(f"Fast chart render error: {ex}")

    # Кнопки управления зумом и навигацией по графику (Мгновенный отклик из RAM)
    def on_zoom_in(e):
        global SAVED_CHART_LIMIT
        SAVED_CHART_LIMIT = max(15, SAVED_CHART_LIMIT - 10)
        render_chart_fast()

    def on_zoom_out(e):
        global SAVED_CHART_LIMIT
        SAVED_CHART_LIMIT = min(180, SAVED_CHART_LIMIT + 15)
        render_chart_fast()

    def on_move_left(e):
        global SAVED_CHART_OFFSET
        SAVED_CHART_OFFSET += 15
        render_chart_fast()

    def on_move_right(e):
        global SAVED_CHART_OFFSET
        SAVED_CHART_OFFSET = max(0, SAVED_CHART_OFFSET - 15)
        render_chart_fast()

    def on_move_up(e):
        global SAVED_CHART_Y_SHIFT
        # Сдвиг вертикальной оси вверх на 2.5 доллара / шаг
        SAVED_CHART_Y_SHIFT += 2.5
        render_chart_fast()

    def on_move_down(e):
        global SAVED_CHART_Y_SHIFT
        SAVED_CHART_Y_SHIFT -= 2.5
        render_chart_fast()

    def on_reset_chart(e):
        global SAVED_CHART_LIMIT, SAVED_CHART_OFFSET, SAVED_CHART_Y_SHIFT
        SAVED_CHART_LIMIT = 50
        SAVED_CHART_OFFSET = 0
        SAVED_CHART_Y_SHIFT = 0.0
        render_chart_fast()

    chart_toolbar = ft.Row([
        ft.IconButton(icon=ft.Icons.ZOOM_IN, icon_size=16, icon_color="#0284c7", tooltip="Приблизить (+)", on_click=on_zoom_in),
        ft.IconButton(icon=ft.Icons.ZOOM_OUT, icon_size=16, icon_color="#0284c7", tooltip="Отдалить (-)", on_click=on_zoom_out),
        ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_size=16, icon_color="#38bdf8", tooltip="Сдвиг влево (История)", on_click=on_move_left),
        ft.IconButton(icon=ft.Icons.ARROW_FORWARD, icon_size=16, icon_color="#38bdf8", tooltip="Сдвиг вправо (Вперед)", on_click=on_move_right),
        ft.IconButton(icon=ft.Icons.CENTER_FOCUS_STRONG, icon_size=16, icon_color="#10b981", tooltip="Возврат к LIVE режиму", on_click=on_reset_chart),
    ], spacing=0, alignment=ft.MainAxisAlignment.END)

    # Секция графика
    chart_title_box = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.AUTO_GRAPH, color="#0284c7", size=18), chart_title], spacing=6),
        expand=True
    )

    chart_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    chart_title_box,
                    chart_toolbar
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                chart_container
            ],
            expand=True
        ),
        {"xs": 12, "md": 8},
        height=390
    )

    def make_stage_badge(label, color):
        return ft.Container(
            content=ft.Text(label, size=10, color="#ffffff", weight=ft.FontWeight.BOLD),
            bgcolor=color,
            border_radius=20,
            padding=ft.Padding.only(left=12, top=8, bottom=8, right=8)
        )

    def make_stage_block(badge_label, badge_color, content_text_ref, col=None):
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=content_text_ref,
                    padding=ft.Padding.only(left=12, top=8, bottom=8, right=8),
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.04, "#ffffff"),
                    border=ft.Border(
                        left=ft.BorderSide(2, badge_color)
                    )
                )
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=ft.Padding.only(bottom=4),
            col=col
        )

    # Логи ИИ
    logs_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, color="#a78bfa", size=20),
                        bgcolor=ft.Colors.with_opacity(0.15, "#a78bfa"),
                        border_radius=8, padding=6
                    ),
                    ft.Column([
                        ml_strategy_title,
                        ml_log_time
                    ], spacing=0, expand=True),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, "#ffffff")),
                ft.ResponsiveRow([
                    make_stage_block("Stage 1", "#0284c7", ml_logs_stage1, col={"xs": 12, "md": 4}),
                    make_stage_block("Stage 2", "#f59e0b", ml_logs_stage2, col={"xs": 12, "md": 4}),
                    make_stage_block("Stage 3", "#ef4444", ml_logs_stage3, col={"xs": 12, "md": 4}),
                ], spacing=12),
            ],
            spacing=12
        ),
        {"xs": 12, "md": 12}
    )

    # Активные ордера
    orders_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.SHOPPING_CART_CHECKOUT, color="#0284c7"), orders_card_title_text]),
                active_orders_column
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )

    # История ордеров
    order_history_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.HISTORY, color="#0284c7"), ft.Text("История ордеров", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                order_history_column
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )

    # История логов
    logs_history_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.HISTORY_TOGGLE_OFF_ROUNDED, color="#38bdf8", size=20),
                        bgcolor=ft.Colors.with_opacity(0.12, "#38bdf8"),
                        border_radius=8, padding=6
                    ),
                    ft.Text("История сигналов ИИ", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, "#ffffff")),
                logs_history_column
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )

    # Переключатель шага группировки стакана (Tick Size Aggregation)
    orderbook_group_step = SAVED_ORDERBOOK_STEP
    group_options = ["0.001", "0.01", "0.1", "1", "10", "100"]
    step_buttons = []
    
    def make_step_click(s_val):
        def handler(e):
            global SAVED_ORDERBOOK_STEP
            nonlocal orderbook_group_step
            orderbook_group_step = s_val
            SAVED_ORDERBOOK_STEP = s_val
            for btn in step_buttons:
                is_sel = (btn.data == orderbook_group_step)
                btn.bgcolor = "#0284c7" if is_sel else ft.Colors.TRANSPARENT
                if isinstance(btn.content, ft.Text):
                    btn.content.color = "#ffffff" if is_sel else "#94a3b8"
            try:
                orderbook_card.update()
            except:
                pass
        return handler

    for step_val in group_options:
        is_init_sel = (step_val == orderbook_group_step)
        btn = ft.Container(
            content=ft.Text(step_val, size=11, color="#ffffff" if is_init_sel else "#94a3b8", weight=ft.FontWeight.BOLD),
            data=step_val,
            on_click=make_step_click(step_val),
            bgcolor="#0284c7" if is_init_sel else ft.Colors.TRANSPARENT,
            padding=ft.Padding(8, 4, 8, 4),
            border_radius=6
        )
        step_buttons.append(btn)

    step_selector_row = ft.Row([
        ft.Text("Шаг цены (Tick):", size=11, color="#94a3b8", weight=ft.FontWeight.BOLD),
        ft.Row(step_buttons, spacing=2)
    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Стакан цен и Крупные плотности
    orderbook_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ft.Icons.VIEW_LIST_ROUNDED, color="#38bdf8", size=20),
                            bgcolor=ft.Colors.with_opacity(0.12, "#38bdf8"),
                            border_radius=8, padding=6
                        ),
                        ft.Text("Стакан цен и Крупные плотности (Order Book Walls)", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    step_selector_row
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, "#ffffff")),
                orderbook_wall_badge,
                ft.ResponsiveRow([
                    ft.Column([
                        ft.Text("🟢 BIDS (ПОКУПКА)", size=11, weight=ft.FontWeight.BOLD, color="#10b981"),
                        orderbook_bids_col
                    ], col={"xs": 12, "md": 6}),
                    ft.Column([
                        ft.Text("🔴 ASKS (ПРОДАЖА)", size=11, weight=ft.FontWeight.BOLD, color="#ef4444"),
                        orderbook_asks_col
                    ], col={"xs": 12, "md": 6}),
                ], spacing=12)
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )

    # Карта ликвидаций фьючерсов
    liquidation_map_card = make_glass_card(
        ft.Column(
            [
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.FLASH_ON_ROUNDED, color="#a78bfa", size=20),
                        bgcolor=ft.Colors.with_opacity(0.12, "#a78bfa"),
                        border_radius=8, padding=6
                    ),
                    ft.Text("Карта ликвидаций фьючерсов (Predicted Liquidation Map)", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, "#ffffff")),
                liq_map_magnet_badge,
                ft.ResponsiveRow([
                    ft.Column([
                        ft.Text("🟢 SHORT LIQUIDATIONS (ВЫШЕ ЦЕНЫ)", size=11, weight=ft.FontWeight.BOLD, color="#10b981"),
                        liq_map_shorts_col
                    ], col={"xs": 12, "md": 6}),
                    ft.Column([
                        ft.Text("🔴 LONG LIQUIDATIONS (НИЖЕ ЦЕНЫ)", size=11, weight=ft.FontWeight.BOLD, color="#ef4444"),
                        liq_map_longs_col
                    ], col={"xs": 12, "md": 6}),
                ], spacing=12)
            ],
            spacing=10
        ),
        {"xs": 12, "md": 12}
    )

    main_layout = ft.ResponsiveRow(
        [
            balance_card,
            bot_card,
            chart_card,
            indicators_card,
            orders_card,
            orderbook_card,
            liquidation_map_card
        ],
        spacing=16
    )

    # Начальное обновление выполняется внутри dashboard_refresher
    return main_layout

