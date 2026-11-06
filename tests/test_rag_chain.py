"""
RAG 问答链测试（B端版） — 行程方案生成 / 修改 / JSON 提取 / 校验 / 降级

测试新 rag_chain.py 中的核心函数：
  1. _extract_json()      — 从 LLM 输出中提取 JSON
  2. _validate_itinerary() — 校验并补全行程字段
  3. generate_itinerary()  — 根据需求生成行程方案（返回 {"success", "data", "error"}）
  4. modify_itinerary()    — 多轮修改方案（参数: requirement, current_content, user_feedback）
  5. _build_fallback_itinerary() — LLM 失败时的兜底方案
  6. build_llm()           — LLM 构建器

使用 Mock 隔离外部依赖（LLM / Chroma），无需真实 API Key。
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """每个测试自动设置环境变量"""
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-key-for-pytest")
    yield


@pytest.fixture
def sample_requirement():
    """标准的行程需求样例"""
    return {
        "client_name": "张三",
        "destination": "桂林",
        "travel_days": 3,
        "traveler_count": 4,
        "total_budget": 6000,
        "travel_type": "亲子",
        "preferences": "自然风光,轻松休闲",
        "special_requirements": "老人/儿童适配",
    }


@pytest.fixture
def sample_itinerary_content():
    """符合规范的标准行程方案内容"""
    return {
        "title": "桂林3日亲子游方案",
        "overview": "这是一条专为亲子家庭设计的桂林3日游路线...",
        "daily_plan": [
            {
                "day": 1,
                "date_desc": "第1天",
                "morning": {"activity": "抵达桂林，入住酒店", "location": "桂林市区", "cost_est": 0, "note": ""},
                "afternoon": {"activity": "游览象鼻山", "location": "象鼻山景区", "cost_est": 200, "note": "适合儿童游玩"},
                "evening": {"activity": "逛东西巷步行街", "location": "东西巷", "cost_est": 100, "note": ""},
                "accommodation": "桂林市区某某酒店",
                "meals": "含早、午餐",
                "transport": "专车接送",
            },
            {
                "day": 2,
                "date_desc": "第2天",
                "morning": {"activity": "漓江竹筏漂流", "location": "漓江", "cost_est": 400, "note": "儿童需穿救生衣"},
                "afternoon": {"activity": "游览阳朔西街", "location": "阳朔", "cost_est": 100, "note": ""},
                "evening": {"activity": "观看印象刘三姐", "location": "阳朔", "cost_est": 200, "note": ""},
                "accommodation": "阳朔特色民宿",
                "meals": "含三餐",
                "transport": "旅游大巴",
            },
            {
                "day": 3,
                "date_desc": "第3天",
                "morning": {"activity": "骑行十里画廊", "location": "阳朔", "cost_est": 100, "note": ""},
                "afternoon": {"activity": "返程", "location": "桂林", "cost_est": 0, "note": ""},
                "accommodation": "",
                "meals": "含早餐",
                "transport": "专车送站",
            },
        ],
        "total_cost_est": 5100,
        "cost_breakdown": "交通: 1200, 住宿: 1800, 餐饮: 900, 门票: 800, 其他: 400",
        "notes": "注意防晒，带好儿童证件",
        "client_talk": "这条路线非常适合亲子家庭...",
        "alternative_routes": "如时间充裕可增加龙脊梯田一日游",
    }


# =====================================================================
# 测试：_extract_json()
# =====================================================================

class TestExtractJson:
    """JSON 提取功能测试"""

    def test_extract_plain_json(self):
        """纯 JSON 字符串 → 应正常解析"""
        from src.rag_chain import _extract_json
        data = {"key": "value", "num": 42}
        text = json.dumps(data, ensure_ascii=False)
        result = _extract_json(text)
        assert result == data

    def test_extract_with_code_block(self):
        """含 ```json ``` 标记 → 应提取代码块内的 JSON"""
        from src.rag_chain import _extract_json
        text = """这里是一些说明文字
