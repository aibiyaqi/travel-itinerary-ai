"""
智能行程方案生成系统 — Streamlit 主应用模块

B端旅行社/研学机构智能行程方案生成系统。
替代原 C端 AI旅行智能助手。

核心页面：
  1. 登录页（顾问/管理员）
  2. 需求录入页（标准化表单 → AI生成）
  3. 方案列表页（查看/管理所有方案）
  4. 方案详情页（查看/修改/导出）
  5. 管理面板（管理员：模板库管理 + 顾问管理）
"""
import sys
from pathlib import Path

# ── 将项目根目录和 src 目录加入 Python 路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import json
import os
import logging
from datetime import datetime

# ── Windows 编码修复 ──
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import streamlit as st

from config import (
    DATA_DIR, UPLOAD_DIR, CHROMA_DB_DIR, DB_PATH, TEMPLATE_DIR,
    TRAVEL_TYPES, PREFERENCE_OPTIONS, ITINERARY_STATUS_OPTIONS,
    CURRENT_DATE, ALLOW_SELF_REGISTER,
)
from db_service import (
    init_db, init_admin,
    register_user, verify_user, user_exists, list_all_users, update_password,
    create_client, get_client, list_clients,
    create_requirement, get_requirement, list_requirements,
    create_itinerary, get_itinerary, list_itineraries,
    update_itinerary, update_itinerary_status, delete_itinerary,
    get_version_history, get_version,
    create_auth_token, verify_auth_token, delete_auth_token,
    can_access_itinerary, log_action, list_audit_logs,
)
from rag_chain import generate_itinerary, modify_itinerary
from export_service import export_to_markdown, export_to_text, export_to_html


# =====================================================================
# 日志配置
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("travel_assistant.app")


# =====================================================================
# 常量
# =====================================================================

APP_TITLE = "🏢 智能行程方案生成系统"
APP_SUBTITLE = "旅行社 · 研学机构 · 智能提效"


# =====================================================================
# 工具函数
# =====================================================================

