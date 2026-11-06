"""
检索质量评测脚本 — 内置业务模板知识库

用途：
  用 20 条人工标注查询，对比 BM25 / 向量 / 混合检索的 Hit@K、Source@K、MRR 与耗时，
  产出一份可复现的评测报告，而不是口头说“检索效果不错”。

用法：
  python scripts/eval_retrieval.py                 # 使用现有索引
  python scripts/eval_retrieval.py --rebuild       # 重建模板知识库后评测
  python scripts/eval_retrieval.py --k 3 --json-out plans/retrieval_eval.json
"""
import argparse
import json
import logging
import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from src.config import TEMPLATE_DIR  # noqa: E402
from src.data_loader import (  # noqa: E402
    TEMPLATE_KB_NAME, load_vector_store, seed_builtin_templates,
)
from src.retriever import build_hybrid_retriever  # noqa: E402


def load_queries(path: Path) -> list:
    queries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def keyword_hit(results, expected_any, k):
    for doc, _ in results[:k]:
        if any(term in doc.page_content for term in expected_any):
            return True
    return False


def source_hit(results, expected_sources, k):
    if not expected_sources:
        return None
    for doc, _ in results[:k]:
        if (doc.metadata or {}).get("source") in expected_sources:
            return True
    return False


def first_hit_rank(results, expected_any):
    for rank, (doc, _) in enumerate(results, start=1):
        if any(term in doc.page_content for term in expected_any):
            return rank
    return None


def evaluate(name, retriever, queries, k, chosen=False):
    rows = []
    latencies = []
    # 预热一次，避免 jieba 词典/首次查询的冷启动时间污染平均耗时
    if queries:
        retriever.search(queries[0]["query"], k=max(k, 5))
    for item in queries:
        start = time.perf_counter()
        results = retriever.search(item["query"], k=max(k, 5))
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

        rows.append({
            "id": item["id"],
            "query": item["query"],
            "hit@1": keyword_hit(results, item["expected_any"], 1),
            "hit@k": keyword_hit(results, item["expected_any"], k),
            "source@k": source_hit(results, item.get("expected_sources"), k),
            "mrr": 1.0 / first_hit_rank(results, item["expected_any"])
            if first_hit_rank(results, item["expected_any"]) else 0.0,
            "latency_ms": round(elapsed_ms, 1),
            "top1": results[0][0].page_content[:60] if results else "",
        })

    total = len(rows)
    source_rows = [row for row in rows if row["source@k"] is not None]
    return {
        "name": name,
        "chosen": chosen,
        "hit@1": round(sum(row["hit@1"] for row in rows) / total, 4),
        f"hit@{k}": round(sum(row["hit@k"] for row in rows) / total, 4),
        f"source@{k}": round(
            sum(row["source@k"] for row in source_rows) / len(source_rows), 4
        ) if source_rows else None,
        "mrr": round(sum(row["mrr"] for row in rows) / total, 4),
        "latency_avg_ms": round(statistics.mean(latencies), 1),
        "latency_p95_ms": round(
            sorted(latencies)[min(len(latencies) - 1, max(0, math.ceil(len(latencies) * 0.95) - 1))],
            1,
        ),
        "rows": rows,
    }


def to_markdown(results, k, query_count, doc_count):
    header = (
        "# 检索评测报告（内置业务模板知识库）\n\n"
        "| 检索方式 | Hit@1 | Hit@{k} | Source@{k} | MRR | 平均耗时 | P95 |\n"
        "|---|---|---|---|---|---|---|"
    ).format(k=k)
    lines = [header]
    for item in results:
        source = "-" if item[f"source@{k}"] is None else f"{item[f'source@{k}']:.2%}"
        lines.append(
            f"| {item['name']} | {item['hit@1']:.2%} | {item[f'hit@{k}']:.2%} | "
            f"{source} | {item['mrr']:.3f} | {item['latency_avg_ms']} ms | "
            f"{item['latency_p95_ms']} ms |"
        )
    lines.append("")
    lines.append(f"- 知识库：{doc_count} 条模板文档")
    lines.append(f"- 评测集：{query_count} 条人工标注查询，cutoff K={k}")
    lines.append("- Source@K 表示 Top-K 中是否命中预期来源文件；BM25 早期版本会丢失元数据，这里已修复")
    lines.append("- 说明：评测查询以实体/主题为主，指标偏乐观；口语化、多跳问题仍需补充")
    lines.append("")

    # 失败样例：便于定位，而不是只报一个好看的总分
    failures = []
    chosen = next((item for item in results if item.get("chosen")), results[-1])
    for row in chosen["rows"]:
        if not row["hit@k"]:
            failures.append(row)
    if failures:
        lines.append(f"### {chosen['name']} 未命中样例（{len(failures)} 条）")
        lines.append("")
        lines.append("| id | 查询 | Top-1 召回片段 |")
        lines.append("|---|---|---|")
        for row in failures:
            lines.append(f"| {row['id']} | {row['query']} | {row['top1']} |")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--queries", default="data/eval/retrieval_queries.jsonl")
    parser.add_argument("--json-out", default="plans/retrieval_eval.json")
    parser.add_argument("--md-out", default="plans/retrieval_eval.md")
    args = parser.parse_args()

    from src.data_loader import _read_template_documents

    doc_count = len(_read_template_documents())
    seeded = seed_builtin_templates(force=args.rebuild)
    if seeded:
        print(f"已重建模板知识库：{seeded} 条")

    store = load_vector_store(TEMPLATE_KB_NAME)
    if store is None:
        raise SystemExit("模板知识库为空，请先运行 seed_builtin_templates()")

    hybrid = build_hybrid_retriever(store, subdir=TEMPLATE_KB_NAME)
    queries = load_queries(Path(args.queries))
    if not queries:
        raise SystemExit(f"评测集为空: {args.queries}")

    from src.retriever import HybridRetriever

    # 对照组：等权 RRF（修复前的策略）
    rrf_hybrid = HybridRetriever(hybrid.bm25, hybrid.vector, fusion="rrf")

    results = [
        evaluate("BM25", hybrid.bm25, queries, args.k),
        evaluate("向量检索", hybrid.vector, queries, args.k),
        evaluate("混合检索-RRF", rrf_hybrid, queries, args.k),
        evaluate("混合检索-向量优先(默认)", hybrid, queries, args.k, chosen=True),
    ]

    markdown = to_markdown(results, args.k, len(queries), doc_count)
    print(markdown)

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "k": args.k,
                "query_count": len(queries),
                "doc_count": doc_count,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    md_path = Path(args.md_out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"已写入 {json_path} 和 {md_path}")


if __name__ == "__main__":
    main()
