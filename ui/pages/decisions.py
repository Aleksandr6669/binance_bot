import flet as ft
import db
import json
import datetime
from ui.theme import *
from ui.styles import *
from ui.i18n import t
from ui.layout import build_layout
from ui.helpers import make_textfield, make_dropdown

def to_local_time(ts_str, tz_offset_min=None):
    if not ts_str:
        return "—"
    if tz_offset_min is None:
        tz_offset_min = db.get_host_tz_offset_min()
    try:
        clean_ts = str(ts_str).split(".")[0].replace("T", " ")
        utc_dt = datetime.datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        user_tz = datetime.timezone(datetime.timedelta(minutes=tz_offset_min))
        return utc_dt.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_str)

def extract_log_timeframe(log):
    if not isinstance(log, dict):
        return "1m"
        
    if log.get("timeframe"):
        return str(log["timeframe"])

    s3 = log.get("stage3_output")
    if isinstance(s3, str) and "timeframe" in s3:
        try:
            parsed = json.loads(s3)
            if isinstance(parsed, dict) and parsed.get("timeframe"):
                return str(parsed["timeframe"])
        except Exception:
            pass

    s1 = str(log.get("stage1_output") or "")
    import re
    match = re.search(r'\b(1m|3m|5m|15m|30m|1h|4h|1d)\b', s1, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    return "1m"

def build_decisions_view(page: ft.Page, lang: str):
    tz_offset = getattr(page, "tz_offset", None) or db.get_host_tz_offset_min()
    page.tz_offset = tz_offset
    user_tz = datetime.timezone(datetime.timedelta(minutes=tz_offset))
    today_str = datetime.datetime.now(datetime.timezone.utc).astimezone(user_tz).strftime("%Y-%m-%d")

    t_title_label = t("nav_decisions", lang)
    t_loading_decisions = t("loading_decisions", lang)
    t_waiting_list = t("waiting_list", lang)
    t_no_logs = t("no_logs_found", lang)
    t_search_hint = t("search_hint", lang)
    t_select_prompt_1 = t("select_prompt_1", lang)
    t_select_prompt_2 = t("select_prompt_2", lang)
    t_loading_details = t("loading_details", lang)
    t_s1_title = t("s1_detail_title", lang)
    t_s2_title = t("s2_detail_title", lang)
    t_s3_title = t("s3_detail_title", lang)

    decisions_list = ft.Column(
        controls=[
            ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color="#a78bfa"),
                    ft.Text(t_loading_decisions, color="#94a3b8", size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding(0, 40, 0, 40),
                expand=True
            )
        ],
        spacing=10,
        scroll=ft.ScrollMode.ADAPTIVE,
        expand=True
    )
    
    detail_panel = ft.Column(
        controls=[
            ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color="#a78bfa"),
                    ft.Text(t_waiting_list, color="#94a3b8", size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding(0, 40, 0, 0),
                expand=True
            )
        ],
        spacing=15,
        scroll=ft.ScrollMode.ADAPTIVE,
        expand=True
    )

    # Filter state — pair search, timeframe, and single date
    filter_state = {
        "pair": "",
        "tf": "ALL",
        "date": today_str,
    }

    # State tracking
    state = {
        "logs": [],
        "selected_id": None
    }
    rendered_log_ids = set()

    def try_parse_json(text):
        if not text:
            return {}
        try:
            return json.loads(text)
        except:
            try:
                cleaned = text.replace("'", '"')
                return json.loads(cleaned)
            except:
                return {}

    def render_json_properties(data):
        if not isinstance(data, dict):
            return ft.Text(str(data), size=12, color="#cbd5e1")

        rows = []
        for k, v in data.items():
            label_text = k.replace("_", " ").upper()
            val_text = str(v)
            if isinstance(v, float):
                val_text = f"{v:.4f}"
            rows.append(
                ft.Row([
                    ft.Text(f"{label_text}:", size=11, color="#64748b", weight=ft.FontWeight.BOLD, width=150),
                    ft.Text(val_text, size=12, color="#f8fafc", weight=ft.FontWeight.BOLD)
                ], spacing=10)
            )
        return ft.Column(rows, spacing=6)

    def select_log(log_id):
        page.run_task(select_log_async, log_id)

    async def select_log_async(log_id):
        # 1. Мгновенно обновляем выбранный ID
        state["selected_id"] = log_id
        
        # 2. Мгновенно подсвечиваем выбранный элемент в списке слева
        render_list()
        
        # 3. И одновременно мгновенно показываем шапку лога с загрузочным спиннером ниже нее
        render_details(only_header=True)

        # 4. Даем браузеру гарантированно отрисовать подсветку, шапку и спиннер
        import asyncio
        await asyncio.sleep(0.1)

        # 5. И только теперь загружаем и строим детальные карточки STAGE 1, 2, 3
        render_details(only_header=False)

    def render_list():
        has_loader = False
        if len(decisions_list.controls) == 1:
            first_ctrl = decisions_list.controls[0]
            if isinstance(first_ctrl, ft.Container) and hasattr(first_ctrl, "content") and isinstance(first_ctrl.content, ft.Column):
                has_loader = True

        if len(decisions_list.controls) != len(state["logs"]) or has_loader:
            decisions_list.controls.clear()
            rendered_log_ids.clear()
            if not state["logs"]:
                decisions_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=32, color="#64748b"),
                            ft.Text(t_no_logs, color="#94a3b8", size=12, weight=ft.FontWeight.W_500),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
                        alignment=ft.alignment.Alignment(0, 0),
                        padding=ft.Padding(0, 40, 0, 40)
                    )
                )
                try:
                    decisions_list.update()
                except:
                    pass
                return

            for log in state["logs"]:
                is_selected = (log["id"] == state["selected_id"])
                s3 = try_parse_json(log.get("stage3_output"))
                action = s3.get("action", "HOLD")
                prob = s3.get("probability", 0.0)
                action_color = "#38bdf8" if action == "HOLD" else ("#10b981" if "BUY" in action else "#ef4444")
                log_tf = extract_log_timeframe(log)

                tf_pill = ft.Container(
                    content=ft.Text(log_tf, size=9, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
                    padding=ft.Padding.symmetric(vertical=2, horizontal=5),
                    border_radius=4,
                    bgcolor=ft.Colors.with_opacity(0.12, GOLD_COLOR),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.3, GOLD_COLOR))
                )

                def make_click_handler(lid):
                    return lambda _: select_log(lid)

                item_card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Row([
                                ft.Text(log['pair'], weight=ft.FontWeight.BOLD, size=12, color="#f8fafc", no_wrap=True),
                                tf_pill
                            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            ft.Text(f"{action} ({prob*100:.1f}%)", color=action_color, weight=ft.FontWeight.BOLD, size=11, no_wrap=True),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([
                            ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=11, color="#64748b"),
                            ft.Text(to_local_time(log['created_at'], tz_offset), size=10, color="#64748b")
                        ], spacing=4)
                    ], spacing=6),
                    bgcolor=ft.Colors.with_opacity(0.05, "#ffffff") if not is_selected else ft.Colors.with_opacity(0.12, "#ffffff"),
                    blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
                    border_radius=12,
                    padding=ft.Padding(16, 12, 16, 12),
                    border=ft.Border.all(
                        1.5 if is_selected else 1, 
                        "#0284c7" if is_selected else ft.Colors.with_opacity(0.1, "#ffffff")
                    ),
                    on_click=make_click_handler(log["id"])
                )
                decisions_list.controls.append(item_card)
                rendered_log_ids.add(log["id"])
        else:
            # Быстро обновляем свойства существующих карточек
            for idx, log in enumerate(state["logs"]):
                is_selected = (log["id"] == state["selected_id"])
                card = decisions_list.controls[idx]
                card.bgcolor = ft.Colors.with_opacity(0.05, "#ffffff") if not is_selected else ft.Colors.with_opacity(0.12, "#ffffff")
                card.border = ft.Border.all(
                    1.5 if is_selected else 1, 
                    "#0284c7" if is_selected else ft.Colors.with_opacity(0.1, "#ffffff")
                )

        try:
            decisions_list.update()
        except:
            pass

    def render_details(only_header=False):
        selected_log = next((l for l in state["logs"] if l["id"] == state["selected_id"]), None)

        if not selected_log:
            if only_header:
                detail_panel.controls.clear()
                detail_panel.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Icon(ft.Icons.PSYCHOLOGY_ROUNDED, size=64, color="#334155"),
                            ft.Text(
                                t_select_prompt_1,
                                size=16, weight=ft.FontWeight.BOLD, color="#f8fafc",
                                text_align=ft.TextAlign.CENTER
                            ),
                            ft.Text(
                                t_select_prompt_2,
                                size=12, color="#64748b", text_align=ft.TextAlign.CENTER
                            )
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                        alignment=ft.alignment.Alignment(0, 0), expand=True
                    )
                )
                try:
                    detail_panel.update()
                except:
                    pass
            return

        s3 = try_parse_json(selected_log.get("stage3_output"))
        action = s3.get("action", "HOLD")
        prob = s3.get("probability", 0.0)
        action_color = "#38bdf8" if action == "HOLD" else ("#10b981" if "BUY" in action else "#ef4444")
        selected_tf = extract_log_timeframe(selected_log)

        header_card = create_glass_card(
            ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Text(selected_log["pair"], size=22, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                        ft.Container(
                            content=ft.Text(selected_tf, size=11, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
                            padding=ft.Padding.symmetric(vertical=3, horizontal=8),
                            border_radius=6,
                            bgcolor=ft.Colors.with_opacity(0.12, GOLD_COLOR),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, GOLD_COLOR))
                        )
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(t("log_created", lang, time=to_local_time(selected_log['created_at'], tz_offset)), size=12, color="#64748b")
                ], spacing=4),
                ft.Column([
                    ft.Text("DECISION SIGNAL", size=10, color="#64748b", weight=ft.FontWeight.BOLD),
                    ft.Text(f"{action} ({prob*100:.1f}%)", size=22, color=action_color, weight=ft.FontWeight.BOLD)
                ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=15
        )

        if only_header:
            detail_panel.controls.clear()
            detail_panel.controls.append(header_card)
            detail_panel.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.ProgressRing(color=GOLD_COLOR, width=24, height=24),
                        ft.Text(t_loading_details, color="#94a3b8", size=12)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.alignment.Alignment(0, 0),
                    padding=ft.Padding(0, 40, 0, 0),
                    expand=True
                )
            )
            try:
                detail_panel.update()
            except:
                pass
            return

        # Если это полная отрисовка деталей, очищаем панель и строим всё заново
        detail_panel.controls.clear()
        detail_panel.controls.append(header_card)

        s1 = try_parse_json(selected_log.get("stage1_output"))
        s1_title = ft.Row([
            ft.Icon(ft.Icons.ANALYTICS_ROUNDED, color="#38bdf8", size=18),
            ft.Text(t_s1_title, size=13, weight=ft.FontWeight.BOLD, color="#38bdf8")
        ], spacing=8)
        s1_content = render_json_properties(s1) if s1 else ft.Text(selected_log.get("stage1_output", "N/A"), size=12, color="#cbd5e1")
        detail_panel.controls.append(
            create_glass_card(ft.Column([s1_title, ft.Divider(color="#1e293b", height=1), s1_content], spacing=10), padding=15)
        )

        s2 = try_parse_json(selected_log.get("stage2_output"))
        s2_title = ft.Row([
            ft.Icon(ft.Icons.QUERY_STATS_ROUNDED, color="#fbbf24", size=18),
            ft.Text(t_s2_title, size=13, weight=ft.FontWeight.BOLD, color="#fbbf24")
        ], spacing=8)
        s2_content = render_json_properties(s2) if s2 else ft.Text(selected_log.get("stage2_output", "N/A"), size=12, color="#cbd5e1")
        detail_panel.controls.append(
            create_glass_card(ft.Column([s2_title, ft.Divider(color="#1e293b", height=1), s2_content], spacing=10), padding=15)
        )

        s3_title = ft.Row([
            ft.Icon(ft.Icons.BOLT_ROUNDED, color="#f43f5e", size=18),
            ft.Text(t_s3_title, size=13, weight=ft.FontWeight.BOLD, color="#f43f5e")
        ], spacing=8)
        s3_content = render_json_properties(s3) if s3 else ft.Text(selected_log.get("stage3_output", "N/A"), size=12, color="#cbd5e1")
        detail_panel.controls.append(
            create_glass_card(ft.Column([s3_title, ft.Divider(color="#1e293b", height=1), s3_content], spacing=10), padding=15)
        )

        try:
            detail_panel.update()
        except:
            pass

    # ---------- Filter logic ----------
    def run_apply(e=None):
        page.run_task(apply_filters)

    async def apply_filters():
        # Показываем красивый спиннер загрузки
        decisions_list.controls.clear()
        decisions_list.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.ProgressRing(color="#a78bfa"),
                    ft.Text(t_loading_decisions, color="#94a3b8", size=12)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding(0, 40, 0, 40),
                expand=True
            )
        )
        try:
            decisions_list.update()
        except:
            pass

        import asyncio
        # Загружаем данные в фоновом потоке, не блокируя UI
        logs = await asyncio.to_thread(db.get_filtered_analysis_logs, pair=None, date=filter_state["date"] or None, tz_offset_min=tz_offset)
        
        pair_query = (filter_state["pair"] or "").strip().upper()
        selected_tf = (filter_state.get("tf") or "").strip()
        filtered_logs = []
        for log in (logs or []):
            if pair_query and pair_query not in (log.get("pair") or "").upper():
                continue
            tf_val = extract_log_timeframe(log)
            if selected_tf and selected_tf != "ALL" and tf_val.lower() != selected_tf.lower():
                continue
            # Display all decisions, including neutral (HOLD) signals
            filtered_logs.append(log)
        state["logs"] = filtered_logs
        if state["logs"]:
            state["selected_id"] = state["logs"][0]["id"]
        else:
            state["selected_id"] = None
        render_list()
        render_details(only_header=True)
        await asyncio.sleep(0.1)
        render_details(only_header=False)

    # ---------- Pair search field ----------
    pair_field = make_textfield(hint_text=t_search_hint, value="", on_change=run_apply)
    pair_field.height = 48
    pair_field.margin = ft.Margin.all(0)
    pair_field.content_padding = ft.Padding(10, 14, 10, 14)
    pair_field.text_size = 10
    pair_field.expand = True

    def on_pair_change(e):
        filter_state["pair"] = pair_field.value or ""
        run_apply()

    pair_field.on_change = on_pair_change

    # ---------- Timeframe Filter Dropdown ----------
    timeframe_options = [
        ("", "Все" if lang == "ru" else "All"),
        ("1m", "1m"),
        ("3m", "3m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("30m", "30m"),
        ("1h", "1h")
    ]
    tf_dropdown = make_dropdown(
        label=None,
        options=[ft.dropdown.Option(k, v) for k, v in timeframe_options],
        width=115,
        value="",
        on_change=lambda e: on_tf_change(e)
    )
    tf_dropdown.height = 48
    tf_dropdown.content_padding = ft.Padding(10, 14, 10, 14)
    tf_dropdown.text_style = ft.TextStyle(size=10)

    def on_tf_change(e):
        filter_state["tf"] = tf_dropdown.value or ""
        run_apply()

    # ---------- Single date picker ----------
    date_text = ft.Text(filter_state["date"], size=10, color="#f8fafc")

    def on_date_picked(e):
        if e.control.value:
            dt = e.control.value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            local_dt = dt.astimezone(user_tz)
            formatted = local_dt.strftime("%Y-%m-%d")
            filter_state["date"] = formatted
            date_text.value = formatted
            date_text.color = "#f8fafc"
            date_container.update()
            run_apply()

    init_dt = datetime.datetime.now(datetime.timezone.utc).astimezone(user_tz).replace(hour=12, minute=0, second=0)
    date_picker = ft.DatePicker(value=init_dt, on_change=on_date_picked)
    page.overlay.append(date_picker)

    def open_date_picker(e):
        if filter_state["date"]:
            try:
                parsed = datetime.datetime.strptime(filter_state["date"], "%Y-%m-%d")
                date_picker.value = parsed.replace(hour=12, minute=0, second=0, tzinfo=user_tz)
            except Exception:
                pass
        date_picker.open = True
        date_picker.update()

    date_container = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=12, color="#94a3b8"), date_text],
            spacing=3,
            alignment=ft.MainAxisAlignment.CENTER
        ),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.3, "#ffffff")),
        border_radius=8,
        padding=ft.Padding(6, 0, 6, 0),
        on_click=open_date_picker,
        bgcolor=ft.Colors.TRANSPARENT,
        alignment=ft.alignment.Alignment(0, 0),
        width=110,
        height=48
    )

    filter_card = create_glass_card(
        ft.Row([
            pair_field,
            ft.Container(width=1, height=16, bgcolor="#334155"),
            tf_dropdown,
            ft.Container(width=1, height=16, bgcolor="#334155"),
            date_container,
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=8
    )

    # ---------- Left panel ----------
    left_panel = ft.Column(
        [
            ft.Text("AI Decision Logs", size=18, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            filter_card,
            ft.Divider(color="#334155"),
            decisions_list
        ],
        width=320,
        expand=False,
        spacing=10
    )

    # ---------- Right panel ----------
    right_panel = ft.Column(
        [
            ft.Text("Pipeline Detailed Analysis", size=18, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            ft.Divider(color="#334155"),
            detail_panel
        ],
        expand=True,
        spacing=10
    )

    split_layout = ft.Row(
        [
            left_panel,
            ft.Container(width=1, bgcolor="#334155", expand=False),
            right_panel
        ],
        expand=True,
        spacing=15
    )

    page.load_decisions_data = apply_filters

    async def decisions_refresher():
        import asyncio
        while True:
            await asyncio.sleep(0.5)
            if page.route != "/decisions":
                continue
            
            try:
                logs = await asyncio.to_thread(db.get_filtered_analysis_logs, pair=None, date=filter_state["date"] or None, tz_offset_min=tz_offset)
                if page.route != "/decisions":
                    continue

                pair_query = (filter_state["pair"] or "").strip().upper()
                selected_tf = (filter_state.get("tf") or "").strip()
                filtered_logs = []
                for log in (logs or []):
                    if pair_query and pair_query not in (log.get("pair") or "").upper():
                        continue
                    tf_val = extract_log_timeframe(log)
                    if selected_tf and selected_tf != "ALL" and tf_val.lower() != selected_tf.lower():
                        continue
                    filtered_logs.append(log)

                # Identify new logs that are not currently rendered
                new_logs = [l for l in filtered_logs if l["id"] not in rendered_log_ids]
                if new_logs:
                    if not rendered_log_ids:
                        decisions_list.controls.clear()

                    newly_created_controls = []
                    # Insert new logs at their correct positions
                    # Since they are sorted DESC by created_at, new logs appear at their sorted position
                    for log in reversed(new_logs): # Insert older new ones first, so the newest ends up at the top
                        action_s3 = try_parse_json(log.get("stage3_output"))
                        act = action_s3.get("action", "HOLD")
                        prb = action_s3.get("probability", 0.0)
                        act_color = "#38bdf8" if act == "HOLD" else ("#10b981" if "BUY" in act else "#ef4444")
                        log_tf = extract_log_timeframe(log)

                        tf_pill = ft.Container(
                            content=ft.Text(log_tf, size=9, weight=ft.FontWeight.BOLD, color=GOLD_COLOR),
                            padding=ft.Padding.symmetric(vertical=2, horizontal=5),
                            border_radius=4,
                            bgcolor=ft.Colors.with_opacity(0.12, GOLD_COLOR),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, GOLD_COLOR))
                        )
                        
                        def make_click_handler(lid):
                            return lambda _: select_log(lid)

                        is_sel = (log["id"] == state["selected_id"])
                        card = ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Row([
                                        ft.Text(log['pair'], weight=ft.FontWeight.BOLD, size=12, color="#f8fafc"),
                                        tf_pill
                                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                    ft.Text(f"{act} ({prb*100:.1f}%)", color=act_color, weight=ft.FontWeight.BOLD, size=11, no_wrap=True),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                ft.Row([
                                    ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=11, color="#64748b"),
                                    ft.Text(to_local_time(log['created_at'], tz_offset), size=10, color="#64748b")
                                ], spacing=4)
                            ], spacing=6),
                            bgcolor=ft.Colors.with_opacity(0.05, "#ffffff") if not is_sel else ft.Colors.with_opacity(0.12, "#ffffff"),
                            blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
                            border_radius=12,
                            padding=ft.Padding(16, 12, 16, 12),
                            border=ft.Border.all(
                                1.5 if is_sel else 1, 
                                "#0284c7" if is_sel else ft.Colors.with_opacity(0.1, "#ffffff")
                            ),
                            on_click=make_click_handler(log["id"]),
                            opacity=0,
                            scale=0.8,
                            animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                            animate_scale=ft.Animation(300, ft.AnimationCurve.EASE_OUT_BACK)
                        )
                        
                        insert_idx = 0
                        for el in state["logs"]:
                            if log["created_at"] < el["created_at"]:
                                insert_idx += 1
                            else:
                                break
                                
                        decisions_list.controls.insert(insert_idx, card)
                        state["logs"].insert(insert_idx, log)
                        rendered_log_ids.add(log["id"])
                        newly_created_controls.append(card)

                    # If previously selected_id was None, select the first new log
                    if state["selected_id"] is None and state["logs"]:
                        state["selected_id"] = state["logs"][0]["id"]
                        # Re-highlight the selected item in the list
                        for idx, el in enumerate(state["logs"]):
                            is_selected = (el["id"] == state["selected_id"])
                            c = decisions_list.controls[idx]
                            c.bgcolor = ft.Colors.with_opacity(0.05, "#ffffff") if not is_selected else ft.Colors.with_opacity(0.12, "#ffffff")
                            c.border = ft.Border.all(
                                1.5 if is_selected else 1, 
                                "#0284c7" if is_selected else ft.Colors.with_opacity(0.1, "#ffffff")
                            )
                        page.run_task(select_log_async, state["selected_id"])

                    try:
                        decisions_list.update()
                    except:
                        pass

                    if newly_created_controls:
                        await asyncio.sleep(0.05)
                        for c in newly_created_controls:
                            c.opacity = 1.0
                            c.scale = 1.0
                        try:
                            decisions_list.update()
                        except:
                            pass
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["session closed", "destroyed session", "has been closed", "connection closed", "websocket", "broken pipe"]):
                    break
                print(f"Decisions background refresher error: {e}")

    page.run_task(decisions_refresher)

    return split_layout