```json
{"name": "桂林3日游", "days": 3}
```
后面还有一些文字"""
        result = _extract_json(text)
        assert result == {"name": "桂林3日游", "days": 3}

    def test_extract_with_trailing_comma(self):
        """含尾随逗号 → 应容错处理"""
        from src.rag_chain import _extract_json
        text = '{"items": [1, 2, 3,], "name": "test",}'
        result = _extract_json(text)
        assert result == {"items": [1, 2, 3], "name": "test"}

    def test_extract_with_python_bool(self):
        """Python 布尔值（True/False/None）→ 应转为 JSON 格式"""
        from src.rag_chain import _extract_json
        text = '{"flag": True, "empty": None, "available": False}'
        result = _extract_json(text)
        assert result == {"flag": True, "empty": None, "available": False}

    def test_extract_invalid_input(self):
        """非法输入 → 返回 None"""
        from src.rag_chain import _extract_json
        assert _extract_json("纯文本，没有JSON") is None
        assert _extract_json("") is None
        assert _extract_json("{不完整的json") is None


# =====================================================================
# 测试：_validate_itinerary()
# =====================================================================

class TestValidateItinerary:
    """行程方案校验功能测试"""

    def test_valid_itinerary(self, sample_itinerary_content):
        """完整的有效方案 → 直接通过"""
        from src.rag_chain import _validate_itinerary
        result = _validate_itinerary(sample_itinerary_content, expected_days=3)
        assert result["title"] == "桂林3日亲子游方案"
        assert len(result["daily_plan"]) == 3

    def test_missing_title_filled(self):
        """缺少标题 → 自动填充默认标题 '行程方案'"""
        from src.rag_chain import _validate_itinerary
        data = {"daily_plan": [{"day": 1}]}
        result = _validate_itinerary(data, expected_days=3)
        assert result["title"] == "行程方案"

    def test_missing_overview_filled(self):
        """缺少概述 → 自动填充"""
        from src.rag_chain import _validate_itinerary
        data = {"title": "测试", "daily_plan": [{"day": 1}]}
        result = _validate_itinerary(data, expected_days=3)
        assert result["overview"] == ""

    def test_daily_plan_not_list(self):
        """daily_plan 不是列表 → 初始化为空列表"""
        from src.rag_chain import _validate_itinerary
        data = {"title": "测试", "daily_plan": "not_a_list"}
        result = _validate_itinerary(data, expected_days=3)
        assert isinstance(result["daily_plan"], list)

    def test_day_without_periods(self):
        """每天缺少具体时段 → 自动补全"""
        from src.rag_chain import _validate_itinerary
        data = {
            "title": "测试",
            "daily_plan": [{"day": 1}],
        }
        result = _validate_itinerary(data, expected_days=1)
        day = result["daily_plan"][0]
        assert "morning" in day
        assert "afternoon" in day
        assert "evening" in day
        assert "accommodation" in day
        assert "meals" in day
        assert "transport" in day

    def test_cost_defaults_to_zero(self):
        """费用字段缺失 → 默认为 0"""
        from src.rag_chain import _validate_itinerary
        data = {"title": "测试", "daily_plan": [{"day": 1}]}
        result = _validate_itinerary(data, expected_days=3)
        assert result.get("total_cost_est", -1) >= 0

    def test_string_cost_normalized(self):
        """LLM 返回 "55元" / "约5000" → 必须归一成数字，否则前端格式化会崩"""
        from src.rag_chain import _validate_itinerary
        data = {
            "title": "测试",
            "total_cost_est": "约5,000元",
            "daily_plan": [{
                "day": 1,
                "morning": {"activity": "游漓江", "cost_est": "55元"},
                "afternoon": {"activity": "象鼻山", "cost_est": None},
            }],
        }
        result = _validate_itinerary(data, expected_days=1)
        assert result["total_cost_est"] == 5000.0
        assert result["daily_plan"][0]["morning"]["cost_est"] == 55.0
        assert result["daily_plan"][0]["afternoon"]["cost_est"] == 0.0

    def test_days_padded_to_expected(self):
        """返回天数不足 → 补齐到需求天数并标记 incomplete"""
        from src.rag_chain import _validate_itinerary
        result = _validate_itinerary(
            {"title": "测试", "daily_plan": [{"day": 1}]}, expected_days=3
        )
        assert len(result["daily_plan"]) == 3
        assert result.get("incomplete") is True

    def test_non_dict_day_dropped(self):
        """daily_plan 中出现字符串项 → 丢弃而不抛异常"""
        from src.rag_chain import _validate_itinerary
        result = _validate_itinerary(
            {"title": "测试", "daily_plan": ["第一天", {"day": 2}]}, expected_days=2
        )
        assert len(result["daily_plan"]) == 2
        assert isinstance(result["daily_plan"][0], dict)


# =====================================================================
# 测试：generate_itinerary()
# =====================================================================

class TestGenerateItinerary:
    """行程方案生成测试
    generate_itinerary() 返回 {"success": bool, "data": dict, "error": str}
    """

    def test_generate_success(self, sample_requirement, sample_itinerary_content):
        """正常调用 → 返回包含完整字段的行程方案"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps(sample_itinerary_content, ensure_ascii=False)
        )

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            with patch("src.rag_chain._retrieve_templates", return_value="桂林景点参考：漓江、象鼻山"):
                from src.rag_chain import generate_itinerary
                result = generate_itinerary(sample_requirement)

        assert result["success"] is True
        assert result["data"]["title"] == "桂林3日亲子游方案"
        assert len(result["data"]["daily_plan"]) == 3
        assert result["data"]["total_cost_est"] > 0
        assert result["error"] is None

    def test_generate_fallback_on_error(self, sample_requirement):
        """LLM 抛出异常 → 应走 fallback（success=True, data=兜底）"""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("API 调用超时")

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            with patch("src.rag_chain._retrieve_templates", return_value=""):
                from src.rag_chain import generate_itinerary
                result = generate_itinerary(sample_requirement)

        # LLM 异常时 success=False，走错误返回而非 fallback
        assert result["success"] is False
        assert result["data"] is None
        assert "API 调用超时" in result["error"]

    def test_generate_fallback_on_bad_json(self, sample_requirement):
        """LLM 返回非 JSON 文本 → 应走 fallback 兜底"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="抱歉，我无法生成方案")

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            with patch("src.rag_chain._retrieve_templates", return_value=""):
                from src.rag_chain import generate_itinerary
                result = generate_itinerary(sample_requirement)

        # 非 JSON 返回时走 fallback，success=True
        assert result["success"] is True
        assert result["data"]["title"] == "桂林3天行程方案"
        assert len(result["data"]["daily_plan"]) == 3
        assert result["error"] is None

    def test_generate_requires_qwen_key(self, sample_requirement):
        """无 API Key → 应直接走 fallback"""
        with patch("src.config.QWEN_API_KEY", ""):
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = Exception("No API key")

            with patch("src.rag_chain.build_llm", return_value=mock_llm):
                with patch("src.rag_chain._retrieve_templates", return_value=""):
                    from src.rag_chain import generate_itinerary
                    result = generate_itinerary(sample_requirement)

            assert result["success"] is False
            assert result["data"] is None


# =====================================================================
# 测试：modify_itinerary()
# =====================================================================

class TestModifyItinerary:
    """行程方案修改测试
    modify_itinerary(requirement: dict, current_content: dict, user_feedback: str)
    返回 {"success": bool, "data": dict, "error": str}
    """

    def test_modify_success(self, sample_requirement, sample_itinerary_content):
        """正常修改 → 返回修改后的新方案内容"""
        mock_llm = MagicMock()
        modified = dict(sample_itinerary_content)
        modified["title"] = "桂林3日亲子游方案（修改版）"
        modified["notes"] = "注意防晒，带好儿童证件，准备雨具"
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps(modified, ensure_ascii=False)
        )

        # 准备正确的参数：requirement dict, current_content dict, feedback str
        requirement = sample_requirement
        current_content = sample_itinerary_content
        feedback = "增加雨具准备提示"

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            from src.rag_chain import modify_itinerary
            result = modify_itinerary(requirement, current_content, feedback)

        assert result["success"] is True
        assert result["data"]["title"] == "桂林3日亲子游方案（修改版）"
        assert "雨具" in result["data"]["notes"]

    def test_modify_with_invalid_feedback(self, sample_requirement, sample_itinerary_content):
        """LLM 异常 → 应返回错误"""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM 错误")

        requirement = sample_requirement
        current_content = sample_itinerary_content
        feedback = "修改内容"

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            from src.rag_chain import modify_itinerary
            result = modify_itinerary(requirement, current_content, feedback)

        assert result["success"] is False
        assert result["data"] is None
        assert "LLM 错误" in result["error"]

    def test_modify_with_bad_json_response(self, sample_requirement, sample_itinerary_content):
        """修改时 LLM 返回非法 JSON → 返回错误"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="这不是JSON")

        requirement = sample_requirement
        current_content = sample_itinerary_content
        feedback = "修改内容"

        with patch("src.rag_chain.build_llm", return_value=mock_llm):
            from src.rag_chain import modify_itinerary
            result = modify_itinerary(requirement, current_content, feedback)

        assert result["success"] is False
        assert result["data"] is None


