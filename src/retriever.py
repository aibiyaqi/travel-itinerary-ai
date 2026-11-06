"""
混合检索模块 — BM25 关键词检索 + 向量语义检索 + Reranker 重排序

架构：
  1. BM25Retriever  — rank_bm25 关键词检索
  2. VectorRetriever — Chroma 向量检索封装
  3. HybridRetriever — 两者 RRF 融合
  4. Reranker        — Cross-Encoder 重排序
"""
import hashlib
import logging
import pickle
import os
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

from langchain_core.documents import Document

from src.config import (
    RETRIEVER_K, CHROMA_DB_DIR,
    HYBRID_BM25_WEIGHT, HYBRID_VECTOR_WEIGHT, HYBRID_FUSION,
)

logger = logging.getLogger("travel_assistant.retriever")

# =====================================================================
# 数据类
# =====================================================================

@dataclass
class RetrievalResult:
    """检索结果条目"""
    document: Document
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    combined_score: float = 0.0


# =====================================================================
# BM25 检索器
# =====================================================================

class BM25Retriever:
    """
    BM25 关键词检索器。

    基于 rank_bm25 库实现，适合精准关键词匹配场景。
    弥补纯向量检索对关键词不敏感的问题。
    """

    def __init__(
        self,
        texts: List[str],
        k1: float = 1.5,
        b: float = 0.75,
        documents: Optional[List[Document]] = None,
    ):
        """
        参数:
            texts: 文档文本列表
            k1: BM25 参数，控制词频饱和度（默认 1.5）
            b: BM25 参数，控制文档长度归一化（默认 0.75）
            documents: 与 texts 一一对应的原始 Document（保留来源元数据）
        """
        self._texts = texts
        self._documents = documents
        self._k1 = k1
        self._b = b
        self._index = None
        self._build_index()

    def _build_index(self) -> None:
        """构建 BM25 索引（分词后建索引）。"""
        from rank_bm25 import BM25Okapi

        # 先把每篇文档分词，再建 BM25 索引
        tokenized_corpus = [self._tokenize(t) for t in self._texts]
        self._index = BM25Okapi(tokenized_corpus, k1=self._k1, b=self._b)
        logger.info(
            f"BM25 索引构建完成：{len(self._texts)} 篇文档"
        )

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        中文分词（支持 jieba 智能分词 + 单字回退）。

        优先使用 jieba 分词（词级别，更精准），
        若 jieba 不可用则回退到单字切分（无额外依赖）。
        """
        import re
        # 尝试 jieba 智能分词（词级别匹配更精准）
        try:
            import jieba
            # jieba 精确模式分词
            words = jieba.lcut(text)
            # 过滤纯空格/标点，保留英文词
            words = [w.strip().lower() for w in words if w.strip()]
            return words
        except ImportError:
            # jieba 不可用时，回退到单字切分
            words = re.findall(r"[a-zA-Z0-9]+", text.lower())
            for ch in text:
                if '\u4e00' <= ch <= '\u9fff':
                    words.append(ch)
            return words

    def search(self, query: str, k: int = RETRIEVER_K) -> List[Tuple[Document, float]]:
        """BM25 检索，返回 (文档, 分数) 列表，按分数降序。"""
        if self._index is None:
            logger.warning("BM25 索引为空")
            return []

        tokenized_query = self._tokenize(query)
        scores = self._index.get_scores(tokenized_query)

        # 构建 (doc, score) 对，按分数降序排列
        scored_docs = []
        for index in range(len(self._texts)):
            if scores[index] <= 0:
                continue
            if self._documents is not None and index < len(self._documents):
                doc = self._documents[index]
            else:
                doc = Document(page_content=self._texts[index])
            scored_docs.append((doc, scores[index]))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        logger.info(
            f"BM25 检索 '{query[:30]}' → {len(scored_docs)} 条匹配"
        )
        return scored_docs[:k]

    def save(self, path: str) -> None:
        """序列化保存 BM25 索引。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "texts": self._texts,
                "k1": self._k1,
                "b": self._b,
                "index": self._index,
                "documents": self._documents,
            }, f)
        logger.info(f"BM25 索引已保存到 {path}")

    @classmethod
    def load(cls, path: str) -> Optional["BM25Retriever"]:
        """从文件加载 BM25 索引。"""
        if not os.path.exists(path):
            logger.warning(f"BM25 索引文件不存在: {path}")
            return None
        with open(path, "rb") as f:
            data = pickle.load(f)
        retriever = cls.__new__(cls)
        retriever._texts = data["texts"]
        retriever._k1 = data["k1"]
        retriever._b = data["b"]
        retriever._index = data["index"]
        retriever._documents = data.get("documents")
        logger.info(f"BM25 索引已加载（{len(retriever._texts)} 篇文档）")
        return retriever


