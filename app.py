"""
AI旅行智能助手 — Streamlit 主入口（项目根目录启动器）

确保无论从哪个目录启动，都能正确找到 src 包。
"""
import sys
from pathlib import Path

# ── 将项目根目录加入 Python 路径（支持从任何位置启动） ──
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 导入主应用模块 ──
from src.app import main

if __name__ == "__main__":
    main()