# =====================================================================
# 测试：_build_fallback_itinerary()
# =====================================================================

class TestBuildFallbackItinerary:
    """兜底方案生成测试"""

    def test_fallback_structure(self, sample_requirement):
        """兜底方案应含有所有必需字段"""
        from src.rag_chain import _build_fallback_itinerary
        result = _build_fallback_itinerary(sample_requirement, "原始文本")

        assert "title" in result
        assert "overview" in result
        assert "daily_plan" in result
        assert "total_cost_est" in result
        assert "cost_breakdown" in result
        assert "notes" in result
        assert "client_talk" in result

    def test_fallback_daily_plan_count(self, sample_requirement):
        """兜底方案的天数应与需求一致"""
        from src.rag_chain import _build_fallback_itinerary
        result = _build_fallback_itinerary(sample_requirement, "")
        assert len(result["daily_plan"]) == sample_requirement["travel_days"]

    def test_fallback_title_contains_destination(self, sample_requirement):
        """兜底方案标题应包含目的地"""
        from src.rag_chain import _build_fallback_itinerary
        result = _build_fallback_itinerary(sample_requirement, "")
        assert "桂林" in result["title"]


# =====================================================================
# 测试：build_llm()
# =====================================================================

class TestBuildLLM:
    """LLM 构建器测试"""

    def test_build_llm_type(self):
        """build_llm 应返回 ChatOpenAI 实例"""
        from src.rag_chain import build_llm
        llm = build_llm()
        from langchain_openai import ChatOpenAI
        assert isinstance(llm, ChatOpenAI)

    def test_build_llm_config(self):
        """build_llm 应使用配置中的参数
        注意：rag_chain.py 在模块级别 `from src.config import LLM_TEMPERATURE`，
        因此需要 patch `src.rag_chain.LLM_TEMPERATURE` 而非 `src.config.LLM_TEMPERATURE`。
        """
        with patch("src.rag_chain.QWEN_MODEL", "qwen-max"):
            with patch("src.rag_chain.LLM_TEMPERATURE", 0.5):
                from src.rag_chain import build_llm
                llm = build_llm()
                assert llm.model_name == "qwen-max"
                assert llm.temperature == 0.5


