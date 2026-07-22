import flet as ft
import flet_charts as ftc
import db
import json
import trading_engine
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from ui.theme import *
from ui.i18n import t, get_lang
from ui.layout import build_layout

def build_dashboard_view(page: ft.Page, lang: str):
    # Хранение текущих данных для графиков и инференса
    current_pair_data = {"klines": [], "price": 0.0}
    rendered_orders = {}

    # --- Компоненты UI для Dashboard ---
    balance_text = ft.Text("$0.00 USDT", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
    collateral_text = ft.Text("$0.00 USDT", size=14, color="#94a3b8")
    pnl_text = ft.Text("$0.00 (0.00%)", size=18, weight=ft.FontWeight.BOLD, color="#10b981")
    bot_status_label = ft.Text("Strategy Status", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    bot_status_desc = ft.Text("Stopped", size=14, color="#94a3b8")
    bot_toggle_btn_text = ft.Text("Start Bot", color="#ffffff")
    bot_toggle_btn = ft.ElevatedButton(content=bot_toggle_btn_text, bgcolor="#0284c7")

    t_chart = t("price_chart", lang)
    t_ai_strat = t("ai_strategy", lang)
    t_wait_data = t("waiting_data", lang)

    # Chart & Price
    chart_title = ft.Text(t_chart, size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")
    indicator_price = ft.Text("Price: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")

    # TA Indicators
    indicator_rsi = ft.Text("RSI: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_atr = ft.Text("ATR%: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_macd = ft.Text("MACD: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")
    indicator_bb = ft.Text("Bollinger Bands: N/A", size=14, weight=ft.FontWeight.W_500, color="#f8fafc")

    # Active Orders
    active_orders_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE)
    order_history_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE, height=200)
    logs_history_column = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE, height=250)

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
        
        # Обновляем заголовки графиков и аналитики (мнемо-индикаторы)
        chart_title.value = f"{t_chart} ({pair} • {timeframe} • {market_type})"
        ml_strategy_title.value = f"{t_ai_strat} ({pair} • {timeframe} • {market_type})"
        
        # 1. Загрузка цен и активных ордеров для PnL и балансов
        active_orders = []
        current_price = 0.0
        try:
            active_orders = await asyncio.to_thread(db.get_active_orders)
            current_price = await asyncio.to_thread(trading_engine.fetch_current_price, pair, market_type)
            indicator_price.value = f"Price: {current_price:,.2f}"
        except Exception as e:
            print(f"Error loading price/orders on dashboard: {e}")

        # Рассчитаем нереализованный PNL активных ордеров
        unrealized_pnl = 0.0
        if active_orders and current_price > 0:
            for o in active_orders:
                amount = float(o["amount"])
                entry = float(o["entry_price"])
                side = o["side"]
                if side == "BUY":
                    unrealized_pnl += amount * (current_price - entry)
                else:
                    unrealized_pnl += amount * (entry - current_price)

        # 3. Расчет сегодняшнего реализованного PnL
        realized_pnl = 0.0
        try:
            daily_pnl = await asyncio.to_thread(db.get_daily_pnl, trading_mode=trading_mode)
            if isinstance(daily_pnl, list):
                today_str = datetime.now().strftime("%Y-%m-%d")
                for row in daily_pnl:
                    if row.get("day") == today_str:
                        realized_pnl = float(row.get("total_pnl") or 0.0)
                        break
        except Exception as e:
            print(f"Error fetching daily PNL: {e}")

        # 2. Обновление балансов и Equity (Баланс + плавающий PnL)
        balance_val = 0.0
        try:
            if is_live:
                bal = await asyncio.to_thread(trading_engine.fetch_binance_balance, market_type)
                balance_val = float(bal) if bal is not None else 0.0
                display_bal = balance_val + unrealized_pnl
                balance_text.value = f"${display_bal:,.2f} USDT"
                collateral_text.value = "Live Account Equity (Binance)"
            else:
                balance_val = float(settings.get("demo_balance") or 10000.0)
                display_bal = balance_val + unrealized_pnl
                balance_text.value = f"${display_bal:,.2f} USDT"
                
                # Рассчитаем задействованное обеспечение (размер ордера в USDT)
                collateral_val = sum(float(o["size_usdt"]) for o in active_orders)
                collateral_text.value = f"{t('wallet_collateral', get_lang(page))}: ${collateral_val:,.2f} USDT"
        except Exception as e:
            print(f"Error fetching balances: {e}")

        # Суммируем реализованный PNL и нереализованный PNL текущих позиций
        total_pnl = realized_pnl + unrealized_pnl
        base_bal = balance_val - realized_pnl
        pnl_pct = (total_pnl / (base_bal + 1e-10)) * 100.0 if base_bal > 0 else 0.0

        pnl_text.value = f"${total_pnl:+.2f} ({pnl_pct:+.2f}%)"
        pnl_text.color = "#10b981" if total_pnl >= 0 else "#ef4444"
    
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
                if order_status == "ACTIVE" and current_price > 0:
                    if side == "BUY":
                        unrealized = amount * (current_price - entry)
                    else:
                        unrealized = amount * (entry - current_price)

                unrealized_color = "#10b981" if unrealized >= 0 else "#ef4444"
                leverage_str = f" | Lev: {o['leverage']}x" if (dict(o).get("market_type", "SPOT") or "SPOT").upper() == "FUTURES" else ""
                tp_str = f"${float(o['take_profit']):.2f}" if o.get("take_profit") else "—"
                sl_str = f"${float(o['stop_loss']):.2f}" if o.get("stop_loss") else "—"

                pnl_display_str = f"${unrealized:+.2f}" if order_status == "ACTIVE" else "PENDING"
                status_bg = "#0284c7" if order_status == "ACTIVE" else "#eab308"

                if order_id in rendered_orders:
                    # Обновляем тексты существующего ордера (без пересоздания виджета)
                    info = rendered_orders[order_id]
                    info["price_text"].value = f"${current_price:.2f}"
                    info["pnl_text"].value = pnl_display_str
                    info["pnl_text"].color = unrealized_color if order_status == "ACTIVE" else "#eab308"
                    info["sl_text"].value = f"SL: {sl_str}"
                    info["tp_text"].value = f"TP: {tp_str}"
                else:
                    # Создаем виджеты для нового ордера
                    price_text = ft.Text(f"${current_price:.2f}", size=11, color="#94a3b8")
                    sl_text = ft.Text(f"SL: {sl_str}", size=11, color="#f43f5e")
                    tp_text = ft.Text(f"TP: {tp_str}", size=11, color="#10b981")

                    order_pnl_text = ft.Text(pnl_display_str, weight=ft.FontWeight.BOLD, color=unrealized_color if order_status == "ACTIVE" else "#eab308", size=13)
                    
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
                                
                                # Col 2: Entry / Current
                                ft.Column([
                                    ft.Text("ENTRY / CURRENT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"${entry:.2f}", size=12, color="#f8fafc"),
                                    price_text
                                ], spacing=2, width=110),
                                
                                # Col 3: Targets (SL / TP)
                                ft.Column([
                                    ft.Text("SL / TP", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    sl_text,
                                    tp_text
                                ], spacing=2, width=110),
                                
                                # Col 4: Stake details
                                ft.Column([
                                    ft.Text("STAKE", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"${float(o['size_usdt']):.2f}", size=12, color="#f8fafc"),
                                    ft.Text(f"Lev: {o['leverage']}x" if o.get('leverage') else "Spot", size=11, color="#94a3b8")
                                ], spacing=2, width=80),
                                
                                # Col 5: Result
                                ft.Column([
                                    ft.Text("LIVE RESULT", size=9, color="#94a3b8", weight=ft.FontWeight.BOLD),
                                    order_pnl_text,
                                    ft.Container(
                                        content=ft.Text(order_status, size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                        bgcolor=status_bg,
                                        padding=ft.Padding.symmetric(vertical=1, horizontal=4),
                                        border_radius=4
                                    )
                                ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
                                
                                # Col 6: Action
                                ft.IconButton(
                                    icon=ft.Icons.CANCEL_ROUNDED,
                                    icon_color="#ef4444",
                                    tooltip="Close Order",
                                    on_click=make_close_handler(order_id),
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
                        "tp_text": tp_text
                    }
                    new_controls_added = True

            # Запускаем анимацию появления для новых ордеров
            if new_controls_added:
                page.update()
                await asyncio.sleep(0.05)  # Небольшая пауза, чтобы Flet зарегистрировал начальное состояние
                for order_id, order_info in rendered_orders.items():
                    order_info["control"].opacity = 1
                    order_info["control"].scale = 1.0
                page.update()
        except Exception as e:
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
            print(f"Error fetching order history: {e}")

        # 5. История логов нейросети
        tz_offset = getattr(page, "tz_offset", 180)
        user_tz = timezone(timedelta(minutes=tz_offset))

        def to_client_local_str(ts_str):
            if not ts_str:
                return "—"
            try:
                utc_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                return utc_dt.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return ts_str

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

        # 5. Логи ИИ (Читаем живой расчет в реальном времени из памяти, либо лог из БД при старте)
        try:
            latest_log = trading_engine.LATEST_LIVE_SIGNAL
            source_desc = "Live prediction"
            if not latest_log:
                analysis_logs = await asyncio.to_thread(db.get_all_analysis_logs)
                if analysis_logs:
                    latest_log = analysis_logs[0]
                    source_desc = "Database log"
            
            if latest_log:
                ml_logs_stage1.value = latest_log.get("stage1_output") or "—"
                ml_logs_stage2.value = latest_log.get("stage2_output") or "—"
                # Format stage3 JSON nicely
                try:
                    import json as _json
                    s3 = _json.loads(latest_log.get("stage3_output") or "{}")
                    action = s3.get("action", "HOLD")
                    price = s3.get("price", 0)
                    prob = s3.get("probability", 0)
                    reason = s3.get("reason", "")
                    reason2 = s3.get("reason2", "")
                    order_type = s3.get("order_type", "")
                    action_icon = "🟢" if action == "BUY" else ("🔴" if action == "SELL" else "⏸")
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
                    ml_logs_stage3.value = latest_log.get("stage3_output") or "—"
                
                ts = to_client_local_str(latest_log.get("created_at", "—"))
                ml_log_time.value = f"🕐  Last run: {ts} ({source_desc})"
                ml_strategy_title.value = f"{t_ai_strat} ({pair} • {timeframe} • {market_type})"
            else:
                t_no_ai_dec = t("no_ai_dec", lang)
                ml_logs_stage1.value = t_no_ai_dec
                ml_logs_stage2.value = ""
                ml_logs_stage3.value = ""
                ml_log_time.value = "Last run: —"
        except Exception as e:
            print(f"Error reading latest AI log: {e}")

        
        # 6. Отрисовка графика
        try:
            chart_klines = await asyncio.to_thread(trading_engine.fetch_binance_klines, pair, timeframe, limit=50, market_type=market_type)
            if chart_klines:
                closes = [float(k[4]) for k in chart_klines]
                opens = [float(k[1]) for k in chart_klines]
                times = [datetime.fromtimestamp(k[0]/1000).strftime("%H:%M") for k in chart_klines]
            
                min_c = min(closes)
                max_c = max(closes)
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
            
                # Горизонтальные линии и ТОЧКА АКТИВАЦИИ для активных ордеров
                for o in active_orders:
                    entry = float(o["entry_price"])
                    side = str(o.get("side", "BUY")).upper()

                    # Находим X-координату точки активации на графике (индекс свечи по времени активации)
                    act_x_index = 0
                    try:
                        c_at = str(o.get("created_at", ""))
                        if c_at:
                            act_dt = datetime.strptime(c_at, "%Y-%m-%d %H:%M:%S")
                            act_ts = act_dt.timestamp()
                            for idx, k in enumerate(chart_klines):
                                k_ts = k[0] / 1000
                                if k_ts <= act_ts < k_ts + 60 or (idx == len(chart_klines) - 1 and act_ts >= k_ts):
                                    act_x_index = idx
                                    break
                    except Exception:
                        act_x_index = 0

                    marker_color = "#10b981" if side == "BUY" else "#ef4444"

                    # 1. Линия входа (от точки активации вправо)
                    series_list.append(
                        ftc.LineChartData(
                            points=[ftc.LineChartDataPoint(act_x_index, entry), ftc.LineChartDataPoint(len(closes) + int(len(closes) * 0.33), entry)],
                            stroke_width=1.5,
                            color="#38bdf8",
                            dash_pattern=[5, 5]
                        )
                    )

                    # 2. Вертикальная пунктирная линия активации (от осей до точки входа)
                    series_list.append(
                        ftc.LineChartData(
                            points=[ftc.LineChartDataPoint(act_x_index, min_y_val), ftc.LineChartDataPoint(act_x_index, entry)],
                            stroke_width=1.5,
                            color=marker_color,
                            dash_pattern=[2, 2]
                        )
                    )

                    # 3. ТОЧКА АКТИВАЦИИ (Яркий маркер/кружок в точке [время активации, цена активации])
                    series_list.append(
                        ftc.LineChartData(
                            points=[ftc.LineChartDataPoint(act_x_index, entry)],
                            stroke_width=0,
                            color=marker_color,
                            show_markers=True,
                            marker_size=12,
                            marker_color=marker_color
                        )
                    )
                
                    if o["take_profit"]:
                        tp = float(o["take_profit"])
                        # Линия TP (зеленая)
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(act_x_index, tp), ftc.LineChartDataPoint(len(closes) + int(len(closes) * 0.33), tp)],
                                stroke_width=1,
                                color="#10b981",
                                dash_pattern=[3, 3]
                            )
                        )
                    
                    if o["stop_loss"]:
                        sl = float(o["stop_loss"])
                        # Линия SL (красная)
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(act_x_index, sl), ftc.LineChartDataPoint(len(closes) + int(len(closes) * 0.33), sl)],
                                stroke_width=1,
                                color="#ef4444",
                                dash_pattern=[3, 3]
                            )
                        )
            
                # Сдвигаем график на треть влево (добавляем пустое место справа)
                max_x_val = len(closes) + int(len(closes) * 0.33)
                price_chart.max_x = max_x_val
                
                # Линия текущей цены (белая пунктирная) - синхронизируем с живой ценой
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
            await asyncio.sleep(0.5)

            # Пропускаем если не на дашборде, но не выходим
            if page.route != "/dashboard":
                continue

            try:
                await fetch_dashboard_data()
            except Exception as e:
                err = str(e)
                if any(x in err.lower() for x in [
                    "session closed", "destroyed session",
                    "has been closed", "connection closed",
                    "websocket", "broken pipe"
                ]):
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
    
    action_btn = ft.ElevatedButton(
        t("trigger_ml", lang),
        on_click=trigger_analysis,
        bgcolor="#8b5cf6",
        color="#ffffff"
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

    # Карта баланса
    balance_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color="#0284c7"), ft.Text(t("demo_balance", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                balance_text,
                collateral_text,
                pnl_text
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            expand=True
        ),
        {"xs": 12, "md": 6},
        height=190
    )

    # Карта управления ботом
    bot_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.SMART_TOY_ROUNDED, color="#0284c7"), ft.Text("Управление ботом", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
                bot_status_label,
                bot_status_desc,
                ft.Row(
                    [
                        bot_toggle_btn,
                    ],
                    spacing=10,
                    alignment=ft.MainAxisAlignment.START
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            expand=True
        ),
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

    # Секция графика
    chart_card = make_glass_card(
        ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.AUTO_GRAPH, color="#0284c7"), chart_title]),
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
                ft.Row([ft.Icon(ft.Icons.SHOPPING_CART_CHECKOUT, color="#0284c7"), ft.Text(t("active_orders", lang), size=16, weight=ft.FontWeight.BOLD, color="#f8fafc")]),
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

    main_layout = ft.ResponsiveRow(
        [
            balance_card,
            bot_card,
            chart_card,
            indicators_card,
            orders_card,
            logs_card
        ],
        spacing=16
    )

    # Начальное обновление выполняется внутри dashboard_refresher
    return main_layout