def reset_session_state():
    """清除所有会话状态（退出登录时调用）。"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def nav_to(page: str):
    """导航到指定页面。"""
    st.session_state.current_page = page
    st.rerun()


def _as_number(value, default: float = 0.0) -> float:
    """把 LLM 可能返回的 "55元"/None 等值安全转成数字，避免格式化崩溃。"""
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


# =====================================================================
# 登录页
# =====================================================================

def render_login_page():
    """登录页面渲染（顾问/管理员登录）。"""
    st.markdown("""
    <style>
        .stApp {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        }
        .brand-header {
            text-align: center;
            padding: 2.5rem 0 1.5rem 0;
        }
        .brand-header .logo {
            font-size: 3.5rem;
            margin-bottom: 0.3rem;
        }
        .brand-header h1 {
            font-size: 2rem;
            font-weight: 700;
            color: #1a1a2e;
            margin: 0.3rem 0;
        }
        .brand-header p {
            font-size: 0.95rem;
            color: #666;
            margin: 0.2rem 0 0 0;
        }
        .auth-container {
            max-width: 440px;
            margin: 0 auto;
            padding: 0 1rem;
        }
        .auth-card {
            background: white;
            border-radius: 16px;
            padding: 2rem 2rem 1.5rem 2rem;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stForm {border: none !important; padding: 0 !important;}
        .stButton button {
            border-radius: 8px;
            font-weight: 600;
            height: 2.8rem;
        }
        .footer-text {
            text-align: center;
            color: #999;
            font-size: 0.8rem;
            margin-top: 1.5rem;
            padding-bottom: 2rem;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 0; }
        .stTabs [data-baseweb="tab"] {
            height: 2.8rem;
            font-weight: 500;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="brand-header">
        <div class="logo">🏢</div>
        <h1>智能行程方案生成系统</h1>
        <p>旅行社 · 研学机构 · 智能提效</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="auth-container"><div class="auth-card">', unsafe_allow_html=True)

    tabs = st.tabs(["🔑 登录", "📝 注册"] if ALLOW_SELF_REGISTER else ["🔑 登录"])
    tab1 = tabs[0]

    # ── 登录 ──
    with tab1:
        with st.form("login_form"):
            username = st.text_input("用户名", placeholder="请输入用户名")
            password = st.text_input("密码", type="password", placeholder="请输入密码")
            submitted = st.form_submit_button("登 录", use_container_width=True)

            if submitted:
                if not username or not password:
                    st.error("⚠️ 请填写用户名和密码")
                else:
                    result = verify_user(username, password)
                    if result:
                        # 创建持久化 Token（页面刷新时恢复登录状态）
                        token = create_auth_token(result["user_id"])
                        st.query_params["auth_token"] = token
                        st.session_state.user_id = result["user_id"]
                        st.session_state.username = result["username"]
                        st.session_state.role = result["role"]
                        st.session_state.is_admin = result["is_admin"]
                        st.session_state.current_page = "requirement_form"
                        log_action(
                            result["user_id"], "login",
                            detail="登录成功", username=result["username"],
                        )
                        st.success(f"👋 欢迎回来，{username}！")
                        st.rerun()
                    else:
                        log_action(
                            None, "login_failed",
                            detail="用户名或密码错误", username=username,
                        )
                        st.error("❌ 用户名或密码错误")

    # ── 注册（默认关闭，仅内部演示时通过 ALLOW_SELF_REGISTER=true 开启） ──
    if ALLOW_SELF_REGISTER:
        with tabs[1]:
            with st.form("register_form"):
                reg_username = st.text_input("用户名", placeholder="3-20位字母或数字")
                reg_password = st.text_input("密码", type="password", placeholder="至少6位字符")
                reg_password2 = st.text_input("确认密码", type="password", placeholder="再次输入密码")
                reg_email = st.text_input("邮箱（选填）", placeholder="example@email.com")
                reg_submitted = st.form_submit_button("创建账号", use_container_width=True)

                if reg_submitted:
                    errors = []
                    if not reg_username or not reg_password:
                        errors.append("用户名和密码为必填项")
                    if reg_username and (len(reg_username) < 3 or len(reg_username) > 20):
                        errors.append("用户名长度需在 3-20 个字符之间")
                    if reg_password and len(reg_password) < 6:
                        errors.append("密码至少 6 位")
                    if reg_password != reg_password2:
                        errors.append("两次密码输入不一致")
                    if reg_username and user_exists(reg_username):
                        errors.append("用户名已被注册")

                    if errors:
                        for err in errors:
                            st.error(f"⚠️ {err}")
                    else:
                        ok = register_user(reg_username, reg_password, reg_email)
                        if ok:
                            st.success("✅ 注册成功！请切换到「登录」标签页登录")
                        else:
                            st.error("❌ 注册失败，请稍后重试")
    else:
        st.caption("账号由管理员统一开通，如需使用请联系管理员。")

    st.markdown('</div></div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="footer-text">
        智能行程方案生成系统 · 基于 LangChain + 通义千问
    </div>
    """, unsafe_allow_html=True)


# =====================================================================
# 侧边栏导航
# =====================================================================

def render_sidebar():
    """渲染侧边栏导航菜单。"""
    with st.sidebar:
        st.markdown(f"### 🏢 {st.session_state.get('username', '用户')}")
        role_label = "👑 管理员" if st.session_state.get("is_admin") else "👤 旅行顾问"
        st.markdown(f"**{role_label}**")
        st.markdown("---")

        # 导航菜单
        nav_items = [
            ("requirement_form", "📋", "需求录入"),
            ("itinerary_list", "📄", "方案列表"),
        ]
        if st.session_state.get("is_admin"):
            nav_items.append(("admin_panel", "⚙️", "系统管理"))

        for page_id, icon, label in nav_items:
            btn_type = "primary" if st.session_state.get("current_page") == page_id else "secondary"
            if st.button(f"{icon} {label}", use_container_width=True,
                         key=f"nav_{page_id}", type=btn_type):
                nav_to(page_id)

        st.markdown("---")
        st.markdown(f"📅 **日期:** {CURRENT_DATE}")

        if st.button("🚪 退出登录", use_container_width=True):
            # 清除服务端 Token
            auth_token = st.query_params.get("auth_token")
            if auth_token:
                delete_auth_token(auth_token)
            log_action(
                st.session_state.get("user_id"), "logout",
                username=st.session_state.get("username", ""),
                detail="退出登录",
            )
            st.query_params.clear()
            reset_session_state()
            st.rerun()


# =====================================================================
# 需求录入页
# =====================================================================

def render_requirement_form():
    """需求录入页面 — 标准化表单 + AI生成方案。"""
    st.header("📋 客户需求录入")
    st.caption("填写客户出行需求，AI 将自动生成结构化行程方案")

    # 客户信息
    st.subheader("1️⃣ 客户信息")
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("客户名称 *", placeholder="请输入客户姓名/公司名",
                                    key="req_client_name")
    with col2:
        client_phone = st.text_input("联系电话", placeholder="选填",
                                     key="req_client_phone")

    # 行程需求
    st.subheader("2️⃣ 行程需求")
    col1, col2, col3 = st.columns(3)
    with col1:
        destination = st.text_input("目的地 *", placeholder="如：桂林、云南",
                                    key="req_destination")
    with col2:
        travel_days = st.number_input("出行天数 *", min_value=1, max_value=30,
                                      value=3, key="req_days")
    with col3:
        traveler_count = st.number_input("出行人数 *", min_value=1, max_value=100,
                                         value=2, key="req_people")

    col1, col2 = st.columns(2)
    with col1:
        total_budget = st.number_input("总预算（元）", min_value=0, max_value=999999,
                                       value=0, step=1000,
                                       help="0表示预算待定",
                                       key="req_budget")
    with col2:
        travel_type = st.selectbox("出行类型 *", options=TRAVEL_TYPES, index=1,
                                   key="req_type")

    preferences = st.multiselect(
        "偏好（可多选）", options=PREFERENCE_OPTIONS,
        default=["自然风光"],
        key="req_preferences",
    )

    special_requirements = st.text_area(
        "特殊要求",
        placeholder="如：老人/儿童适配、低强度路线、纯玩无购物、深度游...",
        key="req_special",
    )

    # 提交按钮
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        submitted = st.button("🚀 AI 生成行程方案", use_container_width=True,
                              type="primary")

    if submitted:
        errors = []
        if not client_name.strip():
            errors.append("请填写客户名称")
        if not destination.strip():
            errors.append("请填写目的地")
        if not travel_type:
            errors.append("请选择出行类型")

        if errors:
            for err in errors:
                st.error(f"⚠️ {err}")
        else:
            with st.spinner("🤖 AI 正在思考并生成行程方案..."):
                try:
                    # 1. 创建/获取客户
                    clients = list_clients(search=client_name.strip())
                    existing_client = None
                    for c in clients:
                        if c["name"] == client_name.strip():
                            existing_client = c
                            break

                    if existing_client:
                        client_id = existing_client["id"]
                    else:
                        client_id = create_client(
                            name=client_name.strip(),
                            phone=client_phone.strip(),
                        )

                    # 2. 保存需求
                    consultant_id = st.session_state.user_id
                    req_id = create_requirement(
                        client_id=client_id,
                        consultant_id=consultant_id,
                        destination=destination.strip(),
                        travel_days=int(travel_days),
                        traveler_count=int(traveler_count),
                        total_budget=float(total_budget) if total_budget > 0 else None,
                        travel_type=travel_type,
                        preferences="、".join(preferences),
                        special_requirements=special_requirements.strip(),
                    )

                    # 3. 构建需求字典传给 AI
                    requirement_dict = {
                        "id": req_id,
                        "client_name": client_name.strip(),
                        "destination": destination.strip(),
                        "travel_days": int(travel_days),
                        "traveler_count": int(traveler_count),
                        "total_budget": float(total_budget) if total_budget > 0 else None,
                        "travel_type": travel_type,
                        "preferences": "、".join(preferences),
                        "special_requirements": special_requirements.strip(),
                    }

                    # 4. 调用 AI 生成
                    result = generate_itinerary(requirement_dict)

                    if result["success"] and result["data"]:
                        content_json = json.dumps(result["data"], ensure_ascii=False)
                        title = result["data"].get("title", "")
                        summary = result["data"].get("overview", "")[:200]

                        # 5. 保存方案到数据库
                        itinerary_id = create_itinerary(
                            requirement_id=req_id,
                            consultant_id=consultant_id,
                            content_json=content_json,
                            title=title,
                            summary=summary,
                        )
                        log_action(
                            consultant_id, "generate", "itinerary", itinerary_id,
                            detail=f"{destination.strip()}/{travel_days}天/{travel_type}",
                            username=st.session_state.get("username", ""),
                        )

                        if result.get("degraded"):
                            st.warning("⚠️ AI 返回内容不完整，已保存为待补全草稿，请在详情页人工核对后再交付。")
                        else:
                            st.success("✅ 行程方案生成成功！")
                        # 跳转到方案详情页
                        st.session_state.current_itinerary_id = itinerary_id
                        nav_to("itinerary_detail")
                    else:
                        error_msg = result.get("error", "AI 返回数据异常")
                        st.error(f"❌ 方案生成失败：{error_msg}")

                except Exception as e:
                    st.error(f"❌ 系统错误：{e}")
                    logger.exception("需求录入异常")


# =====================================================================
# 方案列表页
# =====================================================================

def render_itinerary_list():
    """方案列表页面 — 展示所有方案。"""
    st.header("📄 行程方案列表")
    st.caption("查看、管理所有已生成的行程方案")

    consultant_id = st.session_state.get("user_id")
    is_admin = st.session_state.get("is_admin", False)

    # 筛选栏
    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.selectbox(
            "状态筛选",
            options=["全部", "草稿", "已发送", "客户确认", "已取消"],
            index=0,
        )
    with col2:
        if is_admin:
            # 管理员可以看到所有顾问的方案
            pass

    # 状态映射
    status_map = {
        "全部": None,
        "草稿": "draft",
        "已发送": "sent",
        "客户确认": "confirmed",
        "已取消": "cancelled",
    }

    # 查询方案
    filter_status = status_map.get(status_filter)
    if is_admin:
        itineraries = list_itineraries(status=filter_status)
    else:
        itineraries = list_itineraries(consultant_id=consultant_id, status=filter_status)

    if not itineraries:
        st.info("📭 暂无行程方案，请先在「需求录入」页面生成方案。")
        return

    # 表格展示
    for it in itineraries:
        status_text = ITINERARY_STATUS_OPTIONS.get(it["status"], it["status"])
        status_colors = {
            "draft": "🟡",
            "sent": "🔵",
            "confirmed": "🟢",
            "cancelled": "⚪",
        }
        status_icon = status_colors.get(it["status"], "⚪")

        with st.container(border=True):
            col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])

            with col1:
                st.markdown(f"**{it.get('title', '未命名方案')}**")
                st.caption(f"👤 {it.get('client_name', '未知客户')} · 📍 {it.get('destination', '')}")
            with col2:
                st.caption(f"v{it['version']} · {it['created_at'][:10]}")
            with col3:
                st.markdown(f"{status_icon} {status_text}")
            with col4:
                st.caption(f"{it.get('summary', '')[:30]}...")
            with col5:
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("📖 查看", key=f"view_{it['id']}",
                                 use_container_width=True):
                        st.session_state.current_itinerary_id = it["id"]
                        nav_to("itinerary_detail")

                with col_b:
                    menu_key = f"menu_{it['id']}"
                    # 状态切换
                    current_status = it["status"]
                    next_statuses = {
                        "draft": "sent",
                        "sent": "confirmed",
                        "confirmed": "cancelled",
                    }
                    if current_status in next_statuses:
                        next_s = next_statuses[current_status]
                        next_label = {"sent": "标记已发送", "confirmed": "标记已确认",
                                      "cancelled": "标记已取消"}.get(next_s, next_s)
                        if st.button(next_label, key=f"status_{it['id']}",
                                     use_container_width=True):
                            update_itinerary_status(it["id"], next_s)
                            log_action(
                                st.session_state.get("user_id"), "status",
                                "itinerary", it["id"],
                                detail=f"{current_status} -> {next_s}",
                                username=st.session_state.get("username", ""),
                            )
                            st.rerun()


# =====================================================================
# 方案详情页
# =====================================================================

def render_itinerary_detail():
    """方案详情页面 — 查看/修改/导出方案。"""
    itinerary_id = st.session_state.get("current_itinerary_id")
    if not itinerary_id:
        st.warning("请选择一个方案查看")
        nav_to("itinerary_list")
        return

    # 加载方案
    itinerary = get_itinerary(itinerary_id)
    if not itinerary:
        st.error("方案不存在或已被删除")
        nav_to("itinerary_list")
        return

    # 归属校验：顾问只能看自己的方案，管理员可看全部
    if not can_access_itinerary(
        itinerary,
        st.session_state.get("user_id", 0),
        st.session_state.get("is_admin", False),
    ):
        st.error("⛔ 无权访问该方案")
        nav_to("itinerary_list")
        return

    # 解析 JSON 内容
    try:
        content = json.loads(itinerary["content_json"])
        if not isinstance(content, dict):
            raise ValueError("方案内容不是 JSON 对象")
    except (json.JSONDecodeError, TypeError, ValueError):
        content = None
        st.error("方案数据格式异常")

    if content and (content.get("degraded") or content.get("incomplete")):
        st.warning(
            "⚠️ 该方案由降级兜底生成或存在缺失日程，请人工核查补全后再交付客户。"
        )

    # ── 操作按钮行 ──
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 3])
    with col1:
        if st.button("← 返回列表", use_container_width=True):
            nav_to("itinerary_list")
    with col2:
        status_text = ITINERARY_STATUS_OPTIONS.get(itinerary["status"], itinerary["status"])
        st.markdown(f"**状态:** {status_text}")
    with col3:
        st.markdown(f"**版本:** v{itinerary['version']}")
    with col4:
        # 复制到剪贴板
        md_text = export_to_markdown(itinerary_id)
        st.code(md_text[:100] + "...", language="markdown")

    # ── 方案标题和概述 ──
    if content:
        st.markdown("---")
        st.markdown(f"# {content.get('title', '')}")
        st.markdown(f"> **客户:** {itinerary.get('client_name', '')}  |  "
                    f"**目的地:** {itinerary.get('destination', '')}  |  "
                    f"**天数:** {itinerary.get('travel_days', '')}天  |  "
                    f"**人数:** {itinerary.get('traveler_count', '')}人")
        if _as_number(itinerary.get("total_budget")) > 0:
            st.markdown(f"> **预算:** ¥{_as_number(itinerary['total_budget']):.0f}  |  "
                        f"**类型:** {itinerary.get('travel_type', '')}")

        if content.get("overview"):
            st.markdown(f"### 📝 行程概述")
            st.markdown(content["overview"])

        # ── 每日行程 ──
        st.markdown("### 📅 每日行程安排")

        for day_plan in content.get("daily_plan", []):
            day_num = day_plan.get("day", 1)
            date_desc = day_plan.get("date_desc", f"第{day_num}天")

            with st.expander(f"**{date_desc}** — {day_plan.get('morning', {}).get('activity', '')[:20]}...",
                             expanded=(day_num == 1)):
                for period_name, period_label in [("morning", "🌅 上午"),
                                                   ("afternoon", "☀️ 下午"),
                                                   ("evening", "🌙 晚上")]:
                    period_data = day_plan.get(period_name, {})
                    if isinstance(period_data, dict) and period_data.get("activity"):
                        cost = _as_number(period_data.get("cost_est", 0))
                        cost_str = f"¥{cost:.0f}" if cost > 0 else ""
                        st.markdown(f"**{period_label}**: {period_data['activity']}")
                        st.caption(f"📍 {period_data.get('location', '')}  "
                                   f"{cost_str}  "
                                   f"💡 {period_data.get('note', '')}")
                    elif isinstance(period_data, str) and period_data:
                        st.markdown(f"**{period_label}**: {period_data}")

                st.markdown(f"**🏨 住宿**: {day_plan.get('accommodation', '')}")
                st.markdown(f"**🍽️ 餐饮**: {day_plan.get('meals', '')}")
                st.markdown(f"**🚗 交通**: {day_plan.get('transport', '')}")

        # ── 费用 ──
        st.markdown("---")
        st.markdown("### 💰 费用估算")
        total_cost = _as_number(content.get("total_cost_est"))
        st.markdown(f"**总计:** ¥{total_cost:,.0f}")
        if content.get("cost_breakdown"):
            st.markdown(f"**明细:** {content['cost_breakdown']}")

        # ── 注意事项 ──
        if content.get("notes"):
            st.markdown("### ⚠️ 出行注意事项")
            st.markdown(content["notes"])

        # ── 客户话术 ──
        if content.get("client_talk"):
            with st.expander("💬 客户对外介绍话术（可复制发送给客户）"):
                st.markdown(content["client_talk"])

        # ── 内部备注 ──
        if content.get("internal_notes"):
            with st.expander("📌 顾问内部备注"):
                st.markdown(content["internal_notes"])

        # ── 备选路线 ──
        if content.get("alternative_routes"):
            with st.expander("🔄 备选路线建议"):
                st.markdown(content["alternative_routes"])

    # ── 底部操作 ──
    st.markdown("---")
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button("📝 修改方案", use_container_width=True, type="primary",
                     key="btn_modify"):
            st.session_state.modify_mode = True
            st.rerun()

    with col2:
        md_export = export_to_markdown(itinerary_id)
        if st.button("📥 导出 Markdown", use_container_width=True,
                     key="btn_export_md"):
            os.makedirs("exports", exist_ok=True)
            safe_title = content.get("title", "行程方案")[:30] if content else "行程方案"
            safe_title = "".join(c for c in safe_title if c.isalnum() or c in " _-")
            filepath = f"exports/{safe_title}_v{itinerary['version']}.md"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md_export)
            log_action(
                st.session_state.get("user_id"), "export", "itinerary", itinerary_id,
                detail="markdown", username=st.session_state.get("username", ""),
            )
            st.success(f"✅ 已导出到 {filepath}")
            # 提供下载
            st.download_button(
                label="⬇️ 下载文件",
                data=md_export.encode("utf-8"),
                file_name=f"{safe_title}_v{itinerary['version']}.md",
                mime="text/markdown",
                use_container_width=True,
            )

    with col3:
        text_export = export_to_text(itinerary_id)
        if st.button("📋 复制纯文本", use_container_width=True,
                     key="btn_copy_text"):
            st.code(text_export[:500] + "...\n\n（完整内容请在导出 Markdown 中查看）",
                    language="text")

    with col4:
        # 版本历史
        versions = get_version_history(itinerary_id)
        if len(versions) > 1:
            with st.popover(f"📚 版本历史 (共{len(versions)}版)"):
                for v in versions:
                    st.markdown(f"**v{v['version']}** — {v['created_at'][:16]}")
                    if v.get("change_log"):
                        st.caption(f"变更: {v['change_log']}")
                    st.markdown("---")

    with col5:
        # 客户版 HTML（可直接发客户 / 浏览器打印为 PDF）
        if st.button("🌐 客户版 HTML", use_container_width=True,
                     key="btn_export_html"):
            html_doc = export_to_html(itinerary_id)
            os.makedirs("exports", exist_ok=True)
            html_title = content.get("title", "行程方案")[:30] if content else "行程方案"
            html_title = "".join(c for c in html_title if c.isalnum() or c in " _-") or "行程方案"
            html_path = f"exports/{html_title}_v{itinerary['version']}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_doc)
            log_action(
                st.session_state.get("user_id"), "export", "itinerary", itinerary_id,
                detail="html", username=st.session_state.get("username", ""),
            )
            st.success(f"✅ 已生成 {html_path}")
            st.download_button(
                label="⬇️ 下载 HTML",
                data=html_doc.encode("utf-8"),
                file_name=f"{html_title}_v{itinerary['version']}.html",
                mime="text/html",
                use_container_width=True,
            )

    # ── 修改模式 ──
    if st.session_state.get("modify_mode", False):
        st.markdown("---")
        st.markdown("### ✏️ 修改方案")
        st.caption("输入修改意见，AI 将基于当前方案进行调整")

        user_feedback = st.text_area(
            "修改意见 *",
            placeholder="如：预算减少到3000元 / 增加第2天的景点 / 换成轻松休闲风格...",
            height=100,
            key="modify_feedback",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 确认修改", use_container_width=True, type="primary",
                         key="btn_confirm_modify"):
                if not user_feedback.strip():
                    st.error("请填写修改意见")
                else:
                    with st.spinner("🤖 AI 正在修改方案..."):
                        try:
                            # 获取需求信息
                            req = get_requirement(itinerary["requirement_id"])
                            requirement_dict = {
                                "id": req["id"],
                                "client_name": req.get("client_name", ""),
                                "destination": req["destination"],
                                "travel_days": req["travel_days"],
                                "traveler_count": req["traveler_count"],
                                "total_budget": req["total_budget"],
                                "travel_type": req["travel_type"],
                                "preferences": req["preferences"],
                                "special_requirements": req["special_requirements"],
                            }

                            result = modify_itinerary(
                                requirement=requirement_dict,
                                current_content=content,
                                user_feedback=user_feedback.strip(),
                            )

                            if result["success"] and result["data"]:
                                new_content_json = json.dumps(result["data"], ensure_ascii=False)
                                new_title = result["data"].get("title", "")
                                new_summary = result["data"].get("overview", "")[:200]

                                update_itinerary(
                                    itinerary_id=itinerary_id,
                                    content_json=new_content_json,
                                    title=new_title,
                                    summary=new_summary,
                                    change_log=user_feedback.strip()[:200],
                                    consultant_id=st.session_state.user_id,
                                )
                                log_action(
                                    st.session_state.user_id, "modify", "itinerary",
                                    itinerary_id,
                                    detail=user_feedback.strip()[:200],
                                    username=st.session_state.get("username", ""),
                                )

                                st.success("✅ 方案修改成功！")
                                st.session_state.modify_mode = False
                                st.rerun()
                            else:
                                st.error(f"❌ 修改失败：{result.get('error', '未知错误')}")

                        except Exception as e:
                            st.error(f"❌ 系统错误：{e}")
                            logger.exception("方案修改异常")

        with col2:
            if st.button("取消修改", use_container_width=True,
                         key="btn_cancel_modify"):
                st.session_state.modify_mode = False
                st.rerun()


# =====================================================================
# 管理面板
# =====================================================================

def render_admin_panel():
    """管理员面板 — 用户管理 + 知识库管理。"""
    st.header("⚙️ 系统管理")
    st.caption("管理员专属面板")

    tab1, tab2, tab3 = st.tabs(["👥 顾问管理", "📚 知识库管理", "🧾 操作日志"])

    # ── Tab 1: 顾问管理 ──
    with tab1:
        st.subheader("注册顾问列表")
        users = list_all_users()
        for u in users:
            role_icon = "👑" if u["is_admin"] else "👤"
            role_label = "管理员" if u["is_admin"] else "顾问"
            st.markdown(f"{role_icon} **{u['username']}** — {role_label} "
                        f"— 注册于 {u['created_at'][:10]}")

        st.markdown("---")
        st.subheader("创建新顾问账号")
        with st.form("create_consultant"):
            new_user = st.text_input("用户名", placeholder="3-20位字母或数字")
            new_pass = st.text_input("密码", type="password", placeholder="至少6位")
            new_pass2 = st.text_input("确认密码", type="password")
            col1, col2 = st.columns(2)
            with col1:
                is_admin_check = st.checkbox("设置为管理员")
            with col2:
                pass
            if st.form_submit_button("创建账号", use_container_width=True):
                errors = []
                if not new_user or not new_pass:
                    errors.append("请填写完整")
                elif len(new_user) < 3:
                    errors.append("用户名至少3位")
                elif len(new_pass) < 6:
                    errors.append("密码至少6位")
                elif new_pass != new_pass2:
                    errors.append("两次密码不一致")
                elif user_exists(new_user):
                    errors.append("用户名已存在")

                if errors:
                    for err in errors:
                        st.error(f"⚠️ {err}")
                else:
                    role = "admin" if is_admin_check else "consultant"
                    ok = register_user(new_user, new_pass, role=role)
                    if ok:
                        log_action(
                            st.session_state.get("user_id"), "create_user", "user",
                            detail=f"{new_user} role={role}",
                            username=st.session_state.get("username", ""),
                        )
                        st.success("✅ 账号创建成功！")
                        st.rerun()
                    else:
                        st.error("❌ 创建失败，请稍后重试")

    # ── Tab 2: 知识库管理 ──
    with tab2:
        st.subheader("模板知识库管理")
        st.caption("上传业务模板文件（景点资料、路线模板、安全提示等），"
                   "AI 生成方案时将参考这些模板。")

        # 显示现有知识库
        try:
            from data_loader import list_knowledge_bases
            kbs = list_knowledge_bases()
            if kbs:
                st.markdown("**现有知识库:**")
                for name, display in kbs:
                    st.markdown(f"- {display}")
            else:
                st.info("暂无知识库，请上传模板文件")
        except Exception as e:
            st.warning(f"无法加载知识库列表: {e}")

        # 上传文件
        uploaded_file = st.file_uploader(
            "上传模板文件（支持 PDF / JSONL / CSV）",
            type=["pdf", "jsonl", "csv"],
            key="admin_upload",
        )

        if uploaded_file is not None:
            try:
                from data_loader import process_file
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                kb_name = os.path.splitext(uploaded_file.name)[0]
                with st.spinner(f"⏳ 正在构建知识库 [{kb_name}]..."):
                    vector_store = process_file(file_path, persist_subdir=kb_name)
                    log_action(
                        st.session_state.get("user_id"), "upload_kb", "knowledge_base",
                        detail=uploaded_file.name,
                        username=st.session_state.get("username", ""),
                    )
                    st.success(f"✅ 知识库 [{kb_name}] 构建完成！")
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 处理失败: {e}")

    # ── Tab 3: 操作日志 ──
    with tab3:
        st.subheader("操作日志")
        st.caption(
            "记录登录、生成、修改、状态变更、导出、建号、上传等关键动作；"
            "时间按 UTC 存储。"
        )
        audit_labels = {
            "login": "登录",
            "login_failed": "登录失败",
            "logout": "退出登录",
            "generate": "生成方案",
            "modify": "修改方案",
            "status": "状态变更",
            "export": "导出交付",
            "create_user": "创建账号",
            "upload_kb": "上传知识库",
        }
        selected = st.selectbox(
            "动作筛选",
            ["全部"] + list(audit_labels.values()),
            key="audit_action_filter",
        )
        action_key = None
        if selected != "全部":
            action_key = next(
                key for key, label in audit_labels.items() if label == selected
            )
        logs = list_audit_logs(limit=200, action=action_key)
        if not logs:
            st.info("暂无操作日志")
        else:
            rows = []
            for item in logs:
                target = ""
                if item.get("target_type"):
                    target = f"{item['target_type']}"
                    if item.get("target_id"):
                        target += f"#{item['target_id']}"
                rows.append({
                    "时间(UTC)": item.get("created_at", ""),
                    "用户": item.get("username") or "-",
                    "动作": audit_labels.get(item.get("action", ""), item.get("action", "")),
                    "对象": target,
                    "详情": item.get("detail", ""),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption(f"最近 {len(rows)} 条（最多 200 条）")


# =====================================================================
# 主入口
# =====================================================================

@st.cache_resource
def _bootstrap():
    """初始化数据库、管理员账号与内置模板（进程内只执行一次）。"""
    init_db()
    init_admin()
    try:
        # 首次启动自动把 data/business_templates 导入独立知识库；已是最新则跳过
        from data_loader import seed_builtin_templates

        seed_builtin_templates()
    except Exception:
        logger.warning("内置模板自动入库失败，可在系统管理中手动上传模板", exc_info=True)


def main():
    """Streamlit 主入口。"""
    # 页面配置（必须是第一个 Streamlit 调用）
    st.set_page_config(
        page_title="智能行程方案生成系统",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 初始化数据库和管理员账号（进程内只执行一次）
    _bootstrap()

    # 未登录 → 尝试从 URL Token 恢复会话
    if "user_id" not in st.session_state:
        auth_token = st.query_params.get("auth_token")
        if auth_token:
            user = verify_auth_token(auth_token)
            if user:
                st.session_state.user_id = user["user_id"]
                st.session_state.username = user["username"]
                st.session_state.role = user["role"]
                st.session_state.is_admin = user["is_admin"]
                st.session_state.current_page = "requirement_form"
                st.rerun()
            else:
                # Token 过期或无效 → 清除
                del st.query_params["auth_token"]
                render_login_page()
                return
        else:
            render_login_page()
            return

    # 默认页面
    if "current_page" not in st.session_state:
        st.session_state.current_page = "requirement_form"

    # 渲染侧边栏
    render_sidebar()

    # 路由到对应页面
    page = st.session_state.current_page
    if page == "requirement_form":
        render_requirement_form()
    elif page == "itinerary_list":
        render_itinerary_list()
    elif page == "itinerary_detail":
        render_itinerary_detail()
    elif page == "admin_panel":
        if st.session_state.get("is_admin"):
            render_admin_panel()
        else:
            st.error("无权限访问管理面板")
            nav_to("requirement_form")


if __name__ == "__main__":
    main()