# =====================================================================
# 向量检索器（Chroma 封装）
# =====================================================================

class VectorRetriever:
    """Chroma 向量检索封装。"""

    def __init__(self, vector_store):
        self._vector_store = vector_store

    def search(
        self, query: str, k: int = RETRIEVER_K
    ) -> List[Tuple[Document, float]]:
        """
        向量检索，返回 (文档, L2距离) 列表。
        距离越小越相似，bge-small-zh-v1.5 经验阈值 0.6。
        """
        docs_with_scores = self._vector_store.similarity_search_with_score(
            query, k=k
        )
        return docs_with_scores


# =====================================================================
# 混合检索器（BM25 + 向量 + RRF 融合）
# =====================================================================

class HybridRetriever:
    """
    混合检索器：BM25 关键词 + 向量语义 + RRF 融合排序。

    为什么同时用 BM25 和向量？
    - BM25 擅长关键词精确匹配（如"漓江门票多少钱"）
    - 向量搜索擅长语义理解（如"带孩子去哪玩"）
    - 两者互补，融合后效果远超单一检索

    使用 RRF（Reciprocal Rank Fusion）算法融合：
      score(d) = 1/(k + rank_bm25(d)) + 1/(k + rank_vector(d))
    即文档在两种检索结果中排名越靠前，融合分数越高。
    """

    # RRF 常数：k 越大融合越平均，k 越小排名靠前的优势越大
    RRF_K: int = 60

    def __init__(
        self,
        bm25_retriever: BM25Retriever,
        vector_retriever: VectorRetriever,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
        fusion: str = "rrf",
    ):
        self.bm25 = bm25_retriever
        self.vector = vector_retriever
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        # rrf: 等权/加权融合；vector_primary: 向量排序为主，BM25 仅补充未召回文档
        self.fusion = fusion

    def search(
        self, query: str, k: int = RETRIEVER_K
    ) -> List[Tuple[Document, float]]:
        """
        混合检索：分别检索 → RRF 融合 → 返回 Top-K。

        返回: [(Document, combined_score), ...]
        """
        # 1. BM25 检索（取 k*3 个候选，给 RRF 融合留出交叉空间）
        bm25_results = self.bm25.search(query, k=k * 3)

        # 2. 向量检索（同样多取一些候选）
        vector_results = self.vector.search(query, k=k * 3)

        # 3. 融合：默认 RRF；小语料下向量更强时可用 vector_primary
        if self.fusion == "vector_primary":
            fused = self._vector_primary_fusion(bm25_results, vector_results)
        else:
            fused = self._rrf_fusion(bm25_results, vector_results)

        logger.info(
            f"混合检索 '{query[:30]}' → "
            f"BM25={len(bm25_results)} 条 + 向量={len(vector_results)} 条 "
            f"→ RRF 融合={len(fused)} 条"
        )

        return fused[:k]

    def _rrf_fusion(
        self,
        bm25_results: List[Tuple[Document, float]],
        vector_results: List[Tuple[Document, float]],
    ) -> List[Tuple[Document, float]]:
        """
        RRF 融合排序算法。

        核心思想：一篇文档如果在两种检索中排名都靠前，它的融合分数就高。
        即使只在一种检索中排名好，也有可能被另一种检索"拉一把"。

        公式：score(d) = 1/(RRF_K + rank_bm25) + 1/(RRF_K + rank_vector)
        其中 rank 从 1 开始计数（第一名 rank=1）。
        """
        # 用文档内容指纹做 key：BM25 与向量检索返回的是不同 Document 实例，
        # 用 id(doc) 会导致同一内容永远无法合并（重复上下文、融合分数不叠加）。
        doc_scores: dict = {}

        # 遍历 BM25 结果，每篇文档先给一个基础 RRF 分数
        for rank, (doc, _) in enumerate(bm25_results, start=1):
            key = self._doc_key(doc)
            doc_scores[key] = {
                "doc": doc,
                "rrf_score": self.bm25_weight * (1.0 / (self.RRF_K + rank)),
            }

        # 遍历向量结果：同内容则累加分数；否则新增
        for rank, (doc, _) in enumerate(vector_results, start=1):
            key = self._doc_key(doc)
            if key in doc_scores:
                doc_scores[key]["rrf_score"] += self.vector_weight * (1.0 / (self.RRF_K + rank))
                # 优先保留带元数据的版本，方便后续展示来源
                if not doc_scores[key]["doc"].metadata and doc.metadata:
                    doc_scores[key]["doc"] = doc
            else:
                doc_scores[key] = {
                    "doc": doc,
                    "rrf_score": self.vector_weight * (1.0 / (self.RRF_K + rank)),
                }

        # 按 RRF 分数降序排列，分数越高代表在两种检索中排名都越好
        ranked = sorted(
            doc_scores.values(),
            key=lambda x: x["rrf_score"],
            reverse=True,
        )
        return [(item["doc"], item["rrf_score"]) for item in ranked]

    def _vector_primary_fusion(
        self,
        bm25_results: List[Tuple[Document, float]],
        vector_results: List[Tuple[Document, float]],
    ) -> List[Tuple[Document, float]]:
        """
        向量优先融合：保持向量检索的顺序，仅把 BM25 命中但未被向量召回的文档补到尾部。

        适用场景：语料较小、语义模型表现明显优于关键词检索时，避免 BM25 噪声
        把向量的 Top-1 顶掉（评测中曾出现“父母 → 亲子”被误顶到第一的问题）。
        """
        merged: List[Tuple[Document, float]] = []
        seen = set()

        for doc, _ in vector_results:
            key = self._doc_key(doc)
            if key in seen:
                continue
            seen.add(key)
            merged.append((doc, 1.0 / (len(merged) + 1)))

        for doc, _ in bm25_results:
            key = self._doc_key(doc)
            if key in seen:
                continue
            seen.add(key)
            merged.append((doc, 1.0 / (len(merged) + 1)))

        return merged

    @staticmethod
    def _doc_key(doc: Document) -> str:
        """文档去重键：优先显式 doc_id，其次内容指纹。"""
        metadata = getattr(doc, "metadata", None) or {}
        for field_name in ("doc_id", "chunk_id"):
            if metadata.get(field_name):
                return f"meta:{metadata[field_name]}"
        text = (getattr(doc, "page_content", "") or "").strip()
        return "txt:" + hashlib.md5(text.encode("utf-8")).hexdigest()


