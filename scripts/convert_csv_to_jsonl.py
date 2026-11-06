"""
CSV -> JSONL 转换脚本
=====================
读取 easy.csv，提取有效字段，清洗噪音，输出 clean JSONL。

清洗规则：
  - 移除：uid（序列号）、hard_logic_py（Python 代码）、limit_rooms / limits_room_type（布尔值噪音）
  - 保留：nature_language（用户自然语言）-> prompt
  - 保留：start_city, target_city, days, people_number, budget -> 结构化 response
  - 保留：tag -> 分类标签
"""

import csv
import json
import re
import os
import sys

# Windows GBK 终端兼容
sys.stdout.reconfigure(encoding="utf-8")


def extract_budget_from_nature(text: str) -> int:
    """从自然语言文本中提取预算金额（如"预算1500人民币"->1500）"""
    match = re.search(r"预算(\d+)(?:元|人民币)?", text)
    if match:
        return int(match.group(1))
    return 0


def build_response(row: dict) -> str:
    """从 CSV 行构建结构化 response 文本"""
    start_city = row.get("start_city", "").strip()
    target_city = row.get("target_city", "").strip()
    days = row.get("days", "").strip()
    people = row.get("people_number", "").strip()
    budget = extract_budget_from_nature(row.get("nature_language", ""))

    parts = []
    if start_city and target_city:
        parts.append(f"出发城市：{start_city}，目标城市：{target_city}")
    if days:
        parts.append(f"天数：{days}天")
    if people:
        parts.append(f"人数：{people}人")
    if budget > 0:
        parts.append(f"预算：{budget}元")
    parts.append(f"标签：{row.get('tag', '').strip()}")

    return "，".join(parts)


def convert_csv_to_jsonl(csv_path: str, jsonl_path: str) -> int:
    """
    将 easy.csv 转换为 clean JSONL。

    返回写入的行数。
    """
    count = 0
    with open(csv_path, "r", encoding="utf-8") as f_in, \
         open(jsonl_path, "w", encoding="utf-8") as f_out:

        reader = csv.DictReader(f_in)
        for row in reader:
            nature_lang = row.get("nature_language", "").strip()
            nature_lang_en = row.get("nature_language_en", "").strip()

            if not nature_lang and not nature_lang_en:
                continue  # 跳过空行

            prompt = nature_lang or nature_lang_en
            response = build_response(row)

            entry = {
                "prompt": prompt,
                "response": response,
                "metadata": {
                    "start_city": row.get("start_city", "").strip(),
                    "target_city": row.get("target_city", "").strip(),
                    "days": int(row.get("days", 0)) if row.get("days", "").strip().isdigit() else 0,
                    "people_number": int(row.get("people_number", 0)) if row.get("people_number", "").strip().isdigit() else 0,
                    "budget": extract_budget_from_nature(nature_lang),
                    "tag": row.get("tag", "").strip(),
                },
            }

            if nature_lang_en:
                entry["prompt_en"] = nature_lang_en

            f_out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    return count


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, "easy.csv")
    jsonl_path = os.path.join(base_dir, "easy.jsonl")

    if not os.path.exists(csv_path):
        print(f"[错误] 未找到 CSV 文件: {csv_path}")
        return

    count = convert_csv_to_jsonl(csv_path, jsonl_path)
    print(f"[完成] 转换完成！共处理 {count} 条记录")
    print(f"       输出文件: {jsonl_path}")

    # 预览前 3 条
    print("\n[预览] 前 3 条 JSONL 记录：")
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 3:
                break
            data = json.loads(line)
            print(f"\n--- 记录 {i+1} ---")
            print(f"  prompt:   {data['prompt'][:60]}...")
            print(f"  response: {data['response']}")
            print(f"  metadata: {json.dumps(data['metadata'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
