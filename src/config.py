"""
全局配置 — B端旅行社/研学机构智能行程方案系统

集中管理所有路径、模型、检索参数、业务常量。
"""
import os
import sys

# ── Windows 编码修复 ──
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 内置 .env 解析器 ──
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(_ENV_PATH):
    with open(_ENV_PATH, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _val = _line.split("=", 1)
            _key, _val = _key.strip(), _val.strip().strip("\"'")
            if _key not in os.environ:
                os.environ[_key] = _val

# ====== 路径配置 ======
DATA_DIR: str = "data/"
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "data/uploads")  # 上传文件目录（Docker 中挂载独立卷）
CHROMA_DB_DIR: str = "chroma_db/"
DB_PATH: str = os.getenv("BIZ_DB_PATH", "biz_data.db")   # 业务数据库（可用环境变量指向持久化卷）
TEMPLATE_DIR: str = "data/business_templates/"  # 内置业务模板目录
EXPORT_DIR: str = "exports/"           # 导出文件目录

# ====== 管理员配置 ======
# 注意：不再提供默认弱口令。未配置 ADMIN_PASSWORD 时不会自动创建管理员。
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

# ====== 注册策略 ======
# B 端内部系统默认关闭自助注册，账号由管理员创建
ALLOW_SELF_REGISTER: bool = os.getenv("ALLOW_SELF_REGISTER", "false").strip().lower() in ("1", "true", "yes")

# ====== Embedding 配置 ======
EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"

# ====== 检索配置（用于模板知识库匹配） ======
RETRIEVER_K: int = 4
HYBRID_SEARCH_K: int = 12
RERANKER_TOP_K: int = 3
# RRF 融合权重：当前模板语料以语义匹配为主，BM25 作为关键词补充
HYBRID_BM25_WEIGHT: float = 0.5
HYBRID_VECTOR_WEIGHT: float = 1.0
# 融合策略：vector_primary（向量为主，适合小语料）/ rrf（加权倒数排名融合）
HYBRID_FUSION: str = os.getenv("HYBRID_FUSION", "vector_primary")
CHUNK_SIZE: int = 500
CHUNK_OVERLAP: int = 50
# Cross-Encoder 重排默认关闭：首次使用需下载 ~2GB 模型，CPU 单次约 1-2 秒。
# 需要更高检索精度时在 .env 中设置 RERANK_ENABLED=true 开启。
RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "false").strip().lower() in ("1", "true", "yes")

# ====== 通义千问 LLM 配置 ======
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL: str = "qwen-max"
QWEN_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_TEMPERATURE: float = 0.3
LLM_MAX_TOKENS: int = 8192        # 长行程 JSON 需要更大输出上限
LLM_TIMEOUT: int = 180            # 单次调用超时（秒），避免请求悬挂
LLM_MAX_RETRIES: int = 2          # 网络/限流错误自动重试次数

# ====== Token 计费配置 ======
QWEN_PRICE_INPUT: float = 0.00002
QWEN_PRICE_OUTPUT: float = 0.00006

# ====== 日历配置（用于生成真实的日期描述） ======
import datetime
CURRENT_DATE: str = datetime.date.today().isoformat()

# ====== 业务常量 ======

# 出行类型
TRAVEL_TYPES: list = [
    "亲子", "研学", "团建", "情侣", "毕业旅行",
    "家庭出游", "朋友结伴", "独自旅行", "商务出行",
]

# 偏好标签
PREFERENCE_OPTIONS: list = [
    "自然风光", "历史人文", "美食", "轻松休闲",
    "打卡观光", "户外探险", "文化体验", "购物",
]

# 特殊要求选项（提示用）
SPECIAL_REQUIREMENT_EXAMPLES: list = [
    "老人/儿童适配", "无障碍", "低强度路线",
    "规避购物点", "纯玩无购物", "深度游",
    "含特色体验活动", "含专业讲解",
]

# 方案状态
ITINERARY_STATUS_OPTIONS: dict = {
    "draft": "草稿",
    "sent": "已发送",
    "confirmed": "客户确认",
    "cancelled": "已取消",
}

# 用户角色
USER_ROLES: dict = {
    "consultant": "旅行顾问",
    "admin": "管理员",
}

# ====== 校验 ======
if not QWEN_API_KEY:
    raise ValueError(
        "❌ 未检测到 QWEN_API_KEY！\n"
        "请在项目根目录的 .env 文件中配置：\n"
        "QWEN_API_KEY=sk-your-key-here"
    )
