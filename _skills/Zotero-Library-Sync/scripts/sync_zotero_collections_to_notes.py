from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
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
BACKUP_DIR = CONFIG.logs_dir / "zotero_collection_note_sync_backups"
SUMMARY_PATH = CONFIG.indexes_dir / "zotero_collection_note_sync_summary.md"


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


def yaml_scalar(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def yaml_list(values: list[str]) -> str:
    if not values:
        return "  []"
    return "\n".join(f"  - {yaml_scalar(value)}" for value in values)


def field_block(field: str, value: Any) -> str:
    if isinstance(value, list):
        return f"{field}:\n{yaml_list([str(item) for item in value if str(item).strip()])}"
    return f"{field}: {yaml_scalar(value)}"


def replace_or_insert_field(frontmatter: str, field: str, value: Any, anchor_fields: list[str]) -> str:
    pattern = re.compile(rf"^{re.escape(field)}:.*?(?=^[A-Za-z0-9_\-]+:|\Z)", flags=re.M | re.S)
    block = field_block(field, value).rstrip() + "\n"
    if pattern.search(frontmatter):
        return pattern.sub(block, frontmatter, count=1)

    for anchor in anchor_fields:
        anchor_pattern = re.compile(rf"^{re.escape(anchor)}:.*?(?=^[A-Za-z0-9_\-]+:|\Z)", flags=re.M | re.S)
        match = anchor_pattern.search(frontmatter)
        if match:
            return frontmatter[: match.end()] + block + frontmatter[match.end() :]
    return frontmatter.rstrip() + "\n" + block


def split_note(text: str) -> tuple[str, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1].strip("\n") + "\n", parts[2]


def sync_row(row: dict[str, Any], apply: bool) -> dict[str, Any]:
    note_path = Path(str(row.get("active_note_path") or ""))
    result = {
        "item_key": row.get("item_key"),
        "note_path": str(note_path),
        "apply": apply,
        "status": "preview",
        "zotero_collections": row.get("collection_paths") or [],
        "primary_collection": row.get("primary_collection_path") or "",
    }
    if not note_path.exists():
        result["status"] = "missing_note"
        return result
    text = note_path.read_text(encoding="utf-8", errors="ignore")
    split = split_note(text)
    if not split:
        result["status"] = "missing_frontmatter"
        return result
    fm, body = split
    updated = replace_or_insert_field(
        fm,
        "zotero_collections",
        list(row.get("collection_paths") or []),
        ["zotero_open_pdf_uri", "zotero_select_uri", "zotero_key"],
    )
    updated = replace_or_insert_field(
        updated,
        "primary_collection",
        row.get("primary_collection_path") or "",
        ["zotero_collections"],
    )
    updated_text = "---\n" + updated.strip("\n") + "\n---" + body
    result["will_modify"] = updated_text != text
    if apply and result["will_modify"]:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{note_path.stem}.{stamp}.bak.md"
        shutil.copy2(note_path, backup_path)
        note_path.write_text(updated_text, encoding="utf-8", newline="\n")
        result["status"] = "updated"
        result["backup_path"] = str(backup_path)
    elif not result["will_modify"]:
        result["status"] = "already_synced"
    return result


def write_summary(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Zotero Collection Note Sync Summary",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- rows: `{len(results)}`",
        f"- updated: `{sum(1 for row in results if row.get('status') == 'updated')}`",
        f"- already_synced: `{sum(1 for row in results if row.get('status') == 'already_synced')}`",
        "",
    ]
    for row in results:
        lines.append(f"- `{row.get('status')}` | `{row.get('item_key')}` | `{row.get('note_path')}`")
    SUMMARY_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Zotero collection paths from the index into note frontmatter.")
    parser.add_argument("--apply", action="store_true", help="Actually update note frontmatter.")
    parser.add_argument("--item-keys", nargs="*", help="Limit to specific Zotero item keys.")
    args = parser.parse_args()

    wanted = set(args.item_keys or [])
    rows = [
        row
        for row in read_jsonl(INDEX_PATH)
        if row.get("active_note_path") and (not wanted or row.get("item_key") in wanted)
    ]
    results = [sync_row(row, args.apply) for row in rows]
    write_summary(results)
    print(
        json.dumps(
            {
                "ok": True,
                "apply": args.apply,
                "rows": len(results),
                "updated": sum(1 for row in results if row.get("status") == "updated"),
                "already_synced": sum(1 for row in results if row.get("status") == "already_synced"),
                "summary_path": str(SUMMARY_PATH),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
