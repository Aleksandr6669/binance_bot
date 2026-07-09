import flet as ft
import db
import json
from ui.theme import *
from ui.i18n import t
from ui.layout import build_layout

def build_decisions_view(page: ft.Page, lang: str):
    user_id = page.session.store.get("user_id")
    decisions_list = ft.Column(spacing=12, scroll=ft.ScrollMode.ADAPTIVE, expand=True)
    
    async def load_decisions():
        logs = db.get_all_analysis_logs(user_id)
        decisions_list.controls.clear()
        if not logs:
            decisions_list.controls.append(ft.Text("Логи анализа отсутствуют.", color="#94a3b8"))
        else:
            for log in logs[:30]:  # Показываем последние 30 записей
                s3 = {}
                try:
                    s3 = json.loads(log["stage3_output"])
                except:
                    pass
                
                action = s3.get("action", "HOLD")
                prob = s3.get("probability", 0.0)
                reason = s3.get("reason", "No details")
                
                action_color = "#38bdf8" if action == "HOLD" else ("#10b981" if "BUY" in action else "#ef4444")
                
                card = ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(f"{log['pair']}", weight=ft.FontWeight.BOLD, size=15),
                                    ft.Text(f"Action: {action} (Prob: {prob*100:.1f}%)", color=action_color, weight=ft.FontWeight.BOLD, size=13),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            ft.Text(f"Reason: {reason}", size=13, color="#e2e8f0"),
                            ft.ExpansionTile(
                                title=ft.Text("Detailed Pipeline Output", size=11, color="#64748b"),
                                controls=[
                                    ft.Container(
                                        content=ft.Column(
                                            [
                                                ft.Text("Stage 1 Sentiment:", size=11, color="#38bdf8", weight=ft.FontWeight.BOLD),
                                                ft.Text(log["stage1_output"], size=11, color="#cbd5e1"),
                                                ft.Text("Stage 2 Planner:", size=11, color="#fbbf24", weight=ft.FontWeight.BOLD),
                                                ft.Text(log["stage2_output"], size=11, color="#cbd5e1"),
                                                ft.Text("Stage 3 Execution:", size=11, color="#f43f5e", weight=ft.FontWeight.BOLD),
                                                ft.Text(log["stage3_output"], size=11, color="#cbd5e1"),
                                            ],
                                            spacing=5
                                        ),
                                        padding=10,
                                        bgcolor=BG_COLOR,
                                        border_radius=6
                                    )
                                ]
                            ),
                            ft.Text(f"Timestamp: {log['created_at']}", size=11, color="#64748b")
                        ],
                        spacing=8
                    ),
                    bgcolor=CARD_COLOR,
                    border_radius=8,
                    padding=12,
                    border=ft.Border.all(1, "#334155")
                )
                decisions_list.controls.append(card)
        await page.update()

    layout = ft.Column(
        [
            ft.Text("AI Pipeline Decision History", size=20, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            ft.Divider(color="#334155"),
            decisions_list
        ],
        expand=True,
        spacing=15
    )
    
    page.run_task(load_decisions)
    
    return build_layout(page, layout, 2, lang)

