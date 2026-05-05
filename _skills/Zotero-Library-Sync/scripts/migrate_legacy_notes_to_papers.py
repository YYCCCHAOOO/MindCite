from __future__ import annotations

import argparse
import json
import shutil
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
NOTES_DIR = CONFIG.notes_dir
PAPERS_DIR = CONFIG.notes_papers_dir
STATUS_PATH = CONFIG.status_path
PLAN_PATH = CONFIG.indexes_dir / "note_location_migration_plan.jsonl"
SUMMARY_PATH = CONFIG.indexes_dir / "note_location_migration_summary.md"


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
    if "__" not in path.stem:
        return None
    return path.stem.rsplit("__", 1)[-1].strip() or None


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def legacy_note_paths() -> list[Path]:
    paths: list[Path] = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        rel = path.relative_to(NOTES_DIR)
        if rel.parts and rel.parts[0] == "_papers":
            continue
        paths.append(path)
    return paths


def build_plan() -> list[dict[str, Any]]:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    destination_seen: dict[Path, Path] = {}
    for source_path in legacy_note_paths():
        item_key = extract_item_key(source_path)
        destination_path = PAPERS_DIR / source_path.name
        reasons: list[str] = []
        if not item_key:
            reasons.append("missing_item_key_in_filename")
        if not is_inside(source_path, NOTES_DIR):
            reasons.append("source_outside_notes_dir")
        if not is_inside(destination_path, PAPERS_DIR):
            reasons.append("destination_outside_papers_dir")
        if destination_path.exists() and destination_path.resolve() != source_path.resolve():
            reasons.append("destination_exists")
        if destination_path in destination_seen:
            reasons.append(f"destination_duplicate_with={destination_seen[destination_path]}")
        destination_seen[destination_path] = source_path
        rows.append(
            {
                "item_key": item_key,
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "status": "blocked" if reasons else "ready",
                "reasons": reasons,
                "will_move": False,
            }
        )
    return rows


def update_status_paths(moved_rows: list[dict[str, Any]]) -> int:
    moved_by_key = {
        row["item_key"]: row
        for row in moved_rows
        if row.get("item_key") and row.get("moved")
    }
    if not moved_by_key or not STATUS_PATH.exists():
        return 0
    rows = read_jsonl(STATUS_PATH)
    updated = 0
    for row in rows:
        item_key = row.get("item_key")
        moved = moved_by_key.get(item_key)
        if not moved:
            continue
        if row.get("note_path") == moved.get("source_path"):
            row["note_path"] = moved["destination_path"]
            row["updated_at"] = now_iso()
            row["reason"] = (row.get("reason") or "").rstrip() + " Note path migrated to _papers."
            updated += 1
    write_jsonl(STATUS_PATH, rows)
    return updated


def remove_empty_dirs() -> int:
    removed = 0
    candidates = sorted(
        [path for path in NOTES_DIR.rglob("*") if path.is_dir() and path != PAPERS_DIR],
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in candidates:
        if not is_inside(path, NOTES_DIR):
            continue
        try:
            path.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def apply_plan(rows: list[dict[str, Any]], backup_dir: Path, clean_empty_dirs: bool) -> tuple[list[dict[str, Any]], int, int]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    moved_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "ready":
            continue
        source_path = Path(row["source_path"])
        destination_path = Path(row["destination_path"])
        if not source_path.exists():
            row["status"] = "blocked"
            row.setdefault("reasons", []).append("source_missing_at_apply")
            continue
        if destination_path.exists():
            row["status"] = "blocked"
            row.setdefault("reasons", []).append("destination_exists_at_apply")
            continue
        backup_path = backup_dir / source_path.relative_to(NOTES_DIR)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, backup_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        row["will_move"] = True
        row["moved"] = True
        row["backup_path"] = str(backup_path)
        moved_rows.append(row)

    status_updates = update_status_paths(moved_rows)
    removed_dirs = remove_empty_dirs() if clean_empty_dirs else 0
    return rows, status_updates, removed_dirs


def write_summary(
    path: Path,
    rows: list[dict[str, Any]],
    apply: bool,
    backup_dir: Path | None,
    status_updates: int = 0,
    removed_dirs: int = 0,
) -> None:
    ready = [row for row in rows if row.get("status") == "ready"]
    blocked = [row for row in rows if row.get("status") == "blocked"]
    moved = [row for row in rows if row.get("moved")]
    lines = [
        "# Note Location Migration Summary",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Mode: `{'apply' if apply else 'dry-run'}`",
        f"- Source root: `{NOTES_DIR}`",
        f"- Destination: `{PAPERS_DIR}`",
        f"- Plan path: `{PLAN_PATH}`",
        f"- Legacy notes in plan: `{len(rows)}`",
        f"- Ready to move: `{len(ready)}`",
        f"- Blocked: `{len(blocked)}`",
        f"- Actually moved: `{len(moved)}`",
        f"- Status note_path updates: `{status_updates}`",
        f"- Empty dirs removed: `{removed_dirs}`",
        f"- Backup dir: `{backup_dir or ''}`",
        "",
    ]
    if blocked:
        lines.extend(["## Blocked Samples", ""])
        for row in blocked[:20]:
            lines.append(f"- `{row.get('item_key')}` | `{row.get('source_path')}` | {row.get('reasons')}")
    else:
        lines.append("- No blocked moves.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Move legacy Zotero reading notes into _papers with backups.")
    parser.add_argument("--apply", action="store_true", help="Actually move notes. Default is dry-run only.")
    parser.add_argument("--backup-dir", type=Path, help="Backup directory used only with --apply.")
    parser.add_argument("--keep-empty-dirs", action="store_true", help="Do not remove empty legacy folders after apply.")
    parser.add_argument("--plan-path", type=Path, default=PLAN_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args()

    rows = build_plan()
    backup_dir: Path | None = None
    status_updates = 0
    removed_dirs = 0
    if args.apply:
        backup_dir = args.backup_dir or ROOT / "logs" / "note_location_migration_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        rows, status_updates, removed_dirs = apply_plan(rows, backup_dir, clean_empty_dirs=not args.keep_empty_dirs)

    write_jsonl(args.plan_path, rows)
    write_summary(args.summary_path, rows, args.apply, backup_dir, status_updates, removed_dirs)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "apply" if args.apply else "dry-run",
                "plan_path": str(args.plan_path),
                "summary_path": str(args.summary_path),
                "legacy_notes": len(rows),
                "ready": sum(1 for row in rows if row.get("status") == "ready"),
                "blocked": sum(1 for row in rows if row.get("status") == "blocked"),
                "moved": sum(1 for row in rows if row.get("moved")),
                "status_updates": status_updates,
                "removed_empty_dirs": removed_dirs,
                "backup_dir": str(backup_dir or ""),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

