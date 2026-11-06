# ============================================
# 智能行程方案生成系统 — Docker 镜像
# ============================================
# 构建：docker build -t travel-itinerary-ai .
# 运行：docker compose up -d
#
# 默认安装 CPU 版 PyTorch，镜像更小、无需显卡；
# 有 GPU 时可覆盖：--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124
# ============================================

# ---- Stage 1: Base ----
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 系统依赖：gcc/g++ 供少量包编译，curl 供 HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*


# ---- Stage 2: Dependencies ----
FROM base AS deps

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --upgrade pip && \
    # 先装 CPU 版 torch/torchvision，避免默认拉取 2GB+ 的 CUDA 依赖
    pip install --index-url "${TORCH_INDEX}" torch torchvision && \
    pip install -r requirements.txt


# ---- Stage 3: Runtime ----
FROM deps AS runtime

LABEL org.opencontainers.image.title="travel-itinerary-ai" \
      org.opencontainers.image.description="B-end smart itinerary generation for travel agencies and study-tour operators" \
      org.opencontainers.image.source="https://github.com/aibiyaqi/travel-itinerary-ai"

# 非 root 运行
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# 复制代码并直接归属 appuser，避免额外 chown 层
COPY --chown=appuser:appuser . .

RUN mkdir -p data/uploads data/business_templates db chroma_db logs exports .cache/huggingface && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

# 首次启动会加载/下载 embedding 模型，start-period 放宽到 120s
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
