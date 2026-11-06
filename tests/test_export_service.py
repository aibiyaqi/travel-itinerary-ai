"""
导出服务测试 — 行程方案导出功能测试

测试 export_service.py 中的核心函数：
  1. export_to_markdown()  — 导出为 Markdown 格式
  2. export_to_text()      — 导出为纯文本格式
  3. _format_cost()        — 费用格式化
  4. _daily_plan_to_markdown() — 每日行程转 Markdown
  5. _daily_plan_to_text()     — 每日行程转纯文本

使用 Mock 隔离数据库依赖。
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def sample_itinerary_data():
    """模拟 get_itinerary 返回值"""
    content = {
        "title": "桂林3日亲子游方案",
        "overview": "这是一条专为亲子家庭设计的桂林3日游路线，包含漓江竹筏、阳朔西街等经典景点。",
        "daily_plan": [
            {
                "day": 1,
                "date_desc": "第1天 — 抵达桂林",
                "morning": {"activity": "抵达桂林，入住酒店", "location": "桂林市区", "cost_est": 0, "note": ""},
                "afternoon": {"activity": "游览象鼻山", "location": "象鼻山景区", "cost_est": 200, "note": "适合儿童游玩"},
                "evening": {"activity": "逛东西巷步行街", "location": "东西巷", "cost_est": 100, "note": ""},
                "accommodation": "桂林市区某某酒店",
                "meals": "含早、午餐",
                "transport": "专车接送",
            },
            {
                "day": 2,
                "date_desc": "第2天 — 漓江精华",
                "morning": {"activity": "漓江竹筏漂流", "location": "漓江", "cost_est": 400, "note": "儿童需穿救生衣"},
                "afternoon": {"activity": "游览阳朔西街", "location": "阳朔", "cost_est": 100, "note": ""},
                "evening": {"activity": "观看印象刘三姐", "location": "阳朔", "cost_est": 200, "note": ""},
                "accommodation": "阳朔特色民宿",
                "meals": "含三餐",
                "transport": "旅游大巴",
            },
        ],
        "total_cost_est": 5100,
        "cost_breakdown": "交通: 1200, 住宿: 1800, 餐饮: 900, 门票: 800, 其他: 400",
        "notes": "注意防晒，带好儿童证件",
        "client_talk": "这条路线非常适合亲子家庭，节奏舒缓，景点经典。",
        "alternative_routes": "如时间充裕可增加龙脊梯田一日游",
    }
    return {
        "itinerary_id": 1,
        "client_name": "张三",
        "destination": "桂林",
        "travel_days": 3,
        "traveler_count": 4,
        "total_budget": 6000.0,
        "travel_type": "亲子",
        "preferences": "自然风光,轻松休闲",
        "special_requirements": "老人/儿童适配",
        "status": "draft",
        "version": 1,
        "created_at": "2026-07-09 10:00:00",
        "content_json": json.dumps(content, ensure_ascii=False),
    }


# =====================================================================
# 测试：_format_cost()
# =====================================================================

class TestFormatCost:
    """费用格式化测试"""

    def test_positive_cost(self):
        """正数费用 → 应格式化为人民币"""
        from src.export_service import _format_cost
        assert _format_cost(1000) == "¥1,000"
        assert _format_cost(12345.67) == "¥12,346"

    def test_zero_cost(self):
        """零或负数 → 返回空字符串"""
        from src.export_service import _format_cost
        assert _format_cost(0) == ""
        assert _format_cost(-100) == ""

    def test_none_cost(self):
        """None → 返回空字符串"""
        from src.export_service import _format_cost
        assert _format_cost(None) == ""


# =====================================================================
# 测试：_daily_plan_to_markdown()
# =====================================================================

class TestDailyPlanToMarkdown:
    """每日行程转 Markdown 格式测试"""

    def test_basic_conversion(self):
        """基本转换 → 包含日期标题、时段活动、住宿餐饮交通"""
        from src.export_service import _daily_plan_to_markdown
        plan = [
            {
                "day": 1,
                "date_desc": "第1天",
                "morning": {"activity": "游览景点A", "location": "地点A", "cost_est": 100, "note": "提示"},
                "afternoon": {"activity": "游览景点B", "location": "地点B", "cost_est": 0, "note": ""},
                "accommodation": "某酒店",
                "meals": "含早餐",
                "transport": "步行",
            }
        ]
        result = _daily_plan_to_markdown(plan)

        assert "第1天" in result
        assert "🌅 上午" in result
        assert "☀️ 下午" in result
        assert "游览景点A" in result
        assert "📍 地点A" in result
        assert "💰 ¥100" in result
        assert "💡 提示" in result
        assert "🏨 住宿" in result
        assert "🍽️ 餐饮" in result
        assert "🚗 交通" in result

    def test_string_period(self):
        """时段为字符串（非字典）→ 直接输出"""
        from src.export_service import _daily_plan_to_markdown
        plan = [
            {
                "day": 1,
                "date_desc": "第1天",
                "morning": "上午自由活动",
                "afternoon": "",
            }
        ]
        result = _daily_plan_to_markdown(plan)
        assert "🌅 上午" in result
        assert "上午自由活动" in result

    def test_empty_plan(self):
        """空行程列表 → 返回空字符串"""
        from src.export_service import _daily_plan_to_markdown
        assert _daily_plan_to_markdown([]) == ""


# =====================================================================
# 测试：_daily_plan_to_text()
# =====================================================================

class TestDailyPlanToText:
    """每日行程转纯文本格式测试"""

    def test_basic_conversion(self):
        """基本转换 → 包含分隔线、时段标签、住宿餐饮"""
        from src.export_service import _daily_plan_to_text
        plan = [
            {
                "day": 1,
                "date_desc": "第1天",
                "morning": {"activity": "游览景点A", "location": "地点A", "cost_est": 100, "note": "提示"},
                "accommodation": "某酒店",
                "meals": "含早餐",
                "transport": "步行",
            }
        ]
        result = _daily_plan_to_text(plan)

        assert "第1天" in result
        assert "上午" in result
        assert "游览景点A" in result
        assert "地点: 地点A" in result
        assert "费用: ¥100" in result
        assert "提示: 提示" in result
        assert "住宿: 某酒店" in result

    def test_empty_plan(self):
        """空行程列表 → 返回空字符串"""
        from src.export_service import _daily_plan_to_text
        assert _daily_plan_to_text([]) == ""


# =====================================================================
# 测试：export_to_markdown()
# =====================================================================

class TestExportToMarkdown:
    """Markdown 导出测试"""

    def test_export_success(self, sample_itinerary_data):
        """正常方案 → 返回完整 Markdown 文本"""
        with patch("src.export_service.get_itinerary", return_value=sample_itinerary_data):
            from src.export_service import export_to_markdown
            result = export_to_markdown(1)

        assert "# 桂林3日亲子游方案" in result
        assert "## 📋 基本信息" in result
        assert "**客户名称**：张三" in result
        assert "**目的地**：桂林" in result
        assert "**出行天数**：3天" in result
        assert "**出行人数**：4人" in result
        assert "**总预算**：¥6,000" in result
        assert "**出行类型**：亲子" in result
        assert "## 📝 行程概述" in result
        assert "## 📅 每日行程安排" in result
        assert "## 💰 费用估算" in result
        assert "¥5,100" in result
        assert "## ⚠️ 出行注意事项" in result
        assert "注意防晒" in result
        assert "## 💬 客户介绍话术" in result
        assert "## 🔄 备选路线建议" in result
        assert "龙脊梯田" in result
        assert "由智能行程方案生成系统自动生成" in result

    def test_export_nonexistent(self):
        """不存在的方案 → 返回错误提示"""
        with patch("src.export_service.get_itinerary", return_value=None):
            from src.export_service import export_to_markdown
            result = export_to_markdown(999)
            assert "方案不存在" in result

    def test_export_bad_json(self):
        """content_json 解析失败 → 返回错误提示"""
        with patch("src.export_service.get_itinerary") as mock_get:
            mock_get.return_value = {
                "itinerary_id": 1,
                "content_json": "{invalid json}",
                "status": "draft",
                "version": 1,
                "created_at": "2026-07-09 10:00:00",
            }
            from src.export_service import export_to_markdown
            result = export_to_markdown(1)
            assert "方案数据异常" in result


# =====================================================================
# 测试：export_to_text()
# =====================================================================

class TestExportToText:
    """纯文本导出测试"""

    def test_export_success(self, sample_itinerary_data):
        """正常方案 → 返回完整纯文本"""
        with patch("src.export_service.get_itinerary", return_value=sample_itinerary_data):
            from src.export_service import export_to_text
            result = export_to_text(1)

        assert "桂林3日亲子游方案" in result
        assert "【基本信息】" in result
        assert "客户：张三" in result
        assert "目的地：桂林" in result
        assert "天数：3天 | 人数：4人" in result
        assert "预算：¥6,000" in result
        assert "【行程概述】" in result
        assert "【每日行程安排】" in result
        assert "【费用】" in result
        assert "【注意事项】" in result
        assert "【客户话术】" in result

    def test_export_nonexistent(self):
        """不存在的方案 → 返回错误提示"""
        with patch("src.export_service.get_itinerary", return_value=None):
            from src.export_service import export_to_text
            result = export_to_text(999)
            assert "方案不存在" in result

    def test_export_bad_json(self):
        """content_json 解析失败 → 返回错误提示"""
        with patch("src.export_service.get_itinerary") as mock_get:
            mock_get.return_value = {
                "itinerary_id": 1,
                "content_json": "not json",
                "status": "draft",
                "version": 1,
                "created_at": "2026-07-09",
            }
            from src.export_service import export_to_text
            result = export_to_text(1)
            assert "方案数据异常" in result
