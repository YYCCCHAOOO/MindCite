from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
INDEX_PATH = CONFIG.index_path
TAXONOMY_PATH = CONFIG.taxonomy_path
NOTES_DIR = CONFIG.notes_dir
PREVIEW_PATH = CONFIG.indexes_dir / "note_frontmatter_backfill_preview.jsonl"
SUMMARY_PATH = CONFIG.indexes_dir / "note_frontmatter_backfill_summary.md"
AUDIT_PATH = CONFIG.indexes_dir / "note_frontmatter_backfill_audit.md"
DEFAULT_CLASSIFICATION_STATUS = "auto_tagged"

BACKFILL_FIELDS = [
    "zotero_key",
    "zotero_select_uri",
    "zotero_open_pdf_uri",
    "zotero_collections",
    "primary_collection",
    "theory_family_tags",
    "theory_tags",
    "theory_sub_tags",
    "method_family_tags",
    "method_model_tags",
    "method_combo_tags",
    "method_tags",
    "topic_family_tags",
    "topic_tags",
    "classification_status",
    "classification_audit",
]

TAG_FIELDS = [
    "theory_family_tags",
    "theory_tags",
    "theory_sub_tags",
    "method_family_tags",
    "method_model_tags",
    "method_combo_tags",
    "method_tags",
    "topic_family_tags",
    "topic_tags",
]

DIMENSION_DEFAULT_TAG_FIELD = {
    "theory": "theory_tags",
    "method": "method_model_tags",
    "topic": "topic_tags",
}

STRONG_FEATURES = {
    "financial contagion",
    "rational inattention",
    "garch-midas",
    "garch-midas-x",
    "dcc-garch",
    "dynamic conditional correlation",
    "maxmin expected utility",
    "mixed data sampling",
}