# =====================================================================
# 测试：_retrieve_templates()
# =====================================================================

class TestRetrieveTemplates:
    """模板检索功能测试"""

    def test_retrieve_no_vector_store(self):
        """无向量库时 → 返回空字符串（显式 mock，避免依赖本地 chroma_db）"""
        from src.rag_chain import _retrieve_templates
        with patch("src.data_loader.list_knowledge_bases", return_value=[]):
            result = _retrieve_templates("桂林旅游")
        assert result == ""

    def test_retrieve_with_mock_vector_store(self):
        """模拟向量库检索 → 返回拼接的文档内容
        注意：_retrieve_templates 内部执行
            from src.data_loader import load_vector_store, list_knowledge_bases
            from src.retriever import build_hybrid_retriever
        因此需 patch 这些模块的函数。
        """
        from src.rag_chain import _retrieve_templates

        mock_doc1 = MagicMock()
        mock_doc1.page_content = "漓江是桂林著名景点"
        mock_doc2 = MagicMock()
        mock_doc2.page_content = "桂林3日游经典路线推荐"

        mock_hybrid = MagicMock()
        mock_hybrid.search.return_value = [(mock_doc1, 0.95), (mock_doc2, 0.85)]

        with patch("src.data_loader.list_knowledge_bases",
                   return_value=[("test_kb", "旅游", 2)]):
            with patch("src.data_loader.load_vector_store",
                       return_value=MagicMock()):
                with patch("src.retriever.build_hybrid_retriever",
                           return_value=mock_hybrid):
                    result = _retrieve_templates("桂林旅游", k=2)

        assert "漓江" in result
        assert "桂林" in result
