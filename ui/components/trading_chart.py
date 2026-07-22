import flet as ft
import flet_charts as ftc
from datetime import datetime
import json

class TradingChart(ft.Container):
    def __init__(self, height=320):
        super().__init__()
        self.height = height
        
        self.current_price_text = ft.Text("Цена: ---", size=24, weight=ft.FontWeight.BOLD, color="#ffffff")
        
        self.price_chart = ftc.LineChart(
            data_series=[],
            border=ft.Border(
                bottom=ft.BorderSide(1, "#334155"),
                right=ft.BorderSide(1, "#334155")
            ),
            right_axis=ftc.ChartAxis(labels=[], label_size=45),
            bottom_axis=ftc.ChartAxis(labels=[], label_size=30),
            interactive=False,
            expand=True,
            min_y=0,
            max_y=1
        )
        
        self.content = ft.Stack([
            self.price_chart,
            ft.Container(
                content=self.current_price_text,
                alignment=ft.Alignment(-1, -1),
                padding=10
            )
        ], expand=True)
        self.expand = True

    def update_data(self, chart_klines, active_orders):
        if not chart_klines:
            return
            
        try:
            # Отображаем последние 60 свечей для красоты и простоты
            visible_candles = 60
            if len(chart_klines) > visible_candles:
                sliced_klines = chart_klines[-visible_candles:]
            else:
                sliced_klines = chart_klines

            closes = [float(k[4]) for k in sliced_klines]
            current_price = closes[-1]
            times = [datetime.fromtimestamp(k[0]/1000).strftime("%H:%M") for k in sliced_klines]
            
            # Обновляем текст текущей цены
            self.current_price_text.value = f"${current_price:,.2f}"
            
            min_c = min(closes)
            max_c = max(closes)
            spread = max_c - min_c
            
            import math
            
            import math
            
            # Добавляем отступы сверху и снизу (10%)
            min_y_val = min_c - spread * 0.1 if spread > 0 else min_c * 0.99
            max_y_val = max_c + spread * 0.1 if spread > 0 else max_c * 1.01
            
            points = []
            for i, c in enumerate(closes):
                points.append(ftc.LineChartDataPoint(i, c))
                
            # Красивая синяя линия цены
            price_series = ftc.LineChartData(
                points=points,
                color="#3b82f6", 
                stroke_width=2
            )
            
            series_list = [price_series]
            
            # Горизонтальные линии и ТОЧКА АКТИВАЦИИ для активных и отложенных ордеров
            max_x_val = len(closes) - 1
            for o_row in active_orders:
                o = dict(o_row)
                entry = float(o["entry_price"])
                side = str(o.get("side", "BUY")).upper()
                order_status = str(o.get("status", "ACTIVE")).upper()
                is_active_pos = (order_status == "ACTIVE")

                marker_color = "#10b981" if side == "BUY" else "#ef4444"

                if is_active_pos:
                    act_x_index = 0
                    try:
                        c_at = str(o.get("created_at", ""))
                        if c_at:
                            act_dt = datetime.strptime(c_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            act_ts = act_dt.timestamp()
                            for idx, k in enumerate(sliced_klines):
                                k_ts = k[0] / 1000
                                if k_ts <= act_ts < k_ts + 60:
                                    act_x_index = idx
                                    break
                                elif act_ts >= k_ts + 60 and idx == len(sliced_klines) - 1:
                                    act_x_index = idx
                    except Exception:
                        act_x_index = 0

                    # 1. Линия входа по всей ширине графика (от 0 до max_x_val)
                    series_list.append(
                        ftc.LineChartData(
                            points=[ftc.LineChartDataPoint(0, entry), ftc.LineChartDataPoint(max_x_val, entry)],
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
                                points=[ftc.LineChartDataPoint(0, tp), ftc.LineChartDataPoint(max_x_val, tp)],
                                stroke_width=1,
                                color="#10b981",
                                dash_pattern=[3, 3]
                            )
                        )
                        
                    if o.get("stop_loss"):
                        sl = float(o["stop_loss"])
                        series_list.append(
                            ftc.LineChartData(
                                points=[ftc.LineChartDataPoint(0, sl), ftc.LineChartDataPoint(max_x_val, sl)],
                                stroke_width=1,
                                color="#ef4444",
                                dash_pattern=[3, 3]
                            )
                        )
                else:
                    # PENDING: Показываем только жёлтую пунктирную линию уровня отложенного ордера (без кружка и верт. линии)
                    series_list.append(
                        ftc.LineChartData(
                            points=[ftc.LineChartDataPoint(0, entry), ftc.LineChartDataPoint(max_x_val, entry)],
                            stroke_width=1.5,
                            color="#eab308",
                            dash_pattern=[4, 4]
                        )
                    )
            
            self.price_chart.interactive = True
            self.price_chart.data_series.clear()
            self.price_chart.data_series.extend(series_list)
            self.price_chart.min_y = min_y_val
            self.price_chart.max_y = max_y_val
            self.price_chart.min_x = 0
            empty_space_x = max(2, int(len(closes) * 0.1)) # 10% пустого места справа
            self.price_chart.max_x = max_x_val + empty_space_x
            
            # Подписи оси X (Время)
            step_x = max(1, len(closes) // 6)
            self.price_chart.bottom_axis.labels = [
                ftc.ChartAxisLabel(value=i, label=ft.Text(times[i], size=9, color="#64748b"))
                for i in range(0, len(closes), step_x)
            ]
            
            # Расчет красивых интервалов для оси Y
            range_y = max_y_val - min_y_val
            if range_y == 0:
                nice_step = 1
            else:
                exponent = math.floor(math.log10(range_y))
                fraction = range_y / (10 ** exponent)
                if fraction <= 1.5: nice_fraction = 0.2
                elif fraction <= 3: nice_fraction = 0.5
                elif fraction <= 7: nice_fraction = 1.0
                else: nice_fraction = 2.0
                nice_step = nice_fraction * (10 ** exponent)
                
            start_y = math.ceil(min_y_val / nice_step) * nice_step
            
            y_labels = []
            val = start_y
            while val <= max_y_val:
                if val > 1000: f_val = f"{val:,.0f}"
                elif val > 10: f_val = f"{val:,.2f}"
                else: f_val = f"{val:,.4f}"
                y_labels.append(ftc.ChartAxisLabel(value=val, label=ft.Text(f_val, size=10, color="#64748b")))
                val += nice_step
                
            self.price_chart.right_axis.labels = y_labels
            
            try: 
                self.current_price_text.update()
                self.price_chart.update()
            except: pass
            
        except Exception as e:
            import traceback
            traceback.print_exc()
