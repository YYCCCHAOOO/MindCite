from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from researchvault_config import load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
INDEX_PATH = CONFIG.index_path
NOTES_DIR = CONFIG.notes_dir
QUEUE_PATH = CONFIG.indexes_dir / "classification_review_queue.jsonl"
TAXONOMY_PATH = CONFIG.taxonomy_path

DIMENSION_FIELDS = {
    "theory": "suggested_theory_tags",
    "method": "suggested_method_tags",
    "topic": "suggested_topic_tags",
}

DEFAULT_TAXONOMY: dict[str, Any] = {
    "version": "built-in-v2",
    "dimensions": {
        "theory": [
            {
                "label": "金融传染",
                "target_collection_base": "3. 理论文献",
                "target_collection_path": "3. 理论文献 / 1.金融传染",
                "keywords": ["金融传染", "financial contagion", "rational contagion", "market contagion", "crisis contagion", "shift contagion"],
                "negative_keywords": ["disease contagion", "epidemic contagion"],
            },
            {
                "label": "理性疏忽理论",
                "target_collection_base": "3. 理论文献",
                "keywords": ["rational inattention", "information capacity", "shannon information", "信息容量", "理性疏忽"],
                "negative_keywords": [],
            },
            {
                "label": "避险资产理论",
                "target_collection_base": "3. 理论文献",
                "keywords": ["safe haven", "haven currency", "haven currencies", "hedge", "避险"],
                "negative_keywords": ["diversification only"],
            },
        ],
        "method": [
            {
                "label": "MIDAS",
                "target_collection_base": "2. 模型",
                "keywords": ["midas", "mixed data sampling"],
                "negative_keywords": [],
            },
            {
                "label": "DCC-GARCH",
                "target_collection_base": "2. 模型",
                "target_collection_path": "2. 模型 / 4.多元模型 / DCC",
                "keywords": ["dcc-garch", "dcc garch", "dynamic conditional correlation", "re:\\bdcc\\b"],
                "negative_keywords": [],
            },
            {
                "label": "GARCH",
                "target_collection_base": "2. 模型",
                "target_collection_path": "2. 模型 / 4.多元模型 / GARCH",
                "keywords": ["garch-midas", "garch-midas-x", "garch-midas-rv", "garch model"],
                "negative_keywords": [],
            },
        ],
        "topic": [
            {
                "label": "波动溢出",
                "target_collection_base": "4. 主题研究",
                "target_collection_path": "4. 主题研究 / 5.Spillovereffect",
                "keywords": ["volatility spillover", "risk spillover", "connectedness", "波动溢出", "风险溢出"],
                "negative_keywords": [],
            },
            {
                "label": "风险管理",
                "target_collection_base": "4. 主题研究",
                "keywords": ["risk management", "tail risk", "downside risk", "portfolio risk", "风险管理"],
                "negative_keywords": [],
            },
        ],
    },
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_taxonomy(path: Path) -> dict[str, Any]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        source = str(path)
    else:
        data = copy.deepcopy(DEFAULT_TAXONOMY)
        source = "built_in_defaults"

    dimensions = data.get("dimensions") or {}
    normalized: dict[str, Any] = {
        "version": data.get("version") or "unknown",
        "source": source,
        "dimensions": {},
    }
    for dimension in DIMENSION_FIELDS:
        entries: list[dict[str, Any]] = []
        for raw_entry in dimensions.get(dimension) or []:
            label = str(raw_entry.get("label") or "").strip()
            keywords = clean_string_list(raw_entry.get("keywords"))
            if not label or not keywords:
                continue
            entries.append(
                {
                    "label": label,
                    "target_collection_base": str(raw_entry.get("target_collection_base") or "").strip(),
                    "target_collection_path": str(raw_entry.get("target_collection_path") or "").strip(),
                    "description": str(raw_entry.get("description") or "").strip(),
                    "keywords": keywords,
                    "negative_keywords": clean_string_list(raw_entry.get("negative_keywords")),
                }
            )
        normalized["dimensions"][dimension] = entries
    return normalized


def extract_item_key(path: Path) -> str | None:
    if "__" not in path.stem:
        return None
    return path.stem.rsplit("__", 1)[-1].strip() or None


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


def note_excerpt(path: Path, max_chars: int = 1400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def is_papers_note(path: Path) -> bool:
    try:
        rel_parts = path.relative_to(NOTES_DIR).parts
    except ValueError:
        return False
    return len(rel_parts) > 1 and rel_parts[0] == "_papers"


def should_replace_note(candidate: Path, current_path: str) -> bool:
    current = Path(current_path)
    if is_papers_note(candidate) != is_papers_note(current):
        return is_papers_note(candidate)
    try:
        return candidate.stat().st_mtime >= current.stat().st_mtime
    except OSError:
        return True


def scan_notes() -> dict[str, dict[str, Any]]:
    notes: dict[str, dict[str, Any]] = {}
    if not NOTES_DIR.exists():
        return notes
    for path in sorted(NOTES_DIR.rglob("*.md")):
        item_key = extract_item_key(path)
        if not item_key:
            continue
        current = notes.get(item_key)
        if current and not should_replace_note(path, current["note_path"]):
            continue
        notes[item_key] = {
            "item_key": item_key,
            "note_path": str(path),
            "frontmatter": parse_frontmatter(path),
            "excerpt": note_excerpt(path),
        }
    return notes


def flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(flatten_value(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten_value(item)}" for key, item in value.items())
    return str(value)


def keyword_hit(text_lower: str, keyword: str) -> bool:
    needle = keyword.strip().lower()
    if not needle:
        return False
    if needle.startswith("re:"):
        try:
            return re.search(needle[3:], text_lower, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    if re.fullmatch(r"[a-z0-9-]{1,4}", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None
    return needle in text_lower


def match_dimension(text: str, entries: list[dict[str, Any]]) -> tuple[list[str], dict[str, list[str]]]:
    lowered = text.lower()
    labels: list[str] = []
    matched_keywords: dict[str, list[str]] = {}
    for entry in entries:
        negative_hits = [kw for kw in entry["negative_keywords"] if keyword_hit(lowered, kw)]
        if negative_hits:
            continue
        hits = [kw for kw in entry["keywords"] if keyword_hit(lowered, kw)]
        if not hits:
            continue
        label = entry["label"]
        labels.append(label)
        matched_keywords[label] = hits
    return labels, matched_keywords


def compact_evidence(fm: dict[str, Any], excerpt: str) -> str:
    fields = [
        fm.get("theme", ""),
        fm.get("methodology", ""),
        fm.get("theory", ""),
        fm.get("key_finding", ""),
    ]
    evidence = "；".join(flatten_value(field) for field in fields if flatten_value(field))
    return (evidence or excerpt[:240]).strip()


def confidence_for(matched_keywords: dict[str, dict[str, list[str]]]) -> float:
    label_hits = sum(len(labels) for labels in matched_keywords.values())
    keyword_hits = sum(len(keywords) for labels in matched_keywords.values() for keywords in labels.values())
    if label_hits == 0:
        return 0.25
    if keyword_hits >= 6 and label_hits >= 3:
        return 0.75
    if keyword_hits >= 3 or label_hits >= 2:
        return 0.65
    return 0.55


def build_match_text(index_row: dict[str, Any], fm: dict[str, Any]) -> str:
    fields = [
        index_row.get("title", ""),
        fm.get("title", ""),
        fm.get("aliases", ""),
        fm.get("theme", ""),
        fm.get("methodology", ""),
        fm.get("theory", ""),
        fm.get("key_finding", ""),
        fm.get("theory_tags", ""),
        fm.get("method_tags", ""),
        fm.get("topic_tags", ""),
    ]
    return " ".join(flatten_value(value) for value in fields if flatten_value(value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a classification review queue from existing notes.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum notes to include unless --all is set.")
    parser.add_argument("--all", action="store_true", help="Include all scannable notes.")
    parser.add_argument("--item-keys", nargs="+", help="Build the queue for specific item keys; accepts spaces or commas.")
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH, help="Path to classification_taxonomy.json.")
    args = parser.parse_args()

    taxonomy = load_taxonomy(args.taxonomy)
    index_rows = read_jsonl(INDEX_PATH)
    index_by_key = {row.get("item_key"): row for row in index_rows if row.get("item_key")}
    notes = scan_notes()
    rows: list[dict[str, Any]] = []
    requested_item_keys = [
        key.strip()
        for raw in (args.item_keys or [])
        for key in raw.split(",")
        if key.strip()
    ]
    note_items = (
        [(item_key, notes[item_key]) for item_key in requested_item_keys if item_key in notes]
        if requested_item_keys
        else sorted(notes.items(), key=lambda pair: pair[0])
    )

    for item_key, note in note_items:
        index_row = index_by_key.get(item_key, {})
        fm = note["frontmatter"]
        text = build_match_text(index_row, fm)

        suggestions: dict[str, list[str]] = {}
        matched_keywords: dict[str, dict[str, list[str]]] = {}
        for dimension, field_name in DIMENSION_FIELDS.items():
            labels, hits = match_dimension(text, taxonomy["dimensions"].get(dimension, []))
            suggestions[field_name] = labels
            matched_keywords[dimension] = hits

        rows.append(
            {
                "item_key": item_key,
                "title": index_row.get("title") or fm.get("title") or Path(note["note_path"]).stem,
                "current_zotero_collections": index_row.get("collection_paths") or fm.get("zotero_collections") or [],
                "primary_collection": index_row.get("primary_collection_path") or fm.get("primary_collection") or "",
                "suggested_theory_tags": suggestions["suggested_theory_tags"],
                "suggested_method_tags": suggestions["suggested_method_tags"],
                "suggested_topic_tags": suggestions["suggested_topic_tags"],
                "evidence_note_path": note["note_path"],
                "evidence_summary": compact_evidence(fm, note["excerpt"]),
                "matched_keywords": matched_keywords,
                "confidence": confidence_for(matched_keywords),
                "review_status": "pending",
                "taxonomy_source": taxonomy["source"],
                "taxonomy_version": taxonomy["version"],
                "generated_at": now_iso(),
            }
        )
        if not requested_item_keys and not args.all and len(rows) >= args.limit:
            break

    write_jsonl(QUEUE_PATH, rows)
    print(
        json.dumps(
            {
                "ok": True,
                "queue_path": str(QUEUE_PATH),
                "rows": len(rows),
                "taxonomy_source": taxonomy["source"],
                "taxonomy_version": taxonomy["version"],
                "with_theory": sum(1 for row in rows if row["suggested_theory_tags"]),
                "with_method": sum(1 for row in rows if row["suggested_method_tags"]),
                "with_topic": sum(1 for row in rows if row["suggested_topic_tags"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

