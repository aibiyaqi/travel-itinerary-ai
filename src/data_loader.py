"""
数据加载模块 — PDF/JSONL/CSV 解析 → 切分 → 向量化 → Chroma 存储
支持多知识库管理：每份文件可存入独立子目录
"""
import hashlib
import os
import json
import logging
from typing import List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

from src.config import (
    CHROMA_DB_DIR, EMBEDDING_MODEL, TEMPLATE_DIR,
    CHUNK_SIZE, CHUNK_OVERLAP, RETRIEVER_K,
)

logger = logging.getLogger("travel_assistant.data_loader")

# 内置业务模板知识库（与用户上传的知识库隔离）
TEMPLATE_KB_NAME = "builtin_business_templates"
_SEED_MANIFEST = "seed_manifest.json"


# ==================== 模型与向量库缓存 ====================
# embedding 模型加载耗时 1-2 秒，按进程复用，避免每次生成都重新加载
_EMBEDDINGS = None
_VECTOR_STORES = {}


def _get_embeddings() -> HuggingFaceEmbeddings:
    """获取进程内复用的 embedding 实例。"""
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        _EMBEDDINGS = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _EMBEDDINGS


# ==================== 文本解析器 ====================

def _parse_pdf(file_path: str) -> str:
    """解析 PDF 文件为纯文本（双解析器兜底）"""
    text = ""
    # 第一优先：unstructured（质量高）
    try:
        from unstructured.partition.pdf import partition_pdf
        elements = partition_pdf(file_path, strategy="hi_res")
        text = "\n".join(el.text for el in elements if el.text)
        if text.strip():
            return text
    except Exception as e:
        logger.warning(f"unstructured 解析失败，尝试 pdfplumber: {e}")

    # 第二优先：pdfplumber（轻量快速）
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if text.strip():
            return text
    except Exception as e:
        logger.error(f"pdfplumber 也解析失败: {e}")

    raise ValueError(f"PDF 解析失败（两种解析器均无效）: {file_path}")


def _parse_jsonl(file_path: str) -> str:
    """解析 JSONL 问答对文件为纯文本（兼容 question/answer 和 prompt/response 两种格式）"""
    texts = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                # 兼容两种常见字段命名
                q = item.get("question") or item.get("prompt") or ""
                a = item.get("answer") or item.get("response") or ""
                if q and a:
                    texts.append(f"问：{q}\n答：{a}")
            except json.JSONDecodeError:
                logger.warning(f"跳过无法解析的行: {line[:50]}...")
    return "\n\n".join(texts)


def _parse_csv(file_path: str) -> str:
    """解析 CSV 文件为纯文本"""
    import csv
    texts = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 将每行所有字段拼成文本
            parts = [f"{k}：{v}" for k, v in row.items() if v]
            texts.append("，".join(parts))
    return "\n".join(texts)


# ==================== 文件处理入口 ====================

def process_file(file_path: str, persist_subdir: str = None) -> Chroma:
    """
    处理上传文件，构建/更新向量库。

    参数:
        file_path: 文件路径，支持 .pdf / .jsonl / .csv
        persist_subdir: 持久化子目录名（用于多知识库），默认使用 CHROMA_DB_DIR

    返回:
        Chroma: 构建好的向量库实例
    """
    # 1. 根据扩展名选择解析器
    ext = os.path.splitext(file_path)[1].lower()
    logger.info(f"开始处理文件: {file_path} (格式: {ext})")

    if ext == ".pdf":
        raw_text = _parse_pdf(file_path)
    elif ext == ".jsonl":
        raw_text = _parse_jsonl(file_path)
    elif ext == ".csv":
        raw_text = _parse_csv(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}（仅支持 PDF / JSONL / CSV）")

    if not raw_text.strip():
        raise ValueError("文件解析后内容为空，请检查文件内容")

    # 2. 文本切分
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],
    )
    chunks = splitter.split_text(raw_text)
    logger.info(f"文本切分为 {len(chunks)} 个片段")

    # 3. 确定持久化目录
    persist_dir = os.path.join(CHROMA_DB_DIR, persist_subdir) if persist_subdir else CHROMA_DB_DIR
    os.makedirs(persist_dir, exist_ok=True)

    # 4. 向量化并存入 Chroma（Chroma >= 1.0 自动持久化）
    embeddings = _get_embeddings()
    vector_store = Chroma.from_texts(
        texts=chunks,
        embedding=embeddings,
        persist_directory=persist_dir,
    )
    _VECTOR_STORES[persist_dir] = vector_store
    logger.info(f"向量库已构建并持久化到 {persist_dir}")

    # 5. 同步构建 BM25 索引
    try:
        from src.retriever import build_hybrid_retriever
        build_hybrid_retriever(vector_store, texts=chunks, subdir=persist_subdir)
    except ImportError:
        logger.info("retriever 模块未加载，跳过 BM25 索引构建")
    except Exception as e:
        logger.warning(f"BM25 索引构建失败（不影响主流程）: {e}")

    return vector_store


