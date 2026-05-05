from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
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
ZOTERO_DB = CONFIG.zotero_db_path
DRYRUN_PATH = CONFIG.indexes_dir / "zotero_writeback_dryrun.jsonl"
TREE_PATH = CONFIG.indexes_dir / "zotero_collection_tree.json"
REPORT_PATH = CONFIG.indexes_dir / "zotero_sqlite_writeback_report.jsonl"
SUMMARY_PATH = CONFIG.indexes_dir / "zotero_sqlite_writeback_summary.md"
BACKUP_DIR = CONFIG.logs_dir / "zotero_sqlite_writeback_backups"


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


def flatten_collection_tree() -> dict[str, dict[str, Any]]:
    if not TREE_PATH.exists():
        return {}
    data = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    nodes = data if isinstance(data, list) else data.get("children") or data.get("collections") or []
    by_path: dict[str, dict[str, Any]] = {}

    def walk(items: list[dict[str, Any]]) -> None:
        for node in items:
            path = str(node.get("collection_path") or "").strip()
            key = str(node.get("collection_key") or "").strip()
            if path and key:
                by_path[path] = node
            walk(node.get("children") or [])

    walk(nodes)
    return by_path


def select_rows(rows: list[dict[str, Any]], item_keys: set[str], limit: int | None) -> list[dict[str, Any]]:
    selected = [row for row in rows if not item_keys or str(row.get("item_key")) in item_keys]
    if limit is not None:
        return selected[:limit]
    return selected


