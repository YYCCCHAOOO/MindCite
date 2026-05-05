from __future__ import annotations

import json
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
STATUS_PATH = CONFIG.status_path
NOTES_DIR = CONFIG.notes_dir
REPORT_PATH = CONFIG.indexes_dir / "vault_health_report.md"
ORPHAN_PATH = CONFIG.indexes_dir / "orphan_notes.jsonl"

REQUIRED_CLASSIFICATION_FIELDS = [
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


def extract_item_key(path: Path) -> str | None:
    stem = path.stem
    if "__" not in stem:
        return None
    key = stem.rsplit("__", 1)[-1].strip()
    return key or None


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
                parsed[key] = value.strip('"')
            else:
                parsed[key] = []
    return parsed


def scan_notes() -> list[dict[str, Any]]:
    if not NOTES_DIR.exists():
        return []
    notes: list[dict[str, Any]] = []
    for path in NOTES_DIR.rglob("*.md"):
        item_key = extract_item_key(path)
        fm = parse_frontmatter(path)
        rel_parts = path.relative_to(NOTES_DIR).parts
        notes.append(
            {
                "item_key": item_key,
                "note_path": str(path),
                "is_papers_note": len(rel_parts) > 1 and rel_parts[0] == "_papers",
                "frontmatter": fm,
                "missing_classification_fields": [
                    field for field in REQUIRED_CLASSIFICATION_FIELDS if field not in fm
                ],
            }
        )
    return notes


def main() -> None:
    index_rows = read_jsonl(INDEX_PATH)
    status_rows = read_jsonl(STATUS_PATH)
    latest_status = {row.get("item_key"): row for row in status_rows if row.get("item_key")}
    notes = scan_notes()

    index_keys = {row.get("item_key") for row in index_rows if row.get("item_key")}
    note_keys = {row.get("item_key") for row in notes if row.get("item_key")}
    status_counts = Counter(row.get("status") or "<blank>" for row in latest_status.values())

    orphan_rows = [
        {
            "item_key": note["item_key"],
            "note_path": note["note_path"],
            "reason": "note item_key not found in current zotero_library_index.jsonl",
            "last_seen_in_zotero_index": False,
        }
        for note in notes
        if note.get("item_key") and note.get("item_key") not in index_keys
    ]
    write_jsonl(ORPHAN_PATH, orphan_rows)

    notes_missing_fields = [note for note in notes if note["missing_classification_fields"]]
    done_without_note = [
        key
        for key, row in latest_status.items()
        if row.get("status") == "done" and key not in note_keys
    ]
    status_done_missing_path = [
        row
        for row in latest_status.values()
        if row.get("status") == "done" and row.get("note_path") and not Path(row["note_path"]).exists()
    ]

    report_lines = [
        "# Vault Health Report",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Indexed Zotero items: `{len(index_rows)}`",
        f"- Notes total: `{len(notes)}`",
        f"- Notes in `_papers`: `{sum(1 for note in notes if note['is_papers_note'])}`",
        f"- Notes in legacy classification folders: `{sum(1 for note in notes if not note['is_papers_note'])}`",
        f"- Notes with item_key: `{len(note_keys)}`",
        f"- Notes missing item_key in filename: `{sum(1 for note in notes if not note.get('item_key'))}`",
        "",
        "## Reading Status",
        "",
        f"- `done`: `{status_counts.get('done', 0)}`",
        f"- `needs_pdf`: `{status_counts.get('needs_pdf', 0)}`",
        f"- `needs_note`: `{status_counts.get('needs_note', 0)}`",
        f"- `skipped`: `{status_counts.get('skipped', 0)}`",
        "",
        "## Sync Checks",
        "",
        f"- Orphan notes: `{len(orphan_rows)}`",
        f"- Done status without any scanned note: `{len(done_without_note)}`",
        f"- Done status with missing note_path file: `{len(status_done_missing_path)}`",
        f"- Notes missing classification frontmatter fields: `{len(notes_missing_fields)}`",
        "",
        "## Samples",
        "",
    ]

    for note in notes_missing_fields[:10]:
        report_lines.append(
            f"- Missing fields `{', '.join(note['missing_classification_fields'])}` | `{note['item_key']}` | `{note['note_path']}`"
        )
    if not notes_missing_fields:
        report_lines.append("- No notes missing classification frontmatter fields.")

    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "report_path": str(REPORT_PATH),
                "orphan_notes_path": str(ORPHAN_PATH),
                "indexed_items": len(index_rows),
                "notes_total": len(notes),
                "papers_notes": sum(1 for note in notes if note["is_papers_note"]),
                "legacy_notes": sum(1 for note in notes if not note["is_papers_note"]),
                "orphan_notes": len(orphan_rows),
                "notes_missing_classification_fields": len(notes_missing_fields),
                "status_counts": dict(status_counts),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
