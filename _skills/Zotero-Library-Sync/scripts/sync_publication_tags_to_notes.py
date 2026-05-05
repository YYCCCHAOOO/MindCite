from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import configured_existing_paths, load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
NOTES_DIR = CONFIG.notes_papers_dir
DB_PATHS = configured_existing_paths(CONFIG.zotero_db_path, CONFIG.zotero_snapshot_path)
PREVIEW_PATH = CONFIG.indexes_dir / "publication_tag_sync_preview.jsonl"
SUMMARY_PATH = CONFIG.indexes_dir / "publication_tag_sync_summary.md"

PUBLICATION_FIELDS = [
    "publication_title",
    "journal_abbreviation",
    "publication_tags",
    "journal_rank_tags",
    "jcr_quartile",
    "cas_partition",
    "cas_partition_basic",
    "impact_factor",
    "impact_factor_5y",
    "elite_journal_tags",
    "publication_sync_status",
    "publication_sync_source",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def choose_db() -> Path:
    for path in DB_PATHS:
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
            conn.execute("select 1")
            conn.close()
            return path
        except sqlite3.Error:
            continue
    raise FileNotFoundError("No readable Zotero database found. Set ZOTERO_DB_PATH in .env.")


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def parse_extra_key_values(extra: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in (extra or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_publication_extra(extra: str) -> dict[str, Any]:
    fields = parse_extra_key_values(extra)
    jcr = fields.get("JCR分区")
    cas_upgrade = fields.get("中科院分区升级版")
    cas_basic = fields.get("中科院分区基础版")
    impact_factor = parse_float(fields.get("影响因子"))
    impact_factor_5y = parse_float(fields.get("5年影响因子"))
    elite_tags: list[str] = []
    publication_tags: list[str] = []
    journal_rank_tags: list[str] = []

    if jcr:
        tag = f"JCR {jcr}"
        publication_tags.append(tag)
        journal_rank_tags.append(tag)
    if cas_upgrade:
        tag = f"中科院升级版 {cas_upgrade}"
        publication_tags.append(tag)
        journal_rank_tags.append(tag)
    if cas_basic:
        tag = f"中科院基础版 {cas_basic}"
        publication_tags.append(tag)
        journal_rank_tags.append(tag)
    if impact_factor is not None:
        publication_tags.append(f"IF {impact_factor:g}")
    if impact_factor_5y is not None:
        publication_tags.append(f"5Y IF {impact_factor_5y:g}")

    for key in ["FT50", "UTD24", "EI", "SSCI", "SCI", "CSSCI", "北大核心", "南农高质量"]:
        value = fields.get(key)
        if not value:
            continue
        if key == "EI" and value not in {"是", "YES", "Yes", "yes", "EI"}:
            continue
        tag = key if key != "南农高质量" else f"南农高质量 {value}"
        elite_tags.append(tag)
        publication_tags.append(tag)
        journal_rank_tags.append(tag)

    status = "synced" if publication_tags else "missing_publication_tag"
    return {
        "publication_tags": unique(publication_tags),
        "journal_rank_tags": unique(journal_rank_tags),
        "jcr_quartile": jcr or "",
        "cas_partition": cas_upgrade or "",
        "cas_partition_basic": cas_basic or "",
        "impact_factor": impact_factor,
        "impact_factor_5y": impact_factor_5y,
        "elite_journal_tags": unique(elite_tags),
        "publication_sync_status": status,
        "publication_sync_source": "zotero_extra",
    }


def load_publication_meta(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT
            i.key,
            MAX(CASE WHEN f.fieldName = 'publicationTitle' THEN v.value END) AS publication_title,
            MAX(CASE WHEN f.fieldName = 'journalAbbreviation' THEN v.value END) AS journal_abbreviation,
            MAX(CASE WHEN f.fieldName = 'extra' THEN v.value END) AS extra
        FROM items i
        LEFT JOIN itemData d ON d.itemID = i.itemID
        LEFT JOIN fieldsCombined f ON f.fieldID = d.fieldID
        LEFT JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
        GROUP BY i.key
        """
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for key, publication_title, journal_abbreviation, extra in rows:
        meta = parse_publication_extra(extra or "")
        meta["publication_title"] = publication_title or ""
        meta["journal_abbreviation"] = journal_abbreviation or ""
        out[key] = meta
    return out


def extract_item_key(path: Path) -> str | None:
    if "__" not in path.stem:
        return None
    return path.stem.rsplit("__", 1)[-1].strip() or None


def split_frontmatter(text: str) -> tuple[str, str, str] | None:
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    prefix, fm, body = parts
    if prefix.strip():
        return None
    return prefix, fm, body


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)


def yaml_number_or_empty(value: Any) -> str:
    if value is None or value == "":
        return '""'
    try:
        return str(float(value)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return yaml_scalar(value)


def yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "\n" + "\n".join(f"  - {yaml_scalar(value)}" for value in values)


def render_field(field: str, value: Any) -> str:
    if isinstance(value, list):
        return f"{field}: {yaml_list(value)}" if value else f"{field}: []"
    if field in {"impact_factor", "impact_factor_5y"}:
        return f"{field}: {yaml_number_or_empty(value)}"
    return f"{field}: {yaml_scalar(value)}"


def render_block(meta: dict[str, Any]) -> str:
    return "\n".join(render_field(field, meta.get(field)) for field in PUBLICATION_FIELDS)


def remove_existing_fields(fm: str) -> list[str]:
    lines = fm.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line and not line.startswith(" ") and ":" in line:
            key = line.split(":", 1)[0].strip()
            skipping = key in PUBLICATION_FIELDS
            if skipping:
                continue
        elif skipping and (line.startswith(" ") or not line.strip()):
            continue
        else:
            skipping = False
        if not skipping:
            out.append(line)
    return out


def insert_publication_block(fm: str, meta: dict[str, Any]) -> str:
    lines = remove_existing_fields(fm)
    block = render_block(meta).splitlines()
    insert_at = None
    for idx, line in enumerate(lines):
        if line.startswith("year:"):
            insert_at = idx + 1
            break
    if insert_at is None:
        for idx, line in enumerate(lines):
            if line.startswith("zotero_key:"):
                insert_at = idx
                break
    if insert_at is None:
        insert_at = len(lines)
    new_lines = [*lines[:insert_at], *block, *lines[insert_at:]]
    return "\n".join(new_lines).strip("\n")


def build_rows(meta_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        item_key = extract_item_key(path)
        if not item_key:
            continue
        meta = meta_by_key.get(item_key)
        if not meta:
            rows.append(
                {
                    "item_key": item_key,
                    "note_path": str(path),
                    "status": "missing_in_zotero",
                    "will_modify": False,
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        parts = split_frontmatter(text)
        if not parts:
            rows.append(
                {
                    "item_key": item_key,
                    "note_path": str(path),
                    "status": "no_frontmatter",
                    "will_modify": False,
                }
            )
            continue
        prefix, fm, body = parts
        new_fm = insert_publication_block(fm, meta)
        new_text = f"{prefix}---\n{new_fm}\n---{body}"
        rows.append(
            {
                "item_key": item_key,
                "note_path": str(path),
                "status": meta["publication_sync_status"],
                "publication_title": meta.get("publication_title") or "",
                "publication_tags": meta.get("publication_tags") or [],
                "journal_rank_tags": meta.get("journal_rank_tags") or [],
                "jcr_quartile": meta.get("jcr_quartile") or "",
                "cas_partition": meta.get("cas_partition") or "",
                "impact_factor": meta.get("impact_factor"),
                "elite_journal_tags": meta.get("elite_journal_tags") or [],
                "will_modify": new_text != text,
                "new_text": new_text if new_text != text else None,
            }
        )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for row in rows:
        copy = dict(row)
        copy.pop("new_text", None)
        serializable.append(copy)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in serializable) + ("\n" if serializable else ""),
        encoding="utf-8",
    )


def write_summary(path: Path, rows: list[dict[str, Any]], apply: bool, backup_dir: Path | None) -> None:
    tagged = [row for row in rows if row.get("publication_tags")]
    tag_counter: Counter[str] = Counter(tag for row in rows for tag in (row.get("publication_tags") or []))
    jcr_counter: Counter[str] = Counter(row.get("jcr_quartile") for row in rows if row.get("jcr_quartile"))
    cas_counter: Counter[str] = Counter(row.get("cas_partition") for row in rows if row.get("cas_partition"))
    lines = [
        "# Publication Tag Sync Summary",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Mode: `{'apply' if apply else 'dry-run'}`",
        f"- Notes scanned: `{len(rows)}`",
        f"- Notes with publication tags: `{len(tagged)}`",
        f"- Notes missing publication tags: `{sum(1 for row in rows if row.get('status') == 'missing_publication_tag')}`",
        f"- Rows that would modify notes: `{sum(1 for row in rows if row.get('will_modify'))}`",
        f"- Backup dir: `{backup_dir or ''}`",
        "",
        "## Publication Tag Counts",
        "",
    ]
    for tag, count in tag_counter.most_common(40):
        lines.append(f"- `{tag}`: `{count}`")

    lines.extend(["", "## JCR", ""])
    for tag, count in jcr_counter.most_common():
        lines.append(f"- `{tag}`: `{count}`")

    lines.extend(["", "## CAS Upgrade", ""])
    for tag, count in cas_counter.most_common(30):
        lines.append(f"- `{tag}`: `{count}`")

    lines.extend([
        "",
        "## Samples",
        "",
    ])
    for row in tagged[:12]:
        lines.append(
            f"- `{row['item_key']}` | `{row.get('publication_title', '')}` | "
            f"{row.get('publication_tags') or []}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_rows(rows: list[dict[str, Any]], backup_dir: Path) -> int:
    backup_dir.mkdir(parents=True, exist_ok=True)
    modified = 0
    for row in rows:
        new_text = row.get("new_text")
        if not new_text:
            row["will_modify"] = False
            continue
        path = Path(row["note_path"])
        backup_path = backup_dir / path.name
        shutil.copy2(path, backup_path)
        path.write_text(new_text, encoding="utf-8")
        row["backup_path"] = str(backup_path)
        modified += 1
    return modified


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Zotero publication ranking metadata into note frontmatter.")
    parser.add_argument("--apply", action="store_true", help="Actually update notes. Default is dry-run.")
    parser.add_argument("--preview-path", type=Path, default=PREVIEW_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()

    db_path = choose_db()
    conn = connect_ro(db_path)
    meta_by_key = load_publication_meta(conn)
    conn.close()
    rows = build_rows(meta_by_key)
    backup_dir = None
    modified = 0
    if args.apply:
        backup_dir = args.backup_dir or ROOT / "logs" / "publication_tag_sync_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        modified = apply_rows(rows, backup_dir)
    write_jsonl(args.preview_path, rows)
    write_summary(args.summary_path, rows, args.apply, backup_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "apply" if args.apply else "dry-run",
                "db_path": str(db_path),
                "preview_path": str(args.preview_path),
                "summary_path": str(args.summary_path),
                "notes": len(rows),
                "with_publication_tags": sum(1 for row in rows if row.get("publication_tags")),
                "missing_publication_tags": sum(1 for row in rows if row.get("status") == "missing_publication_tag"),
                "will_modify": sum(1 for row in rows if row.get("will_modify")),
                "modified": modified,
                "backup_dir": str(backup_dir or ""),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
