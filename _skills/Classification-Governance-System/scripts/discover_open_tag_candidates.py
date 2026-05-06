from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
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
NOTES_DIR = CONFIG.notes_papers_dir
TAXONOMY_PATH = CONFIG.taxonomy_path
BLACKLIST_PATH = CONFIG.indexes_dir / "tag_taxonomy_discard_blacklist.json"
OPEN_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidates.json"
OPEN_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidates.md"

TAG_FIELDS: dict[str, dict[str, str]] = {
    "theory": {
        "theory_family_tags": "theory_family",
        "theory_tags": "theory",
        "theory_sub_tags": "theory_sub",
    },
    "method": {
        "method_family_tags": "family",
        "method_model_tags": "model",
        "method_combo_tags": "combo",
        "method_tags": "model",
    },
    "topic": {
        "topic_family_tags": "topic_family",
        "topic_tags": "topic",
    },
}

TEXT_FIELDS = [
    "title",
    "aliases",
    "zotero_collections",
    "primary_collection",
    "classification_audit",
    "publication_tags",
]

SEED_RULES = [
    {
        "label": "GARCH family",
        "dimension": "method",
        "level": "family",
        "keywords": ["garch", "egarch", "dcc-garch", "volatility model"],
    },
    {
        "label": "VAR family",
        "dimension": "method",
        "level": "family",
        "keywords": ["var", "svar", "vector autoregression", "impulse response"],
    },
    {
        "label": "Network connectedness",
        "dimension": "method",
        "level": "model",
        "keywords": ["connectedness", "spillover index", "network centrality"],
    },
    {
        "label": "Event study",
        "dimension": "method",
        "level": "model",
        "keywords": ["event study", "abnormal return", "announcement effect"],
    },
    {
        "label": "Financial contagion",
        "dimension": "theory",
        "level": "theory",
        "keywords": ["financial contagion", "contagion effect", "crisis contagion"],
    },
    {
        "label": "Systemic risk",
        "dimension": "theory",
        "level": "theory",
        "keywords": ["systemic risk", "macroprudential", "financial stability"],
    },
    {
        "label": "Exchange rate risk",
        "dimension": "topic",
        "level": "topic",
        "keywords": ["exchange rate risk", "currency risk", "fx volatility"],
    },
    {
        "label": "Climate finance",
        "dimension": "topic",
        "level": "topic",
        "keywords": ["climate finance", "green finance", "carbon market", "climate risk"],
    },
]


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
        text = str(item).strip().strip('"').strip("'")
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def normalize_label(value: str) -> str:
    return re.sub(r"[\s_\-:/\\|（）()【】\[\]{}]+", "", value.strip().lower())


def looks_like_noise(label: str) -> bool:
    stripped = label.strip()
    if not stripped:
        return True
    if len(stripped) <= 1 or len(stripped) > 80:
        return True
    if stripped.lower() in {"none", "null", "na", "n/a", "todo", "pending", "待分类", "未分类"}:
        return True
    if re.fullmatch(r"[\d\W_]+", stripped, flags=re.UNICODE):
        return True
    return False