def backup_db() -> Path:
    if ZOTERO_DB is None or not ZOTERO_DB.exists():
        raise FileNotFoundError("No Zotero database configured. Set ZOTERO_DB_PATH in .env before using --apply.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"zotero_db.before_collection_writeback_{stamp}.bak"
    shutil.copy2(ZOTERO_DB, backup_path)
    return backup_path


def read_item_collections(cur: sqlite3.Cursor, item_id: int) -> list[dict[str, Any]]:
    rows = cur.execute(
        """
        SELECT c.collectionID, c.key, c.collectionName, ci.orderIndex
        FROM collectionItems ci
        JOIN collections c ON c.collectionID = ci.collectionID
        WHERE ci.itemID = ?
        ORDER BY ci.collectionID
        """,
        (item_id,),
    ).fetchall()
    return [
        {"collectionID": row[0], "collection_key": row[1], "collection_name": row[2], "orderIndex": row[3]}
        for row in rows
    ]


def preview_or_apply(rows: list[dict[str, Any]], collection_by_path: dict[str, dict[str, Any]], apply: bool) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if ZOTERO_DB is None or not ZOTERO_DB.exists():
        raise FileNotFoundError("No Zotero database configured. Set ZOTERO_DB_PATH in .env.")
    con = sqlite3.connect(str(ZOTERO_DB), timeout=10)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        cur = con.cursor()
        for row in rows:
            item_key = str(row.get("item_key") or "").strip()
            add_paths = [str(path).strip() for path in row.get("add_collection_paths") or [] if str(path).strip()]
            existing_paths = [path for path in add_paths if path in collection_by_path]
            missing_paths = [path for path in add_paths if path not in collection_by_path]
            report: dict[str, Any] = {
                "item_key": item_key,
                "title": row.get("title"),
                "apply": apply,
                "attempted_add_collection_paths": existing_paths,
                "skipped_missing_collection_paths": missing_paths,
                "will_remove_collections": False,
                "generated_at": now_iso(),
            }
            item = cur.execute("SELECT itemID, libraryID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                report["status"] = "skipped_missing_item"
                reports.append(report)
                continue
            item_id, item_library_id = int(item[0]), int(item[1])
            report["before"] = read_item_collections(cur, item_id)
            inserts: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for path in existing_paths:
                collection_key = collection_by_path[path]["collection_key"]
                collection = cur.execute(
                    "SELECT collectionID, libraryID, collectionName FROM collections WHERE key = ?",
                    (collection_key,),
                ).fetchone()
                if not collection:
                    skipped.append({"path": path, "reason": "collection_not_found"})
                    continue
                collection_id, collection_library_id, collection_name = int(collection[0]), int(collection[1]), str(collection[2])
                if collection_library_id != item_library_id:
                    skipped.append({"path": path, "reason": "library_mismatch"})
                    continue
                exists = cur.execute(
                    "SELECT 1 FROM collectionItems WHERE collectionID = ? AND itemID = ?",
                    (collection_id, item_id),
                ).fetchone()
                if exists:
                    skipped.append({"path": path, "reason": "already_present"})
                    continue
                max_order = cur.execute(
                    "SELECT COALESCE(MAX(orderIndex), 0) FROM collectionItems WHERE collectionID = ?",
                    (collection_id,),
                ).fetchone()[0]
                inserts.append(
                    {
                        "path": path,
                        "collectionID": collection_id,
                        "collection_key": collection_key,
                        "collection_name": collection_name,
                        "orderIndex": int(max_order) + 1,
                    }
                )
            if apply and inserts:
                with con:
                    for insert in inserts:
                        cur.execute(
                            "INSERT INTO collectionItems(collectionID, itemID, orderIndex) VALUES (?, ?, ?)",
                            (insert["collectionID"], item_id, insert["orderIndex"]),
                        )
            report["inserted_collection_paths"] = [insert["path"] for insert in inserts]
            report["skipped_existing_collection_paths"] = [item["path"] for item in skipped if item["reason"] == "already_present"]
            report["skipped"] = skipped
            report["after"] = read_item_collections(cur, item_id) if apply else report["before"]
            if inserts:
                report["status"] = "updated" if apply else "preview"
            else:
                report["status"] = "already_present_or_no_existing_targets"
            reports.append(report)
    finally:
        con.close()
    return reports


def write_summary(reports: list[dict[str, Any]], apply: bool, backup_path: Path | None) -> None:
    lines = [
        "# Zotero SQLite Writeback Summary",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- apply: `{apply}`",
        f"- backup_path: `{backup_path or ''}`",
        f"- rows: `{len(reports)}`",
        f"- updated: `{sum(1 for row in reports if row.get('status') == 'updated')}`",
        f"- preview: `{sum(1 for row in reports if row.get('status') == 'preview')}`",
        f"- will_remove_collections: `false`",
        "",
    ]
    for row in reports:
        lines.append(f"- `{row.get('status')}` | `{row.get('item_key')}` | {row.get('title') or ''}")
        for path in row.get("inserted_collection_paths") or []:
            lines.append(f"  - add: `{path}`")
        for path in row.get("skipped_missing_collection_paths") or []:
            lines.append(f"  - skipped missing: `{path}`")
    SUMMARY_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Zotero collection writeback directly to zotero.sqlite.")
    parser.add_argument("--apply", action="store_true", help="Actually insert collection memberships into zotero.sqlite.")
    parser.add_argument("--item-keys", nargs="*", help="Limit to specific Zotero item keys.")
    parser.add_argument("--limit", type=int, help="Limit number of dry-run rows.")
    args = parser.parse_args()

    rows = select_rows(read_jsonl(DRYRUN_PATH), set(args.item_keys or []), args.limit)
    backup_path = backup_db() if args.apply and rows else None
    reports = preview_or_apply(rows, flatten_collection_tree(), args.apply)
    write_jsonl(REPORT_PATH, reports)
    write_summary(reports, args.apply, backup_path)
    print(
        json.dumps(
            {
                "ok": True,
                "apply": args.apply,
                "rows": len(reports),
                "updated": sum(1 for row in reports if row.get("status") == "updated"),
                "preview": sum(1 for row in reports if row.get("status") == "preview"),
                "backup_path": str(backup_path) if backup_path else "",
                "report_path": str(REPORT_PATH),
                "summary_path": str(SUMMARY_PATH),
                "will_remove_collections": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