STRICT_STRONG_FEATURES_BY_LABEL = {
    "政策不确定性-模糊理论": {
        "ambiguity",
        "knightian uncertainty",
        "maxmin expected utility",
        "non-unique prior",
        "multiple priors",
        "模糊厌恶",
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
    return unique([str(item).strip() for item in value if str(item).strip()])


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def load_taxonomy(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    if not path.exists():
        return {dimension: [] for dimension in DIMENSION_DEFAULT_TAG_FIELD}, {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    dimensions = data.get("dimensions") or {}
    taxonomy: dict[str, list[dict[str, Any]]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSION_DEFAULT_TAG_FIELD:
        entries: list[dict[str, Any]] = []
        for raw_entry in dimensions.get(dimension) or []:
            label = str(raw_entry.get("label") or "").strip()
            keywords = clean_string_list(raw_entry.get("keywords"))
            if not label or not keywords:
                continue
            entry = {
                "label": label,
                "dimension": dimension,
                "level": str(raw_entry.get("level") or "").strip(),
                "tag_field": str(raw_entry.get("tag_field") or DIMENSION_DEFAULT_TAG_FIELD[dimension]).strip(),
                "parent": str(raw_entry.get("parent") or "").strip(),
                "parents": clean_string_list(raw_entry.get("parents")),
                "combines": clean_string_list(raw_entry.get("combines")),
                "keywords": keywords,
                "negative_keywords": clean_string_list(raw_entry.get("negative_keywords")),
                "target_collection_path": str(raw_entry.get("target_collection_path") or "").strip(),
            }
            entries.append(entry)
            by_label[label] = entry
        taxonomy[dimension] = entries
    return taxonomy, by_label


def extract_item_key(path: Path) -> str | None:
    if "__" not in path.stem:
        return None
    return path.stem.rsplit("__", 1)[-1].strip() or None


def split_frontmatter(text: str) -> tuple[str, str, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def parse_frontmatter_text(fm: str) -> dict[str, Any]:
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


def read_note(path: Path) -> tuple[str, dict[str, Any], tuple[str, str, str] | None]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    parts = split_frontmatter(text)
    if not parts:
        return text, {}, None
    _, fm, _ = parts
    return text, parse_frontmatter_text(fm), parts


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
    if re.fullmatch(r"[a-z0-9][a-z0-9\+\./-]{0,30}", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None
    return needle in text_lower


def note_body_without_frontmatter(text: str, parts: tuple[str, str, str] | None) -> str:
    if not parts:
        return text
    return parts[2]


def build_match_text(index_row: dict[str, Any], fm: dict[str, Any], note_text: str, parts: tuple[str, str, str] | None) -> str:
    body = note_body_without_frontmatter(note_text, parts)
    frontmatter_fields = [
        index_row.get("title", ""),
        fm.get("title", ""),
        fm.get("aliases", ""),
        fm.get("theme", ""),
        fm.get("study_area", ""),
        fm.get("data_source", ""),
        fm.get("methodology", ""),
        fm.get("core_variable", ""),
        fm.get("key_finding", ""),
        fm.get("relevance", ""),
        fm.get("theory", ""),
        fm.get("one_sentence_summary", ""),
        fm.get("research_object", ""),
        fm.get("core_problem", ""),
        fm.get("research_context", ""),
        fm.get("method_type", ""),
        fm.get("overall_idea", ""),
        fm.get("key_concepts", ""),
        fm.get("identification_logic", ""),
        fm.get("borrowable_method", ""),
    ]
    # Exclude Zotero collection names and current classification fields: they are display state, not evidence.
    return " ".join(
        flatten_value(value)
        for value in [*frontmatter_fields, body[:24000]]
        if flatten_value(value)
    )


def add_parent_tags(entry: dict[str, Any], proposed: dict[str, list[str]]) -> None:
    dimension = entry["dimension"]
    parents = clean_string_list(entry.get("parents")) or clean_string_list(entry.get("parent"))
    if dimension == "theory":
        proposed["theory_family_tags"].extend(parents)
    elif dimension == "method":
        proposed["method_family_tags"].extend(parents)
    elif dimension == "topic":
        proposed["topic_family_tags"].extend(parents)


def add_entry_tag(entry: dict[str, Any], proposed: dict[str, list[str]], taxonomy_by_label: dict[str, dict[str, Any]]) -> None:
    if entry["dimension"] == "theory" and entry.get("level") == "theory_family":
        # Broad theory families stay visible in matched evidence, but are not written by old-note backfill.
        # Concrete theory tags can still inherit their parent families.
        return
    field_name = entry.get("tag_field") or DIMENSION_DEFAULT_TAG_FIELD[entry["dimension"]]
    if field_name not in proposed:
        field_name = DIMENSION_DEFAULT_TAG_FIELD[entry["dimension"]]
    proposed[field_name].append(entry["label"])
    add_parent_tags(entry, proposed)

    if entry["dimension"] == "method" and entry.get("level") == "combo":
        for component_label in clean_string_list(entry.get("combines")):
            proposed["method_model_tags"].append(component_label)
            component = taxonomy_by_label.get(component_label)
            if component:
                add_parent_tags(component, proposed)


def finalize_tag_fields(proposed: dict[str, list[str]]) -> dict[str, list[str]]:
    for field in TAG_FIELDS:
        proposed[field] = unique(proposed.get(field) or [])
    proposed["method_tags"] = unique(
        proposed["method_family_tags"]
        + proposed["method_model_tags"]
        + proposed["method_combo_tags"]
        + proposed["method_tags"]
    )
    proposed["theory_tags"] = unique(proposed["theory_tags"])
    proposed["topic_tags"] = unique(proposed["topic_tags"])
    return proposed


def match_taxonomy(
    text: str,
    taxonomy: dict[str, list[dict[str, Any]]],
    taxonomy_by_label: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    lowered = text.lower()
    proposed = {field: [] for field in TAG_FIELDS}
    matched_keywords: dict[str, dict[str, list[str]]] = {dimension: {} for dimension in DIMENSION_DEFAULT_TAG_FIELD}

    for dimension, entries in taxonomy.items():
        for entry in entries:
            if any(keyword_hit(lowered, kw) for kw in entry["negative_keywords"]):
                continue
            hits = [kw for kw in entry["keywords"] if keyword_hit(lowered, kw)]
            if not hits:
                continue
            matched_keywords[dimension][entry["label"]] = hits
            if is_high_confidence(entry["label"], hits, lowered):
                add_entry_tag(entry, proposed, taxonomy_by_label)

    return finalize_tag_fields(proposed), matched_keywords


def is_high_confidence(label: str, hits: list[str], text_lower: str) -> bool:
    lowered_hits = " ".join(hit.lower().removeprefix("re:") for hit in hits)
    strict_features = STRICT_STRONG_FEATURES_BY_LABEL.get(label)
    if strict_features is not None:
        return any(feature in lowered_hits or feature in text_lower for feature in strict_features)
    if len(hits) >= 2:
        return True
    if label.lower() in text_lower:
        return True
    return any(feature in lowered_hits for feature in STRONG_FEATURES)


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)


def yaml_list(value: list[str]) -> str:
    if not value:
        return "[]"
    return "\n" + "\n".join(f"  - {yaml_scalar(item)}" for item in value)


def additions_for(row: dict[str, Any], missing_fields: list[str]) -> dict[str, Any]:
    proposed = {
        "zotero_key": row["item_key"],
        "zotero_select_uri": row.get("zotero_select_uri") or "",
        "zotero_open_pdf_uri": row.get("zotero_open_pdf_uri") or "",
        "zotero_collections": row.get("collection_paths") or [],
        "primary_collection": row.get("primary_collection_path") or "",
        "theory_family_tags": row.get("proposed_theory_family_tags") or [],
        "theory_tags": row.get("proposed_theory_tags") or [],
        "theory_sub_tags": row.get("proposed_theory_sub_tags") or [],
        "method_family_tags": row.get("proposed_method_family_tags") or [],
        "method_model_tags": row.get("proposed_method_model_tags") or [],
        "method_combo_tags": row.get("proposed_method_combo_tags") or [],
        "method_tags": row.get("proposed_method_tags") or [],
        "topic_family_tags": row.get("proposed_topic_family_tags") or [],
        "topic_tags": row.get("proposed_topic_tags") or [],
        "classification_status": DEFAULT_CLASSIFICATION_STATUS,
        "classification_audit": [
            "taxonomy_review=accepted_all",
            "source=note_frontmatter_and_note_body",
            "policy=high_confidence_tags_only",
            "per_paper_review=not_required",
        ],
    }
    return {field: proposed[field] for field in BACKFILL_FIELDS if field in missing_fields}


def render_additions(additions: dict[str, Any]) -> str:
    lines: list[str] = []
    for field in BACKFILL_FIELDS:
        if field not in additions:
            continue
        value = additions[field]
        if isinstance(value, list):
            lines.append(f"{field}: []" if not value else f"{field}:{yaml_list(value)}")
        else:
            lines.append(f"{field}: {yaml_scalar(value)}")
    return "\n".join(lines)


def apply_additions(path: Path, parts: tuple[str, str, str], additions: dict[str, Any]) -> None:
    _, fm, body = parts
    rendered = render_additions(additions)
    if not rendered:
        return
    fm = fm.rstrip()
    new_text = f"---\n{fm}\n{rendered}\n---{body}"
    path.write_text(new_text, encoding="utf-8")


def evidence_summary(row: dict[str, Any]) -> str:
    snippets: list[str] = []
    matches = row.get("candidate_matched_keywords") or {}
    for dimension in ["theory", "method", "topic"]:
        labels = matches.get(dimension) or {}
        for label, hits in list(labels.items())[:3]:
            snippets.append(f"{label}: {', '.join(hits[:3])}")
    return "；".join(snippets[:6])


def build_preview_rows(limit: int | None = None, item_keys: list[str] | None = None) -> list[dict[str, Any]]:
    index_rows = read_jsonl(INDEX_PATH)
    index_by_key = {row.get("item_key"): row for row in index_rows if row.get("item_key")}
    taxonomy, taxonomy_by_label = load_taxonomy(TAXONOMY_PATH)
    wanted = set(item_keys or [])

    rows: list[dict[str, Any]] = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        item_key = extract_item_key(path)
        if not item_key:
            continue
        if wanted and item_key not in wanted:
            continue
        text, fm, parts = read_note(path)
        missing_fields = [field for field in BACKFILL_FIELDS if field not in fm]
        if not missing_fields:
            continue
        index_row = index_by_key.get(item_key)
        if not index_row:
            rows.append(
                {
                    "item_key": item_key,
                    "note_path": str(path),
                    "missing_fields": missing_fields,
                    "reason": "item_key not found in zotero_library_index.jsonl",
                    "will_modify": False,
                }
            )
            continue

        proposed_tags, matched_keywords = match_taxonomy(
            build_match_text(index_row, fm, text, parts),
            taxonomy,
            taxonomy_by_label,
        )
        row = {
            "item_key": item_key,
            "title": index_row.get("title") or fm.get("title") or path.stem,
            "note_path": str(path),
            "missing_fields": missing_fields,
            "proposed_zotero_collections": index_row.get("collection_paths") or [],
            "proposed_primary_collection": index_row.get("primary_collection_path") or "",
            "proposed_theory_family_tags": proposed_tags["theory_family_tags"],
            "proposed_theory_tags": proposed_tags["theory_tags"],
            "proposed_theory_sub_tags": proposed_tags["theory_sub_tags"],
            "proposed_method_family_tags": proposed_tags["method_family_tags"],
            "proposed_method_model_tags": proposed_tags["method_model_tags"],
            "proposed_method_combo_tags": proposed_tags["method_combo_tags"],
            "proposed_method_tags": proposed_tags["method_tags"],
            "proposed_topic_family_tags": proposed_tags["topic_family_tags"],
            "proposed_topic_tags": proposed_tags["topic_tags"],
            "candidate_matched_keywords": matched_keywords,
            "classification_status": DEFAULT_CLASSIFICATION_STATUS,
            "has_frontmatter": parts is not None,
            "will_modify": False,
        }
        row["evidence_summary"] = evidence_summary(row)
        row["frontmatter_additions"] = additions_for(row | index_row, missing_fields)
        row["frontmatter_additions_yaml"] = render_additions(row["frontmatter_additions"])
        rows.append(row)

        if limit is not None and len(rows) >= limit:
            break
    return rows


def write_summary(path: Path, rows: list[dict[str, Any]], apply: bool, preview_path: Path, audit_path: Path) -> None:
    missing_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    for row in rows:
        missing_counter.update(row.get("missing_fields") or [])
        for field in [
            "proposed_theory_family_tags",
            "proposed_theory_tags",
            "proposed_method_family_tags",
            "proposed_method_model_tags",
            "proposed_method_combo_tags",
            "proposed_topic_family_tags",
            "proposed_topic_tags",
        ]:
            if row.get(field):
                tag_counter[field] += 1

    lines = [
        "# Note Frontmatter Backfill Summary",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Mode: `{'apply' if apply else 'dry-run'}`",
        f"- Preview path: `{preview_path}`",
        f"- Audit path: `{audit_path}`",
        f"- Rows: `{len(rows)}`",
        f"- Rows without index row: `{sum(1 for row in rows if row.get('reason'))}`",
        f"- Rows without parseable frontmatter: `{sum(1 for row in rows if row.get('has_frontmatter') is False)}`",
        f"- Rows that would modify notes now: `{sum(1 for row in rows if row.get('will_modify'))}`",
        f"- Rows with proposed theory family tags: `{tag_counter.get('proposed_theory_family_tags', 0)}`",
        f"- Rows with proposed theory tags: `{tag_counter.get('proposed_theory_tags', 0)}`",
        f"- Rows with proposed method family tags: `{tag_counter.get('proposed_method_family_tags', 0)}`",
        f"- Rows with proposed method model tags: `{tag_counter.get('proposed_method_model_tags', 0)}`",
        f"- Rows with proposed method combo tags: `{tag_counter.get('proposed_method_combo_tags', 0)}`",
        f"- Rows with proposed topic family tags: `{tag_counter.get('proposed_topic_family_tags', 0)}`",
        f"- Rows with proposed topic tags: `{tag_counter.get('proposed_topic_tags', 0)}`",
        "",
        "## Missing Fields",
        "",
    ]
    for field in BACKFILL_FIELDS:
        lines.append(f"- `{field}`: `{missing_counter.get(field, 0)}`")

    lines.extend(["", "## Samples", ""])
    for row in rows[:10]:
        lines.append(
            f"- `{row.get('item_key')}` | `{row.get('title', '')}` | "
            f"theory_family={row.get('proposed_theory_family_tags') or []} | "
            f"theory={row.get('proposed_theory_tags') or []} | "
            f"method_family={row.get('proposed_method_family_tags') or []} | "
            f"method_model={row.get('proposed_method_model_tags') or []} | "
            f"method_combo={row.get('proposed_method_combo_tags') or []} | "
            f"topic={row.get('proposed_topic_tags') or []}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def md_cell(value: Any, limit: int = 160) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "\\|")
    return text[:limit]


def write_audit_table(path: Path, rows: list[dict[str, Any]], preview_path: Path) -> None:
    lines = [
        "# 旧 Notes 属性补齐审计表",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Source preview: `{preview_path}`",
        "- 这是给你看的人工审计入口。可以把 `review_status` 改成 `approved`、`rejected`、`needs_edit`，也可以直接告诉 Codex 哪些条目通过。",
        "- JSONL 预览是机器可读源文件；这个 Markdown 表适合在 Obsidian 里快速扫读、批注和确认。",
        "- 本轮仍是 dry-run，表格里的候选标签不会自动写入 notes。",
        "",
        "| review_status | item_key | title | theory_family | theory | method_family | method_model | method_combo | topic | evidence | note_path |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row.get("reason"):
            status = "needs_index_check"
        else:
            status = "pending"
        lines.append(
            "| "
            + " | ".join(
                [
                    status,
                    md_cell(row.get("item_key"), 40),
                    md_cell(row.get("title"), 120),
                    md_cell(row.get("proposed_theory_family_tags"), 120),
                    md_cell(row.get("proposed_theory_tags"), 120),
                    md_cell(row.get("proposed_method_family_tags"), 120),
                    md_cell(row.get("proposed_method_model_tags"), 120),
                    md_cell(row.get("proposed_method_combo_tags"), 120),
                    md_cell(row.get("proposed_topic_tags"), 120),
                    md_cell(row.get("evidence_summary"), 180),
                    md_cell(row.get("note_path"), 180),
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_item_keys(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [key.strip() for raw in values for key in raw.split(",") if key.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or apply missing hierarchical frontmatter fields for notes.")
    parser.add_argument("--limit", type=int, help="Only preview the first N matching notes.")
    parser.add_argument("--item-keys", nargs="+", help="Only preview these item keys; accepts spaces or commas.")
    parser.add_argument("--preview-path", type=Path, default=PREVIEW_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--audit-path", type=Path, default=AUDIT_PATH)
    parser.add_argument("--apply", action="store_true", help="Actually modify notes. Default is dry-run only.")
    parser.add_argument("--backup-dir", type=Path, help="Backup directory used only with --apply.")
    args = parser.parse_args()

    rows = build_preview_rows(limit=args.limit, item_keys=parse_item_keys(args.item_keys))

    if args.apply:
        backup_dir = args.backup_dir or ROOT / "logs" / "note_frontmatter_backfill_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        rows_by_path = {row["note_path"]: row for row in rows if row.get("has_frontmatter") and row.get("frontmatter_additions")}
        for note_path, row in rows_by_path.items():
            path = Path(note_path)
            _, _, parts = read_note(path)
            if not parts:
                continue
            backup_path = backup_dir / path.relative_to(NOTES_DIR)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            apply_additions(path, parts, row["frontmatter_additions"])
            row["will_modify"] = True
            row["backup_path"] = str(backup_path)
    else:
        for row in rows:
            row["will_modify"] = False

    write_jsonl(args.preview_path, rows)
    write_audit_table(args.audit_path, rows, args.preview_path)
    write_summary(args.summary_path, rows, apply=args.apply, preview_path=args.preview_path, audit_path=args.audit_path)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "apply" if args.apply else "dry-run",
                "preview_path": str(args.preview_path),
                "summary_path": str(args.summary_path),
                "audit_path": str(args.audit_path),
                "rows": len(rows),
                "will_modify": sum(1 for row in rows if row.get("will_modify")),
                "with_theory_tags": sum(1 for row in rows if row.get("proposed_theory_tags")),
                "with_method_family_tags": sum(1 for row in rows if row.get("proposed_method_family_tags")),
                "with_method_model_tags": sum(1 for row in rows if row.get("proposed_method_model_tags")),
                "with_method_combo_tags": sum(1 for row in rows if row.get("proposed_method_combo_tags")),
                "with_topic_tags": sum(1 for row in rows if row.get("proposed_topic_tags")),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
