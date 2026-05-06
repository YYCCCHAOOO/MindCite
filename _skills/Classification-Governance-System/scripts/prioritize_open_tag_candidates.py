from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import load_config
from safe_io import DATA_CONTRACT_VERSION, atomic_write_json, atomic_write_text, now_iso


WORKFLOW_VERSION = "0.3.0"
CONFIG = load_config(Path(__file__))
OPEN_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidates.json"
PRIORITY_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidate_priority.json"
PRIORITY_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidate_priority.md"
TAXONOMY_PATH = CONFIG.taxonomy_path
BLACKLIST_PATH = CONFIG.indexes_dir / "tag_taxonomy_discard_blacklist.json"

DEFAULT_PARENT_OPTIONS = {
    "theory": ["理论母类", "研究问题", "机制解释"],
    "method": ["模型族", "识别策略", "数据处理方法"],
    "topic": ["研究主题族", "应用场景", "研究对象"],
}

NOISE_TERMS = {"none", "null", "na", "n/a", "todo", "pending", "待分类", "未分类", "其他"}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def normalize_label(value: str) -> str:
    return re.sub(r"[\s_\-:/\\|（）()【】\[\]{}]+", "", value.strip().lower())


def md_cell(value: Any, limit: int = 220) -> str:
    if isinstance(value, list):
        text = "; ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text[:limit]


def official_entries(taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension, entries in (taxonomy.get("dimensions") or {}).items():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "label": label,
                    "level": str(entry.get("level") or ""),
                    "parent": str(entry.get("parent") or ""),
                    "keywords": clean_list(entry.get("keywords")),
                    "aliases": clean_list(entry.get("aliases")),
                }
            )
    return rows


def blacklist_lookup(data: Any) -> set[str]:
    values: list[Any]
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = data.get("discarded_labels") or data.get("labels") or data.get("blacklist") or []
    else:
        values = []
    out: set[str] = set()
    for item in values:
        label = str(item.get("label") if isinstance(item, dict) else item).strip()
        if label:
            out.add(normalize_label(label))
    return out


