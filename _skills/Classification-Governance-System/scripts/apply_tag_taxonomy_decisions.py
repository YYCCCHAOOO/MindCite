from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import load_config
from safe_io import DATA_CONTRACT_VERSION, atomic_write_json, atomic_write_text, backup_file, now_iso


WORKFLOW_VERSION = "0.3.0"
CONFIG = load_config(Path(__file__))
TAXONOMY_PATH = CONFIG.taxonomy_path
BLACKLIST_PATH = CONFIG.indexes_dir / "tag_taxonomy_discard_blacklist.json"
PRIORITY_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidate_priority.json"
PRIORITY_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_open_candidate_priority.md"
PREVIEW_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_decision_preview_summary.json"
PREVIEW_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_decision_preview_summary.md"
APPLY_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_decision_apply_summary.json"
APPLY_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_decision_apply_summary.md"

VALID_OPERATIONS = {"a", "p", "m", "r", ""}
DIMENSIONS = {"theory", "method", "topic"}
TAG_FIELD_BY_LEVEL = {
    "theory": {
        "theory_family": "theory_family_tags",
        "family": "theory_family_tags",
        "theory": "theory_tags",
        "theory_sub": "theory_sub_tags",
        "sub": "theory_sub_tags",
    },
    "method": {
        "family": "method_family_tags",
        "model": "method_model_tags",
        "combo": "method_combo_tags",
        "method": "method_model_tags",
    },
    "topic": {
        "topic_family": "topic_family_tags",
        "family": "topic_family_tags",
        "topic": "topic_tags",
    },
}
DEFAULT_BASE = {
    "theory": "Theory",
    "method": "Methods",
    "topic": "Topics",
}


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
        if ";" in value:
            value = value.split(";")
        else:
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


def ordered_unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = normalize_label(text)
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def normalize_label(value: str) -> str:
    return re.sub(r"[\s_\-:/\\|（）()【】\[\]{}]+", "", value.strip().lower())


def split_target(value: str) -> tuple[str | None, str]:
    raw = value.strip()
    if ":" in raw:
        prefix, label = raw.split(":", 1)
        prefix = prefix.strip().lower()
        if prefix in DIMENSIONS:
            return prefix, label.strip()
    return None, raw


