from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMMON_DIR = ROOT / "_skills" / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import load_config
from safe_io import DATA_CONTRACT_VERSION, atomic_write_json, atomic_write_jsonl, atomic_write_text, backup_file, now_iso


MIGRATION_ID = "0001_add_schema_version"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def add_schema_version(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if row.get("schema_version") == DATA_CONTRACT_VERSION:
        return row, False
    cleaned = {key: value for key, value in row.items() if key != "schema_version"}
    return {"schema_version": DATA_CONTRACT_VERSION, **cleaned}, True


def migrate_jsonl(path: Path, *, apply: bool, backup_dir: Path, root: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    changed = 0
    out: list[dict[str, Any]] = []
    for row in rows:
        new_row, did_change = add_schema_version(row)
        out.append(new_row)
        changed += int(did_change)
    if apply and changed:
        backup_file(path, backup_dir, root=root, reason=MIGRATION_ID)
        atomic_write_jsonl(path, out)
    return {"path": str(path), "exists": path.exists(), "rows": len(rows), "changed_rows": changed}


def migrate_json_object(path: Path, *, apply: bool, backup_dir: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = data.get("schema_version") != DATA_CONTRACT_VERSION
    if changed:
        data = {"schema_version": DATA_CONTRACT_VERSION, **{key: value for key, value in data.items() if key != "schema_version"}}
    if apply and changed:
        backup_file(path, backup_dir, root=root, reason=MIGRATION_ID)
        atomic_write_json(path, data)
    return {"path": str(path), "exists": True, "changed": changed}


def frontmatter_bounds(text: str) -> tuple[int, int] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return 0, end + 4


def migrate_note(path: Path, *, apply: bool, backup_dir: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    bounds = frontmatter_bounds(text)
    if bounds is None:
        return {"path": str(path), "changed": False, "reason": "missing_frontmatter"}
    start, end = bounds
    frontmatter = text[start:end]
    lines = frontmatter.splitlines()
    changed = False
    for idx, line in enumerate(lines):
        if line.startswith("schema_version:"):
            if line.strip() != f'schema_version: "{DATA_CONTRACT_VERSION}"':
                lines[idx] = f'schema_version: "{DATA_CONTRACT_VERSION}"'
                changed = True
            break
    else:
        lines.insert(1, f'schema_version: "{DATA_CONTRACT_VERSION}"')
        changed = True
    if apply and changed:
        backup_file(path, backup_dir, root=root, reason=MIGRATION_ID)
        atomic_write_text(path, "\n".join(lines) + text[end:])
    return {"path": str(path), "changed": changed}


def migrate_notes(notes_dir: Path, *, apply: bool, backup_dir: Path, root: Path) -> dict[str, Any]:
    if not notes_dir.exists():
        return {"path": str(notes_dir), "exists": False, "notes": 0, "changed_notes": 0}
    results = [migrate_note(path, apply=apply, backup_dir=backup_dir, root=root) for path in sorted(notes_dir.rglob("*.md"))]
    return {
        "path": str(notes_dir),
        "exists": True,
        "notes": len(results),
        "changed_notes": sum(1 for row in results if row.get("changed")),
        "skipped_notes": sum(1 for row in results if row.get("reason")),
    }


def write_migration_state(path: Path, report: dict[str, Any]) -> None:
    state = {"schema_version": DATA_CONTRACT_VERSION, "last_migration": MIGRATION_ID, "updated_at": now_iso(), "report": report}
    atomic_write_json(path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MindCite data migrations.")
    parser.add_argument("--apply", action="store_true", help="Actually write migrated files. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Preview migrations without writing files.")
    parser.add_argument("--root", type=Path, help="Optional vault root. Defaults to configured MindCite root.")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run cannot be used together.")

    config = load_config(Path(__file__))
    root = (args.root or config.root).resolve()
    indexes_dir = root / "indexes"
    logs_dir = root / "logs"
    notes_dir = root / "notes" / "zotero_reading" / "_papers"
    backup_dir = logs_dir / "migration_backups" / MIGRATION_ID

    report = {
        "ok": True,
        "migration_id": MIGRATION_ID,
        "schema_version": DATA_CONTRACT_VERSION,
        "mode": "apply" if args.apply else "dry-run",
        "root": str(root),
        "changes": [
            migrate_jsonl(indexes_dir / "zotero_library_index.jsonl", apply=args.apply, backup_dir=backup_dir, root=root),
            migrate_jsonl(logs_dir / "reading_status.jsonl", apply=args.apply, backup_dir=backup_dir, root=root),
            migrate_jsonl(indexes_dir / "classification_review_queue.jsonl", apply=args.apply, backup_dir=backup_dir, root=root),
            migrate_json_object(indexes_dir / "classification_taxonomy.json", apply=args.apply, backup_dir=backup_dir, root=root),
            migrate_notes(notes_dir, apply=args.apply, backup_dir=backup_dir, root=root),
        ],
    }
    if args.apply:
        logs_dir.mkdir(parents=True, exist_ok=True)
        write_migration_state(logs_dir / "migration_state.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