def similarity(a: str, b: str) -> float:
    na = normalize_label(a)
    nb = normalize_label(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.88
    return SequenceMatcher(None, na, nb).ratio()


def merge_suggestions(label: str, entries: list[dict[str, Any]], limit: int = 5) -> list[str]:
    scored: list[tuple[float, str]] = []
    for entry in entries:
        targets = [entry["label"], *clean_list(entry.get("aliases")), *clean_list(entry.get("keywords"))]
        score = max((similarity(label, target) for target in targets), default=0.0)
        if score >= 0.58:
            scored.append((score, f"{entry['dimension']}:{entry['label']}"))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [target for _, target in scored[:limit]]


def parent_options(dimension: str, entries: list[dict[str, Any]], limit: int = 8) -> list[str]:
    options: list[str] = []
    for entry in entries:
        if entry["dimension"] != dimension:
            continue
        label = str(entry.get("label") or "")
        level = str(entry.get("level") or "")
        if "family" in level or not level:
            options.append(label)
        if len(options) >= limit:
            break
    for option in DEFAULT_PARENT_OPTIONS.get(dimension, []):
        if option not in options:
            options.append(option)
    return options[:limit]


def suggested_role(row: dict[str, Any], blacklisted: set[str]) -> str:
    label = str(row.get("label") or "")
    norm = normalize_label(label)
    if norm in blacklisted or label.lower() in NOISE_TERMS or len(label) > 80:
        return "noise"
    level = str(row.get("suggested_level") or "")
    if "family" in level or int(row.get("matched_notes") or 0) >= 3:
        return "parent"
    return "child"


def default_level(dimension: str, role: str, suggested_level: str) -> str:
    if role == "parent":
        return {"theory": "theory_family", "method": "family", "topic": "topic_family"}.get(dimension, suggested_level or "family")
    if suggested_level:
        return suggested_level
    return {"theory": "theory", "method": "model", "topic": "topic"}.get(dimension, "tag")


def priority_score(row: dict[str, Any], merge_options: list[str], role: str) -> float:
    score = float(row.get("score") or 0)
    score += min(int(row.get("matched_notes") or 0), 10) * 0.5
    if merge_options:
        score += 1.0
    if role == "noise":
        score -= 2.0
    return round(score, 2)


def build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    open_data = read_json(args.input, {"candidates": []})
    taxonomy = read_json(TAXONOMY_PATH, {"dimensions": {}})
    entries = official_entries(taxonomy)
    blacklisted = blacklist_lookup(read_json(BLACKLIST_PATH, {}))
    rows: list[dict[str, Any]] = []

    for raw in open_data.get("candidates") or []:
        label = str(raw.get("label") or "").strip()
        dimension = str(raw.get("source_dimension") or "topic").strip() or "topic"
        merges = merge_suggestions(label, entries)
        role = suggested_role(raw, blacklisted)
        level = default_level(dimension, role, str(raw.get("suggested_level") or ""))
        row = {
            "schema_version": DATA_CONTRACT_VERSION,
            "workflow_version": WORKFLOW_VERSION,
            "operation": "p",
            "suggested_operation": "m" if merges and role != "noise" else ("r" if role == "noise" else "a"),
            "label": label,
            "source_dimension": dimension,
            "dimension_choice": dimension,
            "role_choice": role,
            "level_choice": level,
            "parent_choice": "",
            "parent_options": parent_options(dimension, entries),
            "merge_target": merges[0] if merges else "",
            "merge_options": merges,
            "matched_notes": raw.get("matched_notes") or 0,
            "priority_score": priority_score(raw, merges, role),
            "keywords": clean_list(raw.get("keywords")),
            "sources": clean_list(raw.get("sources")),
            "sample_notes": raw.get("sample_notes") or [],
            "decision_note": "",
            "generated_at": now_iso(),
        }
        rows.append(row)

    rows.sort(key=lambda item: (-float(item["priority_score"]), item["source_dimension"], item["label"].lower()))
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# MindCite v0.3 Tag Taxonomy Decision Table",
        "",
        "编辑 `operation` 列即可完成标签体系审计：`a` 接受；`p` 暂存观察；`m` 合并；`r` 丢弃。",
        "",
        "建议先让 Codex 汇总高优先级标签，再由你只改少量 `operation`、`parent_choice` 和 `merge_target`。",
        "",
        "| operation | suggested_operation | label | source_dimension | dimension_choice | role_choice | level_choice | parent_choice | parent_options | merge_target | merge_options | matched_notes | priority_score | keywords | sample_titles | decision_note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        sample_titles = [sample.get("title", "") for sample in row.get("sample_notes") or []]
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(row.get("operation")),
                    md_cell(row.get("suggested_operation")),
                    md_cell(row.get("label")),
                    md_cell(row.get("source_dimension")),
                    md_cell(row.get("dimension_choice")),
                    md_cell(row.get("role_choice")),
                    md_cell(row.get("level_choice")),
                    md_cell(row.get("parent_choice")),
                    md_cell(row.get("parent_options")),
                    md_cell(row.get("merge_target")),
                    md_cell(row.get("merge_options")),
                    str(row.get("matched_notes") or 0),
                    f"{float(row.get('priority_score') or 0):.2f}",
                    md_cell(row.get("keywords")),
                    md_cell(sample_titles),
                    md_cell(row.get("decision_note")),
                ]
            )
            + " |"
        )
    if not rows:
        lines.append("")
        lines.append("没有需要审计的开放标签候选。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prioritize open tag candidates for taxonomy governance.")
    parser.add_argument("--input", type=Path, default=OPEN_JSON_PATH, help="Open candidates JSON generated by discover_open_tag_candidates.py.")
    args = parser.parse_args()

    rows = build_rows(args)
    payload = {
        "schema_version": DATA_CONTRACT_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "generated_at": now_iso(),
        "input_path": str(args.input),
        "taxonomy_path": str(TAXONOMY_PATH),
        "rows": rows,
    }
    atomic_write_json(PRIORITY_JSON_PATH, payload)
    atomic_write_text(PRIORITY_MD_PATH, render_markdown(rows))
    print(
        json.dumps(
            {
                "ok": True,
                "workflow_version": WORKFLOW_VERSION,
                "rows": len(rows),
                "json_path": str(PRIORITY_JSON_PATH),
                "markdown_path": str(PRIORITY_MD_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
