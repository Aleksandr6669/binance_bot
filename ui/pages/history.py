import flet as ft
import db
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

def build_history_view(page: ft.Page, lang: str):
    user_id = page.session.store.get("user_id")
    history_list = ft.Column(spacing=10, scroll=ft.ScrollMode.ADAPTIVE, expand=True)
    
    # Фильтры
    pair_field = ft.TextField(label="Pair (e.g. BTCUSDT)", value="", width=150)
    status_dd = ft.Dropdown(
        label="Status",
        options=[
            ft.dropdown.Option("", "All"),
            ft.dropdown.Option("CLOSED_TP", "Take Profit"),
            ft.dropdown.Option("CLOSED_SL", "Stop Loss"),
            ft.dropdown.Option("CLOSED_MANUAL", "Manual Closed"),
            ft.dropdown.Option("CANCELED", "Canceled")
        ],
        width=150,
        value=""
    )
    
    async def apply_filters(e):
        orders = db.get_filtered_orders(
            user_id,
            pair=pair_field.value.upper() if pair_field.value else None,
            status=status_dd.value if status_dd.value else None
        )
        
        history_list.controls.clear()
        if not orders:
            history_list.controls.append(ft.Text("Сделок не найдено", color="#94a3b8"))
        else:
            for o in orders:
                pnl_val = float(o["pnl"]) if o["pnl"] is not None else 0.0
                pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
                card = ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(f"{o['pair']} ({o['side']})", weight=ft.FontWeight.BOLD, size=15),
                                    ft.Container(
                                        content=ft.Text(o["status"], size=11, color="#ffffff"),
                                        bgcolor="#334155" if "MANUAL" in o["status"] else ("#10b981" if "TP" in o["status"] else "#ef4444"),
                                        padding=ft.Padding.symmetric(vertical=6, horizontal=4),
                                        border_radius=4
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            ft.Row(
                                [
                                    ft.Text(f"Entry: ${float(o['entry_price']):.2f}", size=13, color="#94a3b8"),
                                    ft.Text(f"Close: ${float(o['close_price'] or 0.0):.2f}", size=13, color="#94a3b8"),
                                    ft.Text(f"PnL: ${pnl_val:.2f}", size=13, weight=ft.FontWeight.BOLD, color=pnl_color)
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            ft.Text(f"Created: {o['created_at']}", size=11, color="#64748b")
                        ],
                        spacing=6
                    ),
                    bgcolor=CARD_COLOR,
                    border_radius=8,
                    padding=12,
                    border=ft.Border.all(1, "#334155")
                )
                history_list.controls.append(card)
        await page.update()

    pair_field.on_submit = apply_filters
    status_dd.on_change = apply_filters
    
    filter_row = ft.Row([pair_field, status_dd, ft.ElevatedButton("Apply", on_click=apply_filters, bgcolor="#0284c7", color="#ffffff")])
    
    layout = ft.Column(
        [
            ft.Text("Order History", size=20, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            filter_row,
            ft.Divider(color="#334155"),
            history_list
        ],
        expand=True,
        spacing=15
    )
    
    # Первичная загрузка
    page.run_task(apply_filters, None)
    
    return build_layout(page, layout, 1, lang)