def frontmatter_text(text: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        fm = frontmatter_text(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in fm.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            parsed.setdefault(current_key, []).append(line[4:].strip().strip('"'))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "[]":
                parsed[key] = []
            elif value:
                parsed[key] = value.strip().strip('"')
            else:
                parsed[key] = []
    return parsed


def note_body_text(path: Path, max_chars: int = 6000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def extract_item_key(path: Path, fm: dict[str, Any]) -> str:
    key = str(fm.get("zotero_key") or "").strip()
    if key:
        return key
    if "__" in path.stem:
        return path.stem.rsplit("__", 1)[-1].strip()
    return path.stem


def taxonomy_lookup(taxonomy: dict[str, Any]) -> tuple[set[str], set[str]]:
    official: set[str] = set()
    aliases: set[str] = set()
    for entries in (taxonomy.get("dimensions") or {}).values():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if label:
                official.add(normalize_label(label))
            for field in ("aliases", "merged_candidates"):
                for alias in clean_list(entry.get(field)):
                    aliases.add(normalize_label(alias))
    return official, aliases


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
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
        else:
            label = str(item).strip()
        if label:
            out.add(normalize_label(label))
    return out


def md_cell(value: Any, limit: int = 180) -> str:
    if isinstance(value, list):
        text = "; ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text[:limit]


def candidate_key(label: str, dimension: str) -> str:
    return f"{dimension}:{normalize_label(label)}"


def add_candidate(
    candidates: dict[str, dict[str, Any]],
    *,
    label: str,
    dimension: str,
    level: str,
    source: str,
    note: dict[str, str],
    evidence: list[str],
) -> None:
    label = label.strip()
    if looks_like_noise(label):
        return
    key = candidate_key(label, dimension)
    row = candidates.setdefault(
        key,
        {
            "schema_version": DATA_CONTRACT_VERSION,
            "workflow_version": WORKFLOW_VERSION,
            "label": label,
            "source_dimension": dimension,
            "suggested_level": level,
            "sources": [],
            "keywords": [],
            "matched_notes": 0,
            "score": 0.0,
            "sample_notes": [],
            "created_at": now_iso(),
        },
    )
    if source not in row["sources"]:
        row["sources"].append(source)
    for item in evidence:
        if item and item not in row["keywords"]:
            row["keywords"].append(item)
    existing_keys = {sample.get("item_key") for sample in row["sample_notes"]}
    if note["item_key"] not in existing_keys:
        row["matched_notes"] += 1
        row["score"] = float(row["matched_notes"]) + min(len(row["keywords"]), 8) * 0.1
        if len(row["sample_notes"]) < 5:
            row["sample_notes"].append(note)


def collect_note_text(fm: dict[str, Any], body: str) -> str:
    parts: list[str] = [body]
    for field in TEXT_FIELDS:
        value = fm.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def discover_candidates(args: argparse.Namespace) -> list[dict[str, Any]]:
    taxonomy = read_json(TAXONOMY_PATH, {"dimensions": {}})
    official_labels, official_aliases = taxonomy_lookup(taxonomy)
    blacklisted = blacklist_lookup(read_json(BLACKLIST_PATH, {}))
    ignored = official_labels | official_aliases | blacklisted

    candidates: dict[str, dict[str, Any]] = {}
    note_paths = sorted(NOTES_DIR.rglob("*.md")) if NOTES_DIR.exists() else []
    for path in note_paths:
        fm = parse_frontmatter(path)
        title = str(fm.get("title") or path.stem).strip()
        note = {
            "item_key": extract_item_key(path, fm),
            "title": title,
            "note_path": str(path),
        }
        for dimension, fields in TAG_FIELDS.items():
            for field, level in fields.items():
                for label in clean_list(fm.get(field)):
                    if normalize_label(label) in ignored:
                        continue
                    add_candidate(
                        candidates,
                        label=label,
                        dimension=dimension,
                        level=level,
                        source=f"frontmatter:{field}",
                        note=note,
                        evidence=[label],
                    )

        if not args.no_seed_rules:
            text = collect_note_text(fm, note_body_text(path))
            for rule in SEED_RULES:
                label = str(rule["label"])
                if normalize_label(label) in ignored:
                    continue
                hits = [kw for kw in clean_list(rule.get("keywords")) if kw.lower() in text]
                if hits:
                    add_candidate(
                        candidates,
                        label=label,
                        dimension=str(rule["dimension"]),
                        level=str(rule["level"]),
                        source="seed_rule",
                        note=note,
                        evidence=hits,
                    )

    rows = [row for row in candidates.values() if int(row["matched_notes"]) >= args.min_notes]
    rows.sort(key=lambda row: (-float(row["score"]), row["source_dimension"], row["label"].lower()))
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# MindCite v0.3 Open Tag Candidates",
        "",
        "这个文件用于做标签体系审计：先发现 notes 中出现但尚未进入正式 taxonomy 的候选标签，再交给用户判断是否需要存在。",
        "",
        "操作列说明：`a` 接受为正式标签；`p` 暂存观察；`m` 合并到已有标签；`r` 丢弃并加入黑名单。默认先保留为 `p`。",
        "",
        "| operation | label | source_dimension | dimension_choice | role_choice | level_choice | parent_choice | parent_options | merge_target | merge_options | matched_notes | score | sample_titles | decision_note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        sample_titles = [sample.get("title", "") for sample in row.get("sample_notes") or []]
        lines.append(
            "| "
            + " | ".join(
                [
                    "p",
                    md_cell(row.get("label")),
                    md_cell(row.get("source_dimension")),
                    md_cell(row.get("source_dimension")),
                    "child",
                    md_cell(row.get("suggested_level")),
                    "",
                    "",
                    "",
                    "",
                    str(row.get("matched_notes") or 0),
                    f"{float(row.get('score') or 0):.2f}",
                    md_cell(sample_titles),
                    "",
                ]
            )
            + " |"
        )
    if not rows:
        lines.append("")
        lines.append("未发现开放候选标签。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover open tag candidates from MindCite notes.")
    parser.add_argument("--min-notes", type=int, default=1, help="Minimum note count for a candidate to be reported.")
    parser.add_argument("--no-seed-rules", action="store_true", help="Only use note frontmatter tags, skip generic seed rules.")
    args = parser.parse_args()

    rows = discover_candidates(args)
    payload = {
        "schema_version": DATA_CONTRACT_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "generated_at": now_iso(),
        "root": str(CONFIG.root),
        "notes_dir": str(NOTES_DIR),
        "taxonomy_path": str(TAXONOMY_PATH),
        "min_notes": args.min_notes,
        "candidates": rows,
    }
    atomic_write_json(OPEN_JSON_PATH, payload)
    atomic_write_text(OPEN_MD_PATH, render_markdown(rows))
    print(
        json.dumps(
            {
                "ok": True,
                "workflow_version": WORKFLOW_VERSION,
                "candidates": len(rows),
                "json_path": str(OPEN_JSON_PATH),
                "markdown_path": str(OPEN_MD_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
