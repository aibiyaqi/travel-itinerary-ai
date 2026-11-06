"""
提交前/CI 敏感信息检查。

用途：
  - 防止 .env、数据库、私钥、真实 API Key 被提交；
  - 在 CI 中作为第一道门禁（GitHub Actions 会设置 CI=true）。

用法：
  python scripts/check_secrets.py
  python scripts/check_secrets.py --strict   # 本地也把 .env/db 视为错误
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".tools", ".secrets", ".npm-cache", ".pytest_cache",
    "__pycache__", "chroma_db", "exports", "node_modules", ".venv", "venv",
}
SKIP_FILES = {
    # 本地个人文档（已被 .gitignore 排除），不在扫描范围内
    "plans/pro_end执行版.md",
    "plans/项目复盘_面试版.md",
    "plans/排查.md",
}
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".yml", ".yaml", ".json", ".jsonl", ".html",
    ".conf", ".example", ".dockerignore", ".gitignore", ".toml", ".ini", ".cfg",
}
SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
SENSITIVE_SUFFIXES = {".db", ".sqlite3", ".pem", ".key", ".p12", ".pfx"}

PATTERNS = [
    ("API Key (sk-)", re.compile(r"sk-[A-Za-z0-9]{24,}")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("私钥", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("默认管理员口令", re.compile(r"Admin@" + "2024")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
]


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(ROOT).as_posix()
            if rel in SKIP_FILES:
                continue
            yield rel, path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="本地也把 .env/数据库视为错误")
    args = parser.parse_args()
    strict = args.strict or os.environ.get("CI", "").lower() == "true"

    errors = []
    warnings = []

    for rel, path in iter_files():
        lower = rel.lower()
        name = path.name.lower()

        if name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            message = f"敏感文件: {rel}"
            (errors if strict else warnings).append(message)
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES and not name.endswith((".example", ".gitignore", ".dockerignore")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                # 测试里的全 0 占位号码不算 PII
                if label == "手机号" and set(match.group()) == {"0"}:
                    continue
                # 只输出位置，不回显命中的敏感值（避免日志二次泄露）
                errors.append(f"{label}: {rel}")

    for message in warnings:
        print(f"WARN  {message}")
    for message in errors:
        print(f"ERROR {message}")

    if errors:
        print(f"\n发现 {len(errors)} 个敏感信息问题，已阻止提交。")
        return 1
    print(f"通过：扫描 {len(list(iter_files()))} 个文件，未发现敏感信息。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
