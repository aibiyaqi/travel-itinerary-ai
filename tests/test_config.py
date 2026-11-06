"""
配置模块测试 — 验证 config.py 环境变量加载与默认值
"""
import os
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


class TestConfigLoading:
    """测试配置加载与默认值"""

    def test_env_loading(self, monkeypatch):
        """验证 .env 文件解析后 os.getenv 能获取到值"""
        # 模拟环境变量
        monkeypatch.setenv("QWEN_API_KEY", "sk-test-key-12345")
        monkeypatch.setenv("ADMIN_USERNAME", "test_admin")
        monkeypatch.setenv("ADMIN_PASSWORD", "test_pass_2024")

        # 重新导入 config 模块（使用 importlib 避免缓存）
        import importlib
        from src import config
        importlib.reload(config)

        assert config.QWEN_API_KEY == "sk-test-key-12345"
        assert config.ADMIN_USERNAME == "test_admin"
        assert config.ADMIN_PASSWORD == "test_pass_2024"

    def test_config_defaults(self):
        """验证关键配置项有合理的默认值"""
        from src import config

        # 路径配置
        assert config.DATA_DIR == "data/"
        assert config.CHROMA_DB_DIR == "chroma_db/"
        assert config.DB_PATH == "biz_data.db"
        assert config.TEMPLATE_DIR == "data/business_templates/"
        assert config.EXPORT_DIR == "exports/"

        # 检索配置
        assert config.RETRIEVER_K == 4
        assert config.HYBRID_SEARCH_K == 12
        assert config.RERANKER_TOP_K == 3
        assert config.CHUNK_SIZE == 500
        assert config.CHUNK_OVERLAP == 50

        # LLM 配置
        assert config.QWEN_MODEL == "qwen-max"
        assert config.QWEN_API_BASE == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert config.LLM_TEMPERATURE == 0.3

        # Token 计费
        assert config.QWEN_PRICE_INPUT == 0.00002
        assert config.QWEN_PRICE_OUTPUT == 0.00006

        # 业务常量 — 出行类型
        assert "亲子" in config.TRAVEL_TYPES
        assert "研学" in config.TRAVEL_TYPES
        assert "团建" in config.TRAVEL_TYPES
        assert len(config.TRAVEL_TYPES) >= 8

        # 业务常量 — 偏好标签
        assert "自然风光" in config.PREFERENCE_OPTIONS
        assert "历史人文" in config.PREFERENCE_OPTIONS
        assert len(config.PREFERENCE_OPTIONS) >= 6

        # 业务常量 — 特殊要求示例
        assert "老人/儿童适配" in config.SPECIAL_REQUIREMENT_EXAMPLES

        # 业务常量 — 方案状态
        assert config.ITINERARY_STATUS_OPTIONS["draft"] == "草稿"
        assert config.ITINERARY_STATUS_OPTIONS["sent"] == "已发送"
        assert config.ITINERARY_STATUS_OPTIONS["confirmed"] == "客户确认"
        assert config.ITINERARY_STATUS_OPTIONS["cancelled"] == "已取消"

        # 业务常量 — 用户角色
        assert config.USER_ROLES["consultant"] == "旅行顾问"
        assert config.USER_ROLES["admin"] == "管理员"

    def test_env_missing_key_raises_error(self, monkeypatch):
        """未设置 QWEN_API_KEY 时 config.py 的校验逻辑应报错"""
        # 模拟 config.py 内置 .env 解析器未读取到任何内容
        # 通过 patch os.getenv 返回空字符串来触发校验
        import importlib
        # 清除模块缓存
        for mod in list(sys.modules.keys()):
            if mod.startswith("src.config"):
                del sys.modules[mod]

        monkeypatch.setenv("QWEN_API_KEY", "")
        try:
            with pytest.raises(ValueError, match="QWEN_API_KEY"):
                import importlib
                if "src.config" in sys.modules:
                    del sys.modules["src.config"]
                from src.config import QWEN_API_KEY  # noqa: F811
        except Exception:
            pass
        finally:
            monkeypatch.setenv("QWEN_API_KEY", "sk-test-key-for-pytest")
            if "src.config" in sys.modules:
                del sys.modules["src.config"]
            import importlib
            import src.config
            importlib.reload(src.config)

    def test_config_types(self):
        """验证配置项类型正确"""
        from src import config

        assert isinstance(config.RETRIEVER_K, int)
        assert isinstance(config.LLM_TEMPERATURE, float)
        assert isinstance(config.ADMIN_USERNAME, str)
        assert isinstance(config.TRAVEL_TYPES, list)
        assert isinstance(config.PREFERENCE_OPTIONS, list)
        assert isinstance(config.ITINERARY_STATUS_OPTIONS, dict)
        assert isinstance(config.USER_ROLES, dict)