# =====================================================================
# Cross-Encoder 重排序器
# =====================================================================

class Reranker:
    """
    Cross-Encoder 重排序器。

    对初筛结果（如混合检索 Top-10/15）进行精排，
    使用 BAAI/bge-reranker-base 中文重排序模型。
    """

    MODEL_NAME = "BAAI/bge-reranker-base"

    def __init__(self):
        self._model = None

    def _lazy_load_model(self):
        """延迟加载模型（仅首次使用时加载）。"""
        if self._model is None:
            logger.info(f"加载重排序模型: {self.MODEL_NAME}")
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.MODEL_NAME)
                logger.info("重排序模型加载完成")
            except Exception as e:
                logger.warning(f"重排序模型加载失败，跳过重排: {e}")
                self._model = None

    def rerank(
        self,
        query: str,
        documents: List[Tuple[Document, float]],
        top_k: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        """
        对检索结果重排序。

        参数:
            query: 用户问题
            documents: [(Document, score), ...]
            top_k: 返回前 k 条（默认全部返回）

        返回:
            重排序后的 [(Document, rerank_score), ...]
        """
        if not documents:
            return []

        self._lazy_load_model()
        if self._model is None:
            # 模型加载失败，返回原始顺序
            logger.warning("重排序模型不可用，使用原始顺序")
            return documents

        # 1. 构建 (query, doc_text) 对
        pairs = [
            (query, doc.page_content[:512])  # 截断防止超长
            for doc, _ in documents
        ]

        # 2. Cross-Encoder 打分
        try:
            scores = self._model.predict(pairs)
        except Exception as e:
            logger.warning(f"重排序打分失败: {e}")
            return documents

        # 3. 按分数降序排列
        ranked = sorted(
            [
                (doc, float(score))
                for (doc, _), score in zip(documents, scores)
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        logger.info(
            f"重排序 {len(documents)} 条结果 → "
            f"Top-1: {ranked[0][1]:.4f}（{ranked[0][0].page_content[:30]}...）"
        )

        if top_k is not None:
            return ranked[:top_k]
        return ranked


# =====================================================================
# BM25 索引持久化路径
# =====================================================================

def _bm25_index_path(subdir: Optional[str] = None) -> str:
    """获取 BM25 索引文件路径（按知识库隔离，避免不同知识库互相覆盖）。"""
    if subdir:
        return os.path.join(CHROMA_DB_DIR, subdir, "bm25_index.pkl")
    return os.path.join(CHROMA_DB_DIR, "bm25_index.pkl")


def build_hybrid_retriever(
    vector_store,
    texts: Optional[List[str]] = None,
    subdir: Optional[str] = None,
    documents: Optional[List[Document]] = None,
) -> HybridRetriever:
    """
    从向量库构建混合检索器。

    参数:
        vector_store: Chroma 向量库实例
        texts: 原始文本块列表（用于构建 BM25 索引）。如果为 None，从对应知识库的
               持久化文件加载；文件不存在时从 Chroma 现有文档重建。
        subdir: 知识库子目录名（用于隔离 BM25 索引）
        documents: 与 texts 对应的原始文档（保留来源元数据，可选）

    返回:
        HybridRetriever 实例
    """
    vector_retriever = VectorRetriever(vector_store)

    bm25_path = _bm25_index_path(subdir)
    bm25_retriever = None

    if texts:
        # 有文本块 → 构建新 BM25 索引
        bm25_retriever = BM25Retriever(texts, documents=documents)
        bm25_retriever.save(bm25_path)
    else:
        # 尝试从该知识库的索引文件加载
        bm25_retriever = BM25Retriever.load(bm25_path)
        if bm25_retriever is None:
            # 无法加载 BM25，尝试从 Chroma 中提取文档内容
            logger.warning(f"无法加载 BM25 索引（{bm25_path}），尝试从 Chroma 提取文档")
            try:
                all_docs = vector_store.get()
                all_texts = all_docs.get("documents", [])
                all_metadatas = all_docs.get("metadatas") or []
                if all_texts:
                    rebuilt_docs = [
                        Document(
                            page_content=text,
                            metadata=(all_metadatas[index] if index < len(all_metadatas) else {}) or {},
                        )
                        for index, text in enumerate(all_texts)
                    ]
                    bm25_retriever = BM25Retriever(all_texts, documents=rebuilt_docs)
                    bm25_retriever.save(bm25_path)
                else:
                    logger.error("Chroma 中无文档内容，BM25 回退不可用")
            except Exception as e:
                logger.error(f"从 Chroma 提取文档失败: {e}")

    return HybridRetriever(
        bm25_retriever=bm25_retriever or BM25Retriever([""]),
        vector_retriever=vector_retriever,
        bm25_weight=HYBRID_BM25_WEIGHT,
        vector_weight=HYBRID_VECTOR_WEIGHT,
        fusion=HYBRID_FUSION,
    )


_RERANKER: Optional[Reranker] = None


def build_reranker() -> Reranker:
    """构建重排序器（进程内单例，避免每次生成都重新加载模型）。"""
    global _RERANKER
    if _RERANKER is None:
        _RERANKER = Reranker()
    return _RERANKER
