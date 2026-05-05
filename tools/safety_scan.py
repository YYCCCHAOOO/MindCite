from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {
    ".bak",
    ".caj",
    ".copy",
    ".csv",
    ".db",
    ".docx",
    ".feather",
    ".jsonl",
    ".parquet",
    ".pdf",
    ".pyc",
    ".sqlite",
    ".tsv",
    ".xlsx",
}
IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv"}
CONTENT_PATTERNS = {
    "private_researchvault_path": re.compile(r"D:\\ResearchVault", re.IGNORECASE),
    "private_user_path": re.compile(r"C:\\Users\\64111", re.IGNORECASE),
    "openai_style_secret": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "nonempty_json_api_key": re.compile(r'"api_key"\s*:\s*"(?!")([^"]+)"', re.IGNORECASE),
    "nonempty_env_secret": re.compile(
        r"^(?:DEEPSEEK|SILICONFLOW|OPENAI|ANTHROPIC|GEMINI)_API_KEY=(?!\s*$|<)[^\r\n]+$",
        re.MULTILINE,
    ),
}


def should_skip(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def scan() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in ROOT.rglob("*"):
        if should_skip(path) or path.is_dir():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in BLOCKED_SUFFIXES and not rel.startswith("examples/demo-vault/"):
            findings.append({"type": "blocked_file_suffix", "path": rel, "detail": path.suffix})
            continue
        if path.name == ".env":
            findings.append({"type": "local_env_file", "path": rel, "detail": "do not commit .env"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in CONTENT_PATTERNS.items():
            if pattern.search(text):
                findings.append({"type": name, "path": rel, "detail": "content pattern matched"})
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print(json.dumps({"ok": False, "findings": findings}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "findings": []}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