def load_vector_store(subdir: str = None) -> Optional[Chroma]:
    """
    从磁盘加载已有向量库，支持指定子目录。

    参数:
        subdir: 子目录名，默认加载 CHROMA_DB_DIR 根目录

    返回:
        Chroma 实例，若目录不存在则返回 None
    """
    persist_dir = os.path.join(CHROMA_DB_DIR, subdir) if subdir else CHROMA_DB_DIR

    if not os.path.exists(persist_dir):
        logger.info(f"向量库目录不存在: {persist_dir}")
        return None

    if not os.listdir(persist_dir):
        logger.info(f"向量库目录为空: {persist_dir}")
        return None

    # 进程内复用，避免每次检索都重新打开 Chroma + 加载 embedding 模型
    if persist_dir in _VECTOR_STORES:
        return _VECTOR_STORES[persist_dir]

    vector_store = Chroma(
        persist_directory=persist_dir,
        embedding_function=_get_embeddings(),
    )
    _VECTOR_STORES[persist_dir] = vector_store
    logger.info(f"已加载已有向量库（{persist_dir}）")
    return vector_store


def list_knowledge_bases() -> list:
    """
    扫描 chroma_db 目录，列出所有可用的知识库。

    返回:
        [(名称, 显示名), ...] 列表，按修改时间降序
    """
    bases = []
    if not os.path.exists(CHROMA_DB_DIR):
        return bases

    for entry in os.listdir(CHROMA_DB_DIR):
        entry_path = os.path.join(CHROMA_DB_DIR, entry)
        if entry.startswith(".") or entry == "bm25_index.pkl":
            continue
        if os.path.isdir(entry_path):
            sub_items = os.listdir(entry_path)
            if any(f.endswith(".bin") or f == "chroma.sqlite3" for f in sub_items):
                # 美化显示名：去掉扩展名
                name = entry
                display = entry.replace("_", " ").replace("-", " ").title()
                bases.append((name, f"📁 {display}"))

    # 如果根目录也有数据，添加为默认知识库
    if os.path.exists(os.path.join(CHROMA_DB_DIR, "chroma.sqlite3")):
        bases.insert(0, ("_default", "📁 默认知识库"))

    # 按修改时间降序（_default 是虚拟名称，对应 chroma_db 根目录）
    def _sort_key(item):
        name = item[0]
        if name == "_default":
            dir_path = CHROMA_DB_DIR
        else:
            dir_path = os.path.join(CHROMA_DB_DIR, name)
        try:
            return os.path.getmtime(dir_path)
        except OSError:
            return 0.0

    bases.sort(key=_sort_key, reverse=True)

    return bases


# ==================== 内置业务模板自动入库 ====================

def _read_template_documents() -> List[Document]:
    """
    读取 data/business_templates/*.jsonl，一行一条记录作为一个文档。

    与通用 process_file 的按 500 字切分不同：模板是“问/答”结构，
    按条入库能保留完整语义，也便于评测时定位来源。
    """
    documents: List[Document] = []
    if not os.path.isdir(TEMPLATE_DIR):
        return documents

    for filename in sorted(os.listdir(TEMPLATE_DIR)):
        if not filename.endswith(".jsonl"):
            continue
        path = os.path.join(TEMPLATE_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            for index, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"模板行解析失败，已跳过: {filename}#{index}")
                    continue
                question = item.get("question") or item.get("prompt") or ""
                answer = item.get("answer") or item.get("response") or ""
                if not question or not answer:
                    continue
                documents.append(Document(
                    page_content=f"问：{question}\n答：{answer}",
                    metadata={
                        "source": filename,
                        "record_index": index,
                        "kb": TEMPLATE_KB_NAME,
                    },
                ))
    return documents


def _template_fingerprint(documents: List[Document]) -> str:
    """按内容计算指纹，模板不变时跳过重复向量化。"""
    digest = hashlib.md5()
    for doc in documents:
        digest.update(doc.page_content.encode("utf-8"))
        digest.update(str(doc.metadata.get("source", "")).encode("utf-8"))
    return digest.hexdigest()


def seed_builtin_templates(force: bool = False) -> int:
    """
    将内置业务模板导入独立知识库（幂等）。

    返回本次实际入库的文档数；模板未变化时返回 0 且不加载 embedding 模型。
    """
    documents = _read_template_documents()
    if not documents:
        logger.warning(f"未找到内置模板文件: {TEMPLATE_DIR}")
        return 0

    persist_dir = os.path.join(CHROMA_DB_DIR, TEMPLATE_KB_NAME)
    manifest_path = os.path.join(persist_dir, _SEED_MANIFEST)
    fingerprint = _template_fingerprint(documents)

    if not force and os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            db_file = os.path.join(persist_dir, "chroma.sqlite3")
            if manifest.get("fingerprint") == fingerprint and os.path.isfile(db_file):
                logger.info(f"内置模板知识库已是最新（{manifest.get('count', 0)} 条），跳过入库")
                return 0
        except (OSError, json.JSONDecodeError):
            logger.warning("模板 manifest 读取失败，将重新入库")

    os.makedirs(persist_dir, exist_ok=True)
    embeddings = _get_embeddings()

    # 模板全量重建：先删除旧 collection，避免重复累积
    try:
        old_store = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
        old_store.delete_collection()
    except Exception as e:
        logger.warning(f"清理旧模板知识库失败（可忽略）: {e}")

    ids = [f"tpl-{index:05d}" for index in range(len(documents))]
    vector_store = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=persist_dir,
        ids=ids,
    )
    _VECTOR_STORES[persist_dir] = vector_store

    # 同步构建该知识库独立的 BM25 索引
    from src.retriever import build_hybrid_retriever

    build_hybrid_retriever(
        vector_store,
        texts=[doc.page_content for doc in documents],
        subdir=TEMPLATE_KB_NAME,
        documents=documents,
    )

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "fingerprint": fingerprint,
                "count": len(documents),
                "sources": sorted({doc.metadata["source"] for doc in documents}),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(f"内置模板入库完成：{len(documents)} 条 → {persist_dir}")
    return len(documents)
