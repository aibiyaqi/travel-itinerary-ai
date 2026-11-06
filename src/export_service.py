"""
导出服务模块 — 行程方案导出交付能力

功能:
  1. export_to_markdown(itinerary_id) → Markdown 格式文本
  2. export_to_text(itinerary_id) → 纯文本格式

支持从方案详情页直接复制文本或下载 Markdown 文件。
"""
import html
import json
import logging
from typing import Dict, Any, Optional

from src.db_service import get_itinerary
from src.config import ITINERARY_STATUS_OPTIONS

logger = logging.getLogger("travel_assistant.export")


# =====================================================================
# 格式化工具
# =====================================================================

def _format_cost(cost: float) -> str:
    """格式化费用显示。"""
    if cost and cost > 0:
        return f"¥{cost:,.0f}"
    return ""


def _to_number(value: Any, default: float = 0.0) -> float:
    """把 "约5000" / "5000元" / None 等异常值安全转成数字。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        import re
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", "").replace("，", ""))
        if match:
            try:
                return float(match.group())
            except ValueError:
                return default
    return default


def _daily_plan_to_markdown(daily_plan: list) -> str:
    """将每日行程列表转换为 Markdown。"""
    lines = []
    for day in daily_plan:
        day_num = day.get("day", 1)
        date_desc = day.get("date_desc", f"第{day_num}天")
        lines.append(f"\n### {date_desc}\n")

        for period_name, period_label in [
            ("morning", "🌅 上午"),
            ("afternoon", "☀️ 下午"),
            ("evening", "🌙 晚上"),
        ]:
            period = day.get(period_name, {})
            if isinstance(period, dict):
                activity = period.get("activity", "")
                location = period.get("location", "")
                cost = period.get("cost_est", 0)
                note = period.get("note", "")
                if activity:
                    cost_str = _format_cost(cost)
                    parts = [f"**{period_label}**：{activity}"]
                    if location:
                        parts.append(f"📍 {location}")
                    if cost_str:
                        parts.append(f"💰 {cost_str}")
                    if note:
                        parts.append(f"💡 {note}")
                    lines.append("  \n".join(parts) + "  \n")
            elif isinstance(period, str) and period:
                lines.append(f"**{period_label}**：{period}  \n")

        accommodation = day.get("accommodation", "")
        meals = day.get("meals", "")
        transport = day.get("transport", "")

        if accommodation:
            lines.append(f"- **🏨 住宿**：{accommodation}")
        if meals:
            lines.append(f"- **🍽️ 餐饮**：{meals}")
        if transport:
            lines.append(f"- **🚗 交通**：{transport}")

    return "\n".join(lines)


def _daily_plan_to_text(daily_plan: list) -> str:
    """将每日行程列表转换为纯文本。"""
    lines = []
    for day in daily_plan:
        day_num = day.get("day", 1)
        date_desc = day.get("date_desc", f"第{day_num}天")
        lines.append(f"\n{'='*40}")
        lines.append(f"{date_desc}")
        lines.append(f"{'='*40}\n")

        for period_name, period_label in [
            ("morning", "上午"),
            ("afternoon", "下午"),
            ("evening", "晚上"),
        ]:
            period = day.get(period_name, {})
            if isinstance(period, dict):
                activity = period.get("activity", "")
                location = period.get("location", "")
                cost = period.get("cost_est", 0)
                note = period.get("note", "")
                if activity:
                    cost_str = _format_cost(cost)
                    line = f"[{period_label}] {activity}"
                    if location:
                        line += f" (地点: {location})"
                    if cost_str:
                        line += f" [费用: {cost_str}]"
                    lines.append(line)
                    if note:
                        lines.append(f"  提示: {note}")
            elif isinstance(period, str) and period:
                lines.append(f"[{period_label}] {period}")

        accommodation = day.get("accommodation", "")
        meals = day.get("meals", "")
        transport = day.get("transport", "")

        if accommodation:
            lines.append(f"住宿: {accommodation}")
        if meals:
            lines.append(f"餐饮: {meals}")
        if transport:
            lines.append(f"交通: {transport}")

    return "\n".join(lines)


# =====================================================================
# 导出函数
# =====================================================================

def export_to_markdown(itinerary_id: int) -> str:
    """
    将行程方案导出为 Markdown 文本。

    参数:
        itinerary_id: 方案 ID

    返回:
        Markdown 格式的完整方案文本
    """
    itinerary = get_itinerary(itinerary_id)
    if not itinerary:
        return "# 方案不存在\n"

    try:
        content = json.loads(itinerary["content_json"])
    except (json.JSONDecodeError, TypeError):
        return "# 方案数据异常\n"

    lines = []

    # ── 标题 ──
    title = content.get("title", "行程方案")
    lines.append(f"# {title}")
    lines.append("")

    # ── 基本信息 ──
    lines.append("## 📋 基本信息")
    lines.append("")
    lines.append(f"- **客户名称**：{itinerary.get('client_name', '')}")
    lines.append(f"- **目的地**：{itinerary.get('destination', '')}")
    lines.append(f"- **出行天数**：{itinerary.get('travel_days', '')}天")
    lines.append(f"- **出行人数**：{itinerary.get('traveler_count', '')}人")

    budget = itinerary.get("total_budget")
    if _to_number(budget) > 0:
        lines.append(f"- **总预算**：¥{_to_number(budget):,.0f}")
    lines.append(f"- **出行类型**：{itinerary.get('travel_type', '')}")
    lines.append(f"- **偏好**：{itinerary.get('preferences', '')}")
    if itinerary.get("special_requirements"):
        lines.append(f"- **特殊要求**：{itinerary['special_requirements']}")

    status_text = ITINERARY_STATUS_OPTIONS.get(itinerary["status"], itinerary["status"])
    lines.append(f"- **方案状态**：{status_text}")
    lines.append(f"- **版本号**：v{itinerary['version']}")
    lines.append(f"- **生成时间**：{itinerary['created_at']}")
    lines.append("")

    # ── 行程概述 ──
    overview = content.get("overview", "")
    if overview:
        lines.append("## 📝 行程概述")
        lines.append("")
        lines.append(overview)
        lines.append("")

    # ── 每日行程 ──
    lines.append("## 📅 每日行程安排")
    daily_plan = content.get("daily_plan", [])
    lines.append(_daily_plan_to_markdown(daily_plan))
    lines.append("")

    # ── 费用估算 ──
    total_cost = _to_number(content.get("total_cost_est"))
    if total_cost > 0:
        lines.append("## 💰 费用估算")
        lines.append("")
        lines.append(f"**总计**：¥{total_cost:,.0f}")
        cost_breakdown = content.get("cost_breakdown", "")
        if cost_breakdown:
            lines.append("")
            lines.append(f"**费用明细**：{cost_breakdown}")
        lines.append("")

    # ── 注意事项 ──
    notes = content.get("notes", "")
    if notes:
        lines.append("## ⚠️ 出行注意事项")
        lines.append("")
        lines.append(notes)
        lines.append("")

    # ── 客户话术 ──
    client_talk = content.get("client_talk", "")
    if client_talk:
        lines.append("## 💬 客户介绍话术")
        lines.append("")
        lines.append(client_talk)
        lines.append("")

    # ── 备选路线 ──
    alternative = content.get("alternative_routes", "")
    if alternative:
        lines.append("## 🔄 备选路线建议")
        lines.append("")
        lines.append(alternative)
        lines.append("")

    lines.append("---")
    lines.append(f"*由智能行程方案生成系统自动生成 · {itinerary['created_at'][:10]}*")

    return "\n".join(lines)


def export_to_text(itinerary_id: int) -> str:
    """
    将行程方案导出为纯文本。

    参数:
        itinerary_id: 方案 ID

    返回:
        纯文本格式的完整方案
    """
    itinerary = get_itinerary(itinerary_id)
    if not itinerary:
        return "方案不存在"

    try:
        content = json.loads(itinerary["content_json"])
    except (json.JSONDecodeError, TypeError):
        return "方案数据异常"

    lines = []

    # 标题
    title = content.get("title", "行程方案")
    lines.append(f"{'='*60}")
    lines.append(f"  {title}")
    lines.append(f"{'='*60}")
    lines.append("")

    # 基本信息
    lines.append("【基本信息】")
    lines.append(f"  客户：{itinerary.get('client_name', '')}")
    lines.append(f"  目的地：{itinerary.get('destination', '')}")
    lines.append(f"  天数：{itinerary.get('travel_days', '')}天 | 人数：{itinerary.get('traveler_count', '')}人")
    budget = itinerary.get("total_budget")
    if _to_number(budget) > 0:
        lines.append(f"  预算：¥{_to_number(budget):,.0f}")
    lines.append(f"  类型：{itinerary.get('travel_type', '')}")
    lines.append(f"  状态：{ITINERARY_STATUS_OPTIONS.get(itinerary['status'], itinerary['status'])}")
    lines.append(f"  版本：v{itinerary['version']}")
    lines.append("")

    # 概述
    overview = content.get("overview", "")
    if overview:
        lines.append("【行程概述】")
        lines.append(f"  {overview}")
        lines.append("")

    # 每日行程
    lines.append("【每日行程安排】")
    daily_plan = content.get("daily_plan", [])
    lines.append(_daily_plan_to_text(daily_plan))
    lines.append("")

    # 费用
    total_cost = _to_number(content.get("total_cost_est"))
    if total_cost > 0:
        lines.append(f"【费用】总计：¥{total_cost:,.0f}")
        cost_detail = content.get("cost_breakdown", "")
        if cost_detail:
            lines.append(f"  明细：{cost_detail}")
        lines.append("")

    # 注意事项
    notes = content.get("notes", "")
    if notes:
        lines.append("【注意事项】")
        lines.append(f"  {notes}")
        lines.append("")

    # 话术
    client_talk = content.get("client_talk", "")
    if client_talk:
        lines.append("【客户话术】")
        lines.append(f"  {client_talk}")

    lines.append("")
    lines.append(f"{'='*60}")
    lines.append(f"由智能行程方案生成系统自动生成 · {itinerary['created_at'][:10]}")

    return "\n".join(lines)


# =====================================================================
# 客户版 HTML 导出（可直接发给客户 / 浏览器打印为 PDF）
# =====================================================================

_CUSTOMER_CSS = """
:root { --brand: #0f766e; --ink: #1f2937; --muted: #6b7280; --line: #e5e7eb; }
* { box-sizing: border-box; }
body { margin: 0; padding: 40px 20px; background: #f8fafc; color: var(--ink);
       font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
       line-height: 1.75; }
.page { max-width: 880px; margin: 0 auto; background: #fff; padding: 48px 56px;
        border-radius: 14px; box-shadow: 0 8px 30px rgba(15, 23, 42, .08); }
.brand { color: var(--brand); font-size: 13px; letter-spacing: .12em; font-weight: 600; }
h1 { font-size: 30px; line-height: 1.35; margin: 10px 0 18px; }
.meta-bar { display: flex; flex-wrap: wrap; gap: 10px 26px; padding: 14px 0;
            border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
            color: var(--muted); font-size: 14px; }
.meta-bar b { color: var(--ink); font-weight: 600; }
h2 { font-size: 19px; margin: 34px 0 12px; padding-left: 10px;
     border-left: 4px solid var(--brand); }
.overview { color: #374151; }
.day { border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; margin: 16px 0;
       break-inside: avoid; }
.day h3 { margin: 0 0 12px; font-size: 16px; color: var(--brand); }
.period { display: flex; gap: 12px; padding: 6px 0; }
.period-label { flex: 0 0 54px; color: var(--muted); font-size: 13px; padding-top: 2px; }
.period-body { flex: 1; }
.activity { font-weight: 500; }
.cost { color: #b45309; font-weight: 600; margin-left: 6px; }
.meta { color: var(--muted); font-size: 13px; }
.day-foot { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--line);
            color: #4b5563; font-size: 13px; }
.cost-box { background: #f0fdfa; border: 1px solid #ccfbf1; border-radius: 10px;
            padding: 16px 20px; }
.cost-total { font-size: 24px; font-weight: 700; color: var(--brand); }
.notes { background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px;
         padding: 16px 20px; white-space: pre-wrap; }
.quote { background: #f8fafc; border-left: 3px solid #94a3b8; padding: 12px 16px; color: #475569; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line);
         color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; }
@media print {
  body { background: #fff; padding: 0; }
  .page { box-shadow: none; border-radius: 0; padding: 0; max-width: none; }
  .day { break-inside: avoid; }
}
@page { size: A4; margin: 16mm; }
"""


def _esc(value: Any) -> str:
    """HTML 转义，防止客户内容里的特殊字符破坏页面。"""
    return html.escape("" if value is None else str(value))


def _period_html(label: str, period: Any) -> str:
    if not isinstance(period, dict) or not period.get("activity"):
        return ""
    cost = _to_number(period.get("cost_est"))
    cost_html = f'<span class="cost">¥{cost:,.0f}</span>' if cost > 0 else ""
    meta_parts = []
    if period.get("location"):
        meta_parts.append(f"📍 {_esc(period['location'])}")
    if period.get("note"):
        meta_parts.append(f"💡 {_esc(period['note'])}")
    meta_html = f'<div class="meta">{" ".join(meta_parts)}</div>' if meta_parts else ""
    return (
        f'<div class="period"><div class="period-label">{_esc(label)}</div>'
        f'<div class="period-body"><div class="activity">{_esc(period["activity"])}'
        f'{cost_html}</div>{meta_html}</div></div>'
    )


def export_to_html(itinerary_id: int) -> str:
    """
    导出一份客户可直接阅读的 HTML 方案（不含顾问内部备注）。

    浏览器打开后可直接打印/另存为 PDF，不需要任何外部资源，适合微信/邮件交付。
    """
    itinerary = get_itinerary(itinerary_id)
    if not itinerary:
        return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><h1>方案不存在</h1></html>"

    try:
        content = json.loads(itinerary["content_json"])
    except (json.JSONDecodeError, TypeError):
        content = {}
    if not isinstance(content, dict):
        content = {}

    title = content.get("title") or "行程方案"
    budget = _to_number(itinerary.get("total_budget"))
    meta_bar = [
        f"<span>客户：<b>{_esc(itinerary.get('client_name', ''))}</b></span>",
        f"<span>目的地：<b>{_esc(itinerary.get('destination', ''))}</b></span>",
        f"<span>天数：<b>{_esc(itinerary.get('travel_days', ''))} 天</b></span>",
        f"<span>人数：<b>{_esc(itinerary.get('traveler_count', ''))} 人</b></span>",
    ]
    if budget > 0:
        meta_bar.append(f"<span>预算：<b>¥{budget:,.0f}</b></span>")

    body = [
        '<div class="page">',
        '<div class="brand">SMART ITINERARY · 定制行程方案</div>',
        f"<h1>{_esc(title)}</h1>",
        f'<div class="meta-bar">{"".join(meta_bar)}</div>',
    ]

    if content.get("overview"):
        body.append("<h2>行程概述</h2>")
        body.append(f'<div class="overview">{_esc(content["overview"])}</div>')

    daily_plan = content.get("daily_plan") or []
    if daily_plan:
        body.append("<h2>每日行程</h2>")
        for day in daily_plan:
            if not isinstance(day, dict):
                continue
            body.append('<div class="day">')
            day_label = day.get("date_desc") or f"第{day.get('day', 1)}天"
            body.append(f"<h3>{_esc(day_label)}</h3>")
            body.append(_period_html("上午", day.get("morning")))
            body.append(_period_html("下午", day.get("afternoon")))
            body.append(_period_html("晚上", day.get("evening")))
            foot = []
            if day.get("accommodation"):
                foot.append(f"🏨 住宿：{_esc(day['accommodation'])}")
            if day.get("meals"):
                foot.append(f"🍽️ 餐饮：{_esc(day['meals'])}")
            if day.get("transport"):
                foot.append(f"🚗 交通：{_esc(day['transport'])}")
            if foot:
                body.append(f'<div class="day-foot">{" &nbsp;|&nbsp; ".join(foot)}</div>')
            body.append("</div>")

    total_cost = _to_number(content.get("total_cost_est"))
    if total_cost > 0:
        body.append("<h2>费用估算</h2>")
        body.append('<div class="cost-box">')
        body.append(f'<div>费用合计：<span class="cost-total">¥{total_cost:,.0f}</span></div>')
        if content.get("cost_breakdown"):
            body.append(f'<div class="meta">{_esc(content["cost_breakdown"])}</div>')
        body.append("</div>")

    if content.get("notes"):
        body.append("<h2>出行注意事项</h2>")
        body.append(f'<div class="notes">{_esc(content["notes"])}</div>')

    if content.get("client_talk"):
        body.append("<h2>给客户的说明</h2>")
        body.append(f'<div class="quote">{_esc(content["client_talk"])}</div>')

    if content.get("alternative_routes"):
        body.append("<h2>备选方案</h2>")
        body.append(f"<div>{_esc(content['alternative_routes'])}</div>")

    body.append(
        f"<footer><span>本方案由智能行程方案生成系统生成</span>"
        f"<span>版本 v{_esc(itinerary.get('version', 1))}</span></footer>"
    )
    body.append("</div>")

    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_CUSTOMER_CSS}</style></head>"
        f"<body>{''.join(body)}</body></html>"
    )
