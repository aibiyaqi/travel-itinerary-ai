"""
智能行程生成模块 — B端旅行社/研学机构结构化行程方案生成

核心能力:
  1. 根据客户需求生成结构化行程方案（JSON）
  2. 支持多轮修改重生成（保留版本历史）
  3. 结合内置模板知识库提升生成质量
  4. 输出严格的 JSON 格式，便于前端渲染

依赖:
  - 通义千问 qwen-max (DashScope OpenAI 兼容接口)
  - langchain_openai.ChatOpenAI
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI

from src.config import (
    QWEN_API_KEY, QWEN_MODEL, QWEN_API_BASE,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT, LLM_MAX_RETRIES,
    CURRENT_DATE, RERANK_ENABLED,
    QWEN_PRICE_INPUT, QWEN_PRICE_OUTPUT,
)

logger = logging.getLogger("travel_assistant.rag_chain")


# =====================================================================
# 系统角色定义 — B端行程规划专家
# =====================================================================

SYSTEM_PROMPT = """你是 **智能行程规划专家**，服务于旅行社和研学机构的行程顾问。

## 你的身份
- 你是一位经验丰富的旅行社/研学机构高级行程规划师。
- 你的任务是根据客户需求和公司模板库，生成可直接交付客户的结构化行程方案。
- 你输出的方案必须专业、详细、可执行，能够直接提升顾问的工作效率。

## 核心原则
1. **专业可靠**：行程安排合理，时间分配科学，景点选择符合客户偏好。
2. **细节丰富**：每个活动包含具体地点、时间安排、费用估算、实用提示。
3. **可交付**：方案可直接发给客户阅读，包含介绍话术。
4. **预算合理**：总费用估算需与客户预算匹配，给出明细。
5. **安全提示**：包含必要的出行注意事项和安全提醒。

## 输出要求
- 严格按照用户要求的 JSON 结构输出
- 只输出 JSON，不要包含额外解释或说明文字
- 确保 JSON 格式正确，可被 json.loads() 直接解析
- 中文字段内容使用中文"""


# =====================================================================
# 行程结构定义
# =====================================================================

ITINERARY_STRUCTURE_EXAMPLE = {
    "title": "【示例】桂林5天4晚亲子深度游方案",
    "overview": "本方案为XX客户量身定制的桂林5天亲子游...",
    "daily_plan": [
        {
            "day": 1,
            "date_desc": "第1天",
            "morning": {
                "activity": "抵达桂林，入住酒店",
                "location": "桂林市区",
                "cost_est": 0,
                "note": "建议选择桂林市中心酒店，方便出行"
            },
            "afternoon": {
                "activity": "游览象鼻山公园",
                "location": "象鼻山景区",
                "cost_est": 55,
                "note": "桂林标志性景点，约2小时游览时间"
            },
            "evening": {
                "activity": "两江四湖夜游",
                "location": "两江四湖景区",
                "cost_est": 180,
                "note": "夜景非常美，适合家庭出游"
            },
            "accommodation": "桂林市区四星酒店",
            "meals": "早餐：酒店自助 / 午餐：桂林米粉 / 晚餐：特色啤酒鱼",
            "transport": "专车接送"
        }
    ],
    "total_cost_est": 5000,
    "cost_breakdown": "交通：2000元 / 住宿：1500元 / 门票：800元 / 餐饮：700元",
    "notes": "1. 桂林夏季炎热，注意防暑...",
    "client_talk": "您好！这是为您定制的桂林5天亲子游方案...",
    "internal_notes": "客户带一名6岁儿童，需要安排儿童友好项目",
    "alternative_routes": "如时间充裕，可增加龙脊梯田一日游..."
}


# =====================================================================
# Prompt 模板
# =====================================================================

GENERATE_PROMPT_TEMPLATE = """
{system_prompt}

【当前日期】
{CURRENT_DATE}

【客户需求】
- 客户名称：{client_name}
- 目的地：{destination}
- 出行天数：{travel_days}天
- 出行人数：{traveler_count}人
- 总预算：{total_budget}元
- 出行类型：{travel_type}
- 偏好：{preferences}
- 特殊要求：{special_requirements}

【参考模板】
{template_context}