def md_split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def read_markdown_decisions(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return {}
    header = [cell.strip() for cell in md_split_row(lines[0])]
    decisions: dict[str, dict[str, str]] = {}
    for line in lines[2:]:
        if re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?", line):
            continue
        cells = md_split_row(line)
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        row = {header[idx]: cells[idx].strip() for idx in range(len(header))}
        label = row.get("label", "").strip()
        source_dimension = row.get("source_dimension", "").strip()
        if label:
            decisions[f"{source_dimension}:{normalize_label(label)}"] = row
            decisions[normalize_label(label)] = row
    return decisions


def overlay_markdown_rows(rows: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    decisions = read_markdown_decisions(path)
    if not decisions:
        return rows
    out: list[dict[str, Any]] = []
    editable_fields = [
        "operation",
        "dimension_choice",
        "role_choice",
        "level_choice",
        "parent_choice",
        "merge_target",
        "decision_note",
    ]
    for row in rows:
        label = str(row.get("label") or "")
        source_dimension = str(row.get("source_dimension") or "")
        decision = decisions.get(f"{source_dimension}:{normalize_label(label)}") or decisions.get(normalize_label(label))
        patched = dict(row)
        if decision:
            for field in editable_fields:
                if field in decision and decision[field].strip():
                    patched[field] = decision[field].strip()
        out.append(patched)
    return out


def md_cell(value: Any, limit: int = 260) -> str:
    if isinstance(value, list):
        text = "; ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text[:limit]


def ensure_taxonomy(data: dict[str, Any]) -> dict[str, Any]:
    taxonomy = deepcopy(data) if data else {}
    taxonomy.setdefault("schema_version", DATA_CONTRACT_VERSION)
    taxonomy.setdefault("version", "local")
    taxonomy.setdefault("source", "mindcite-local-taxonomy")
    taxonomy.setdefault("dimensions", {})
    for dimension in DIMENSIONS:
        taxonomy["dimensions"].setdefault(dimension, [])
    return taxonomy


def dimension_base(taxonomy: dict[str, Any], dimension: str) -> str:
    for entry in taxonomy.get("dimensions", {}).get(dimension, []) or []:
        base = str(entry.get("target_collection_base") or "").strip()
        if base:
            return base
    return DEFAULT_BASE.get(dimension, dimension.title())


def tag_field(dimension: str, level: str) -> str:
    return TAG_FIELD_BY_LEVEL.get(dimension, {}).get(level, TAG_FIELD_BY_LEVEL.get(dimension, {}).get("topic", "tags"))


def taxonomy_index(taxonomy: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    for dimension, entries in (taxonomy.get("dimensions") or {}).items():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if label:
                index[f"{dimension}:{normalize_label(label)}"] = (dimension, entry)
                index[normalize_label(label)] = (dimension, entry)
            for alias in clean_list(entry.get("aliases")):
                index[f"{dimension}:{normalize_label(alias)}"] = (dimension, entry)
    return index


def label_exists(taxonomy: dict[str, Any], dimension: str, label: str) -> bool:
    wanted = normalize_label(label)
    for entry in taxonomy.get("dimensions", {}).get(dimension, []) or []:
        if normalize_label(str(entry.get("label") or "")) == wanted:
            return True
    return False


def build_entry(row: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    label = str(row.get("label") or "").strip()
    dimension = str(row.get("dimension_choice") or row.get("source_dimension") or "topic").strip()
    role = str(row.get("role_choice") or "child").strip()
    level = str(row.get("level_choice") or "").strip()
    if role == "parent" and not level:
        level = {"theory": "theory_family", "method": "family", "topic": "topic_family"}.get(dimension, "family")
    if not level:
        level = {"theory": "theory", "method": "model", "topic": "topic"}.get(dimension, "tag")
    parent = str(row.get("parent_choice") or "").strip()
    base = dimension_base(taxonomy, dimension)
    path_parts = [base]
    if parent:
        path_parts.append(parent)
    path_parts.append(label)
    keywords = ordered_unique([label, *clean_list(row.get("keywords"))])
    return {
        "label": label,
        "level": level,
        "role": role,
        "parent": parent,
        "tag_field": tag_field(dimension, level),
        "target_collection_base": base,
        "target_collection_path": " / ".join(path_parts),
        "keywords": keywords,
        "aliases": [],
        "negative_keywords": [],
        "review_status": "accepted",
        "accepted_at": now_iso(),
        "accepted_source": "mindcite-v0.3-tag-governance",
        "decision_note": str(row.get("decision_note") or "").strip(),
    }


def blacklist_data(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        out = deepcopy(data)
    else:
        out = {}
        if isinstance(data, list):
            out["discarded_labels"] = data
    out.setdefault("schema_version", DATA_CONTRACT_VERSION)
    out.setdefault("workflow_version", WORKFLOW_VERSION)
    out.setdefault("discarded_labels", [])
    return out


def add_blacklist_entry(data: dict[str, Any], row: dict[str, Any]) -> bool:
    label = str(row.get("label") or "").strip()
    existing = {
        normalize_label(str(item.get("label") if isinstance(item, dict) else item))
        for item in data.get("discarded_labels", [])
    }
    if normalize_label(label) in existing:
        return False
    data["discarded_labels"].append(
        {
            "label": label,
            "source_dimension": row.get("source_dimension") or "",
            "reason": row.get("decision_note") or "rejected_by_user",
            "discarded_at": now_iso(),
        }
    )
    return True


def merge_candidate(taxonomy: dict[str, Any], row: dict[str, Any]) -> tuple[bool, str]:
    target = str(row.get("merge_target") or "").strip()
    label = str(row.get("label") or "").strip()
    if not target:
        return False, "missing_merge_target"
    target_dimension, target_label = split_target(target)
    index = taxonomy_index(taxonomy)
    key = f"{target_dimension}:{normalize_label(target_label)}" if target_dimension else normalize_label(target_label)
    found = index.get(key)
    if not found:
        return False, "target_not_found"
    _, entry = found
    entry["aliases"] = ordered_unique([*clean_list(entry.get("aliases")), label])
    entry["keywords"] = ordered_unique([*clean_list(entry.get("keywords")), label, *clean_list(row.get("keywords"))])
    merged = entry.get("merged_candidates")
    if not isinstance(merged, list):
        merged = []
    if normalize_label(label) not in {normalize_label(str(item.get("label") if isinstance(item, dict) else item)) for item in merged}:
        merged.append(
            {
                "label": label,
                "source_dimension": row.get("source_dimension") or "",
                "merged_at": now_iso(),
                "decision_note": row.get("decision_note") or "",
            }
        )
    entry["merged_candidates"] = merged
    return True, str(entry.get("label") or target_label)


def apply_rows(rows: list[dict[str, Any]], *, should_apply: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_taxonomy = read_json(TAXONOMY_PATH, {})
    taxonomy = ensure_taxonomy(original_taxonomy)
    blacklist = blacklist_data(read_json(BLACKLIST_PATH, {}))

    actions: list[dict[str, Any]] = []
    counts = {
        "accepted": 0,
        "pending": 0,
        "merged": 0,
        "rejected": 0,
        "skipped": 0,
        "invalid": 0,
    }

    for raw in rows:
        row = dict(raw)
        operation = str(row.get("operation") or "p").strip().lower()
        if operation not in VALID_OPERATIONS:
            counts["invalid"] += 1
            actions.append({"operation": operation, "label": row.get("label"), "status": "invalid_operation"})
            continue
        if operation in {"", "p"}:
            counts["pending"] += 1
            actions.append({"operation": "p", "label": row.get("label"), "status": "pending"})
            continue

        dimension = str(row.get("dimension_choice") or row.get("source_dimension") or "").strip()
        if dimension not in DIMENSIONS and operation in {"a"}:
            counts["invalid"] += 1
            actions.append({"operation": operation, "label": row.get("label"), "status": "invalid_dimension"})
            continue

        label = str(row.get("label") or "").strip()
        if operation == "a":
            if label_exists(taxonomy, dimension, label):
                counts["skipped"] += 1
                actions.append({"operation": "a", "label": label, "status": "already_exists", "dimension": dimension})
                continue
            entry = build_entry(row, taxonomy)
            taxonomy["dimensions"][dimension].append(entry)
            counts["accepted"] += 1
            actions.append({"operation": "a", "label": label, "status": "accepted", "dimension": dimension, "entry": entry})
        elif operation == "m":
            ok, detail = merge_candidate(taxonomy, row)
            if ok:
                counts["merged"] += 1
                actions.append({"operation": "m", "label": label, "status": "merged", "target": detail})
            else:
                counts["skipped"] += 1
                actions.append({"operation": "m", "label": label, "status": detail, "target": row.get("merge_target")})
        elif operation == "r":
            add_blacklist_entry(blacklist, row)
            counts["rejected"] += 1
            actions.append({"operation": "r", "label": label, "status": "rejected"})

    changed_taxonomy = taxonomy != ensure_taxonomy(original_taxonomy)
    changed_blacklist = blacklist != blacklist_data(read_json(BLACKLIST_PATH, {}))
    if should_apply:
        backup_dir = CONFIG.logs_dir / "backups"
        backup_file(TAXONOMY_PATH, backup_dir, root=CONFIG.root, reason="v0.3 taxonomy decisions")
        backup_file(BLACKLIST_PATH, backup_dir, root=CONFIG.root, reason="v0.3 taxonomy decisions")
        if changed_taxonomy:
            atomic_write_json(TAXONOMY_PATH, taxonomy)
        if changed_blacklist:
            atomic_write_json(BLACKLIST_PATH, blacklist)

    summary = {
        "schema_version": DATA_CONTRACT_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "generated_at": now_iso(),
        "mode": "apply" if should_apply else "preview",
        "taxonomy_path": str(TAXONOMY_PATH),
        "blacklist_path": str(BLACKLIST_PATH),
        "changed_taxonomy": changed_taxonomy,
        "changed_blacklist": changed_blacklist,
        "counts": counts,
        "actions": actions,
        "applied": should_apply,
    }
    return summary, taxonomy, blacklist


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        f"# MindCite v0.3 Tag Taxonomy Decision {'Apply' if summary['applied'] else 'Preview'} Summary",
        "",
        f"- mode: `{summary['mode']}`",
        f"- accepted: `{counts['accepted']}`",
        f"- merged: `{counts['merged']}`",
        f"- rejected: `{counts['rejected']}`",
        f"- pending: `{counts['pending']}`",
        f"- skipped: `{counts['skipped']}`",
        f"- invalid: `{counts['invalid']}`",
        f"- changed_taxonomy: `{summary['changed_taxonomy']}`",
        f"- changed_blacklist: `{summary['changed_blacklist']}`",
        "",
        "| operation | label | status | target_or_dimension |",
        "| --- | --- | --- | --- |",
    ]
    for action in summary.get("actions") or []:
        target = action.get("target") or action.get("dimension") or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(action.get("operation")),
                    md_cell(action.get("label")),
                    md_cell(action.get("status")),
                    md_cell(target),
                ]
            )
            + " |"
        )
    lines.append("")
    if not summary["applied"]:
        lines.append("这是预览结果，没有修改 taxonomy 或黑名单。确认后再运行 `--apply`。")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or apply v0.3 tag taxonomy decisions.")
    parser.add_argument("--decisions-json", type=Path, default=PRIORITY_JSON_PATH, help="Priority decision JSON.")
    parser.add_argument("--decisions-md", type=Path, default=PRIORITY_MD_PATH, help="Editable markdown decision table.")
    parser.add_argument("--use-markdown-operations", action="store_true", help="Overlay edited markdown operations onto JSON rows.")
    parser.add_argument("--apply", action="store_true", help="Apply accepted/merged/rejected decisions to taxonomy and blacklist.")
    args = parser.parse_args()

    data = read_json(args.decisions_json, {"rows": []})
    rows = list(data.get("rows") or [])
    if args.use_markdown_operations:
        rows = overlay_markdown_rows(rows, args.decisions_md)
    summary, _, _ = apply_rows(rows, should_apply=args.apply)

    atomic_write_json(PREVIEW_JSON_PATH, summary)
    atomic_write_text(PREVIEW_MD_PATH, render_summary(summary))
    if args.apply:
        atomic_write_json(APPLY_JSON_PATH, summary)
        atomic_write_text(APPLY_MD_PATH, render_summary(summary))

    print(
        json.dumps(
            {
                "ok": True,
                "workflow_version": WORKFLOW_VERSION,
                "mode": summary["mode"],
                "counts": summary["counts"],
                "preview_json_path": str(PREVIEW_JSON_PATH),
                "preview_markdown_path": str(PREVIEW_MD_PATH),
                "apply_json_path": str(APPLY_JSON_PATH) if args.apply else "",
                "apply_markdown_path": str(APPLY_MD_PATH) if args.apply else "",
                "applied": args.apply,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
