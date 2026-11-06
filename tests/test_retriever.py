"""
混合检索测试 — 重点验证 RRF 融合的文档去重与分数叠加。

背景：BM25 与向量检索返回的是不同的 Document 实例，
早期实现用 id(doc) 做融合键，导致同一内容被当成两条、融合分数不叠加。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QWEN_API_KEY", "sk-test-key-for-pytest")

import pytest
from langchain_core.documents import Document


TEXTS = [
    "漓江竹筏漂流适合亲子",
    "桂林象鼻山门票55元",
    "阳朔西街夜景推荐",
    "龙脊梯田一日游",
]


class _FakeVectorStore:
    """模拟 Chroma：返回全新的 Document 实例（与 BM25 的对象不同）。"""

    def similarity_search_with_score(self, query, k=4):
        return [
            (Document(page_content=text, metadata={"src": "chroma"}), 0.1 * index)
            for index, text in enumerate(TEXTS[:k])
        ]


@pytest.fixture
def hybrid():
    from src.retriever import BM25Retriever, HybridRetriever, VectorRetriever

    return HybridRetriever(
        bm25_retriever=BM25Retriever(TEXTS),
        vector_retriever=VectorRetriever(_FakeVectorStore()),
    )


def test_fusion_deduplicates_same_content(hybrid):
    """同一内容出现在两路结果中时，融合后只能保留一条。"""
    results = hybrid.search("漓江亲子", k=4)
    contents = [doc.page_content for doc, _ in results]
    assert len(contents) == len(set(contents))


def test_fusion_sums_scores_for_overlap(hybrid):
    """两路都命中的文档，RRF 分数应为两路之和。"""
    results = hybrid.search("漓江亲子", k=4)
    top_doc, top_score = results[0]
    assert top_doc.page_content == TEXTS[0]
    # 1/(60+1) + 1/(60+1)
    assert top_score == pytest.approx(2 / 61)


def test_fusion_keeps_metadata(hybrid):
    """去重后应保留带元数据的版本，便于展示来源。"""
    results = hybrid.search("漓江亲子", k=4)
    assert results[0][0].metadata.get("src") == "chroma"