【输出要求】
请严格按照以下 JSON 结构输出方案，只输出 JSON，不要包含任何额外文字：

{{
    "title": "方案标题（包含目的地、天数、类型）",
    "overview": "行程概述（100-200字，简要介绍本次行程特色和亮点）",
    "daily_plan": [
        {{
            "day": 1,
            "date_desc": "第1天",
            "morning": {{"activity": "上午活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "afternoon": {{"activity": "下午活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "evening": {{"activity": "晚上活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "accommodation": "住宿安排",
            "meals": "餐饮安排",
            "transport": "交通方式"
        }}
    ],
    "total_cost_est": 总费用估算(数字),
    "cost_breakdown": "费用明细说明",
    "notes": "出行注意事项和安全提示",
    "client_talk": "面向客户的方案介绍话术（可直接复制发给客户）",
    "internal_notes": "顾问内部备注（仅供内部参考）",
    "alternative_routes": "备选路线建议"
}}

请确保：
1. daily_plan 数组的长度等于出行天数
2. 每个活动的 cost_est 为数字，总费用 total_cost_est 为所有费用之和
3. 行程安排要符合客户偏好和特殊要求
4. 费用估算在客户预算范围内
5. 提供足够实用的细节，让顾问可以直接使用
"""


MODIFY_PROMPT_TEMPLATE = """
{system_prompt}

【当前日期】
{CURRENT_DATE}

【原始需求】
- 客户名称：{client_name}
- 目的地：{destination}
- 出行天数：{travel_days}天
- 出行人数：{traveler_count}人
- 总预算：{total_budget}元
- 出行类型：{travel_type}
- 偏好：{preferences}
- 特殊要求：{special_requirements}

【当前方案内容】
{current_content}

【修改意见】
{user_feedback}

【输出要求】
请根据修改意见，在保留原方案合理部分的基础上进行修改。
请严格按照以下 JSON 结构输出，只输出 JSON，不要包含任何额外文字：

{{
    "title": "方案标题",
    "overview": "行程概述",
    "daily_plan": [
        {{
            "day": 1,
            "date_desc": "第1天",
            "morning": {{"activity": "上午活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "afternoon": {{"activity": "下午活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "evening": {{"activity": "晚上活动", "location": "地点", "cost_est": 费用(数字), "note": "提示"}},
            "accommodation": "住宿安排",
            "meals": "餐饮安排",
            "transport": "交通方式"
        }}
    ],
    "total_cost_est": 总费用估算(数字),
    "cost_breakdown": "费用明细说明",
    "notes": "出行注意事项和安全提示",
    "client_talk": "面向客户的方案介绍话术（可直接复制发给客户）",
    "internal_notes": "顾问内部备注（仅供内部参考）",
    "alternative_routes": "备选路线建议"
}}
"""


# =====================================================================
# LLM 构建
# =====================================================================

def build_llm() -> ChatOpenAI:
    """构建通义千问 LLM 实例。"""
    return ChatOpenAI(
        model=QWEN_MODEL,
        api_key=QWEN_API_KEY,
        base_url=QWEN_API_BASE,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        timeout=LLM_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )


def _log_usage(response: Any, scene: str) -> None:
    """记录 token 用量与估算成本（便于核算每次生成的真实成本）。"""
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = int(usage.get("input_tokens", 0) or 0)
    completion_tokens = int(usage.get("output_tokens", 0) or 0)
    if not prompt_tokens and not completion_tokens:
        return
    cost = prompt_tokens * QWEN_PRICE_INPUT + completion_tokens * QWEN_PRICE_OUTPUT
    logger.info(
        f"[{scene}] token 用量 input={prompt_tokens} output={completion_tokens} "
        f"估算成本=¥{cost:.4f}"
    )


# =====================================================================
# 模板检索（从 Chroma 向量库匹配相关模板）
# =====================================================================

def _retrieve_templates(query_text: str, k: int = 3) -> str:
    """
    从模板知识库检索相关模板，返回格式化的文本。
    如果模板库未加载或检索失败，返回空字符串。
    """
    try:
        from src.data_loader import (
            load_vector_store, list_knowledge_bases, TEMPLATE_KB_NAME,
        )
        from src.retriever import build_hybrid_retriever

        available_kbs = list_knowledge_bases()
        if not available_kbs:
            return ""

        # 知识库选择：优先匹配查询中的知识库名，其次内置模板库，最后取第一个
        kb_names = [entry[0] for entry in available_kbs]
        lowered_query = query_text.lower()
        kb_name = next(
            (name for name in kb_names
             if name != "_default" and name.lower() and name.lower() in lowered_query),
            None,
        )
        if kb_name is None:
            kb_name = TEMPLATE_KB_NAME if TEMPLATE_KB_NAME in kb_names else kb_names[0]

        subdir = kb_name if kb_name != "_default" else None
        vector_store = load_vector_store(subdir)
        if vector_store is None:
            return ""

        # 混合检索（BM25 索引按知识库隔离）
        hybrid_retriever = build_hybrid_retriever(vector_store, subdir=subdir)
        results = hybrid_retriever.search(query_text, k=max(k * 3, k))

        # 可选：Cross-Encoder 精排（默认关闭，开启后首次调用需下载模型）
        if RERANK_ENABLED and len(results) > k:
            from src.retriever import build_reranker

            results = build_reranker().rerank(query_text, results, top_k=k)

        if not results:
            return ""

        parts = []
        for i, (doc, score) in enumerate(results[:k]):
            content = doc.page_content[:500] if hasattr(doc, "page_content") else str(doc)[:500]
            parts.append(f"【模板 {i+1}】\n{content}")

        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"模板检索失败: {e}")
        return ""


# =====================================================================
# JSON 清理与校验
# =====================================================================

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    从 LLM 输出中提取 JSON。
    处理常见问题：```json 包裹、多余文字、尾随逗号等。
    """
    if not text:
        return None

    # 1. 尝试提取 ```json ... ``` 包裹的内容
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    # 2. 找第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    text = text[start:end + 1]

    # 3. 去除尾随逗号（常见 LLM 错误）
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*\]", "]", text)

    # 4. 尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}")
        # 5. 最后一次尝试：使用 ast.literal_eval 兼容 True/False/null
        try:
            import ast
            text_fixed = text.replace("null", "None").replace("true", "True").replace("false", "False")
            result = ast.literal_eval(text_fixed)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return None


def _to_number(value: Any, default: float = 0.0) -> float:
    """把 LLM 可能返回的 "55元" / "约5000" / None / "1,200" 统一成数字。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("，", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return default
    return default


def _empty_day(day_number: int) -> Dict[str, Any]:
    """构造一个空白日程（用于补齐缺失天数）。"""
    return {
        "day": day_number,
        "date_desc": f"第{day_number}天",
        "morning": {"activity": "", "location": "", "cost_est": 0, "note": ""},
        "afternoon": {"activity": "", "location": "", "cost_est": 0, "note": ""},
        "evening": {"activity": "", "location": "", "cost_est": 0, "note": ""},
        "accommodation": "",
        "meals": "",
        "transport": "",
    }


def _validate_itinerary(data: Dict[str, Any], expected_days: int) -> Dict[str, Any]:
    """
    校验行程 JSON 的完整性、类型与天数，并补全缺失字段。

    重点防御：LLM 经常把费用返回成 "55元" 字符串、把时段返回成字符串或 null，
    这些值如果直接进入前端格式化（f"{cost:,.0f}"）会直接抛异常。
    """
    if not isinstance(data, dict):
        data = {}

    # ── 文本字段 ──
    for key in (
        "title", "overview", "cost_breakdown", "notes",
        "client_talk", "internal_notes", "alternative_routes",
    ):
        value = data.get(key)
        if not value:
            data[key] = "行程方案" if key == "title" else ""
        elif not isinstance(value, str):
            data[key] = str(value)

    # ── 每日计划：过滤非字典项 + 类型归一 ──
    raw_plan = data.get("daily_plan")
    plan = raw_plan if isinstance(raw_plan, list) else []
    clean_plan: List[Dict[str, Any]] = []
    dropped = 0
    for index, day_plan in enumerate(plan, start=1):
        if not isinstance(day_plan, dict):
            dropped += 1
            continue
        day_plan["day"] = int(_to_number(day_plan.get("day"), index))
        if day_plan.get("date_desc"):
            day_plan["date_desc"] = str(day_plan["date_desc"])
        else:
            day_plan["date_desc"] = f"第{day_plan['day']}天"

        for period in ("morning", "afternoon", "evening"):
            value = day_plan.get(period)
            if isinstance(value, str):
                value = {"activity": value, "location": "", "cost_est": 0, "note": ""}
            elif not isinstance(value, dict):
                value = {"activity": "", "location": "", "cost_est": 0, "note": ""}
            else:
                for text_key in ("activity", "location", "note"):
                    raw_text = value.get(text_key)
                    value[text_key] = "" if raw_text is None else str(raw_text)
                value["cost_est"] = _to_number(value.get("cost_est"))
            day_plan[period] = value

        for key in ("accommodation", "meals", "transport"):
            raw_text = day_plan.get(key)
            day_plan[key] = "" if raw_text is None else str(raw_text)
        clean_plan.append(day_plan)

    # ── 天数对齐：缺的补空日程，多的截断 ──
    expected = int(_to_number(expected_days, 0))
    incomplete = dropped > 0
    if expected > 0:
        if len(clean_plan) < expected:
            incomplete = True
            for number in range(len(clean_plan) + 1, expected + 1):
                clean_plan.append(_empty_day(number))
        elif len(clean_plan) > expected:
            clean_plan = clean_plan[:expected]
    data["daily_plan"] = clean_plan

    # ── 数值字段 ──
    data["total_cost_est"] = _to_number(data.get("total_cost_est"))

    if incomplete:
        # 标记为不完整，前端会提示人工复核，避免当成完整方案直接交付
        data["incomplete"] = True

    return data


# =====================================================================
# 核心生成函数
# =====================================================================

def generate_itinerary(requirement: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据客户需求生成结构化行程方案。

    参数:
        requirement: 包含以下字段的字典
            - client_name: 客户名称
            - destination: 目的地
            - travel_days: 出行天数
            - traveler_count: 出行人数
            - total_budget: 总预算
            - travel_type: 出行类型
            - preferences: 偏好
            - special_requirements: 特殊要求

    返回:
        {
            "success": bool,
            "data": dict (完整的行程 JSON),
            "error": str (失败时的错误信息),
        }
    """
    # 1. 构建 Prompt
    query_text = (
        f"{requirement.get('destination', '')} "
        f"{requirement.get('travel_type', '')} "
        f"{requirement.get('preferences', '')} "
        f"{requirement.get('travel_days', '')}天行程"
    )

    template_context = _retrieve_templates(query_text)

    # 格式化需求字段
    preferences = requirement.get("preferences", "") or "无特殊偏好"
    special_req = requirement.get("special_requirements", "") or "无"
    budget = requirement.get("total_budget")
    budget_str = f"{budget:.0f}" if budget and budget > 0 else "待定"

    prompt = GENERATE_PROMPT_TEMPLATE.format(
        system_prompt=SYSTEM_PROMPT,
        CURRENT_DATE=CURRENT_DATE,
        client_name=requirement.get("client_name", "客户"),
        destination=requirement.get("destination", ""),
        travel_days=requirement.get("travel_days", 3),
        traveler_count=requirement.get("traveler_count", 2),
        total_budget=budget_str,
        travel_type=requirement.get("travel_type", "亲子"),
        preferences=preferences,
        special_requirements=special_req,
        template_context=template_context or "（暂无匹配模板）",
    )

    # 2. 调用 LLM
    try:
        llm = build_llm()
        logger.info(f"开始生成行程方案: {requirement.get('destination', '')} "
                    f"{requirement.get('travel_days', '')}天 "
                    f"{requirement.get('travel_type', '')}")
        response = llm.invoke(prompt)
        answer = response.content if hasattr(response, "content") else str(response)
        _log_usage(response, "generate")
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return {"success": False, "data": None, "error": f"AI 服务调用失败: {e}", "degraded": False}

    # 3. 提取并校验 JSON
    json_data = _extract_json(answer)
    if json_data is None:
        logger.error(f"JSON 提取失败，原始输出: {answer[:200]}...")
        # 降级：用原始文本构造一个简单方案，并显式标记 degraded 供前端提示
        fallback = _build_fallback_itinerary(requirement, answer)
        fallback["degraded"] = True
        return {"success": True, "data": fallback, "error": None, "degraded": True}

    # 4. 校验完整性
    expected_days = requirement.get("travel_days", 3)
    json_data = _validate_itinerary(json_data, expected_days)

    degraded = bool(json_data.pop("degraded", False)) or bool(json_data.get("incomplete"))
    logger.info(f"行程方案生成成功: {json_data.get('title', '')}")
    return {"success": True, "data": json_data, "error": None, "degraded": degraded}


def modify_itinerary(
    requirement: Dict[str, Any],
    current_content: Dict[str, Any],
    user_feedback: str,
) -> Dict[str, Any]:
    """
    根据用户反馈修改已有行程方案。

    参数:
        requirement: 原始客户需求
        current_content: 当前方案 JSON
        user_feedback: 用户修改意见

    返回:
        {
            "success": bool,
            "data": dict (修改后的行程 JSON),
            "error": str,
        }
    """
    # 1. 构建修改 Prompt
    preferences = requirement.get("preferences", "") or "无特殊偏好"
    special_req = requirement.get("special_requirements", "") or "无"
    budget = requirement.get("total_budget")
    budget_str = f"{budget:.0f}" if budget and budget > 0 else "待定"

    prompt = MODIFY_PROMPT_TEMPLATE.format(
        system_prompt=SYSTEM_PROMPT,
        CURRENT_DATE=CURRENT_DATE,
        client_name=requirement.get("client_name", "客户"),
        destination=requirement.get("destination", ""),
        travel_days=requirement.get("travel_days", 3),
        traveler_count=requirement.get("traveler_count", 2),
        total_budget=budget_str,
        travel_type=requirement.get("travel_type", "亲子"),
        preferences=preferences,
        special_requirements=special_req,
        current_content=json.dumps(current_content, ensure_ascii=False, indent=2),
        user_feedback=user_feedback,
    )

    # 2. 调用 LLM
    try:
        llm = build_llm()
        logger.info(f"开始修改行程方案 (ID: {requirement.get('id', '')}), 反馈: {user_feedback[:50]}")
        response = llm.invoke(prompt)
        answer = response.content if hasattr(response, "content") else str(response)
        _log_usage(response, "modify")
    except Exception as e:
        logger.error(f"LLM 修改调用失败: {e}")
        return {"success": False, "data": None, "error": f"AI 服务修改失败: {e}"}

    # 3. 提取并校验 JSON
    json_data = _extract_json(answer)
    if json_data is None:
        logger.error(f"修改后 JSON 提取失败")
        return {"success": False, "data": None, "error": "AI 输出格式异常，请重试"}

    expected_days = requirement.get("travel_days", 3)
    json_data = _validate_itinerary(json_data, expected_days)

    logger.info(f"行程方案修改成功: {json_data.get('title', '')}")
    return {"success": True, "data": json_data, "error": None}


# =====================================================================
# 降级方案
# =====================================================================

def _build_fallback_itinerary(requirement: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """当 JSON 解析失败时，用 LLM 原始输出构建一个兜底方案。"""
    days = requirement.get("travel_days", 3)
    daily_plan = []
    for d in range(1, days + 1):
        daily_plan.append({
            "day": d,
            "date_desc": f"第{d}天",
            "morning": {"activity": "", "location": "", "cost_est": 0, "note": ""},
            "afternoon": {"activity": "", "location": "", "cost_est": 0, "note": ""},
            "evening": {"activity": "", "location": "", "cost_est": 0, "note": ""},
            "accommodation": "",
            "meals": "",
            "transport": "",
        })

    return {
        "title": f"{requirement.get('destination', '')}{requirement.get('travel_days', '')}天行程方案",
        "overview": "方案正在优化中，以下为AI原始输出。",
        "daily_plan": daily_plan,
        "total_cost_est": 0,
        "cost_breakdown": "",
        "notes": "",
        "client_talk": raw_text[:1000] if raw_text else "方案生成中，请稍后查看。",
        "internal_notes": "该方案需要手动调整格式",
        "alternative_routes": "",
    }
