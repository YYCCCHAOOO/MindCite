from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
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
INDEX_DIR = CONFIG.indexes_dir
LOG_DIR = CONFIG.logs_dir
NOTES_DIR = CONFIG.notes_dir
STATUS_PATH = CONFIG.status_path
ZOTERO_STORAGE = CONFIG.zotero_storage_path or ROOT / ".not_configured" / "zotero_storage"
DB_CANDIDATES = [
    (CONFIG.zotero_db_path, "configured"),
    (CONFIG.zotero_snapshot_path, "snapshot"),
]


EXCLUDED_TYPES = {"attachment", "note", "annotation"}


@dataclass
class CollectionNode:
    collection_id: int
    name: str
    key: str
    parent_id: int | None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_status_map() -> dict[str, dict[str, Any]]:
    if not STATUS_PATH.exists():
        return {}
    status_map: dict[str, dict[str, Any]] = {}
    for line in STATUS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        item_key = row.get("item_key")
        if item_key:
            status_map[item_key] = row
    return status_map


def choose_db() -> tuple[Path, str]:
    for path, label in DB_CANDIDATES:
        if path is None or not path.exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
            conn.execute("select 1")
            conn.close()
            return path, label
        except sqlite3.Error:
            continue
    raise FileNotFoundError("No readable Zotero database found. Set ZOTERO_DB_PATH in .env.")


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)


def slugify_segment(text: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in text.strip())
    return out.rstrip(" .") or "_"


def load_collections(conn: sqlite3.Connection) -> dict[int, CollectionNode]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT collectionID, collectionName, key, parentCollectionID
        FROM collections
        """
    ).fetchall()
    return {
        row[0]: CollectionNode(
            collection_id=row[0],
            name=row[1],
            key=row[2],
            parent_id=row[3],
        )
        for row in rows
    }


def build_collection_paths(collections: dict[int, CollectionNode]) -> tuple[dict[int, list[str]], dict[int, list[int]]]:
    name_cache: dict[int, list[str]] = {}
    id_cache: dict[int, list[int]] = {}

    def walk(cid: int) -> tuple[list[str], list[int]]:
        if cid in name_cache:
            return name_cache[cid], id_cache[cid]
        node = collections[cid]
        if node.parent_id and node.parent_id in collections:
            parent_names, parent_ids = walk(node.parent_id)
            names = [*parent_names, node.name]
            ids = [*parent_ids, cid]
        else:
            names = [node.name]
            ids = [cid]
        name_cache[cid] = names
        id_cache[cid] = ids
        return names, ids

    for cid in collections:
        walk(cid)
    return name_cache, id_cache


def load_collection_memberships(conn: sqlite3.Connection) -> dict[int, list[int]]:
    cur = conn.cursor()
    memberships: dict[int, list[int]] = defaultdict(list)
    for item_id, collection_id in cur.execute("SELECT itemID, collectionID FROM collectionItems"):
        memberships[item_id].append(collection_id)
    return memberships


def load_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT
            i.itemID,
            i.key,
            it.typeName,
            MAX(CASE WHEN f.fieldName = 'title' THEN v.value END) AS title,
            MAX(CASE WHEN f.fieldName = 'publicationTitle' THEN v.value END) AS publication_title,
            MAX(CASE WHEN f.fieldName = 'journalAbbreviation' THEN v.value END) AS journal_abbreviation,
            MAX(CASE WHEN f.fieldName = 'date' THEN v.value END) AS raw_date,
            MAX(CASE WHEN f.fieldName = 'DOI' THEN v.value END) AS doi,
            MAX(CASE WHEN f.fieldName = 'extra' THEN v.value END) AS extra
        FROM items i
        JOIN itemTypesCombined it ON it.itemTypeID = i.itemTypeID
        LEFT JOIN itemData d ON d.itemID = i.itemID
        LEFT JOIN fieldsCombined f ON f.fieldID = d.fieldID
        LEFT JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
        GROUP BY i.itemID, i.key, it.typeName
        """
    ).fetchall()
    items = []
    for item_id, key, type_name, title, publication_title, journal_abbreviation, raw_date, doi, extra in rows:
        if type_name in EXCLUDED_TYPES:
            continue
        publication_meta = parse_publication_extra(extra or "")
        items.append(
            {
                "item_id": item_id,
                "item_key": key,
                "item_type": type_name,
                "title": title or key,
                "publication_title": publication_title,
                "journal_abbreviation": journal_abbreviation,
                "raw_date": raw_date,
                "doi": doi,
                "extra": extra,
                **publication_meta,
            }
        )
    return items


def extract_year(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in raw_date).split()
    for part in digits:
        if len(part) == 4:
            return part
    return None


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
        return float(str(value).strip())
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

    return {
        "publication_extra": extra or None,
        "publication_extra_fields": fields,
        "publication_tags": unique(publication_tags),
        "journal_rank_tags": unique(journal_rank_tags),
        "jcr_quartile": jcr,
        "cas_partition": cas_upgrade,
        "cas_partition_basic": cas_basic,
        "impact_factor": impact_factor,
        "impact_factor_5y": impact_factor_5y,
        "elite_journal_tags": unique(elite_tags),
    }


def load_item_tags(conn: sqlite3.Connection) -> dict[int, dict[str, list[str]]]:
    cur = conn.cursor()
    grouped: dict[int, dict[str, list[str]]] = defaultdict(lambda: {"all": [], "manual": [], "automatic": []})
    rows = cur.execute(
        """
        SELECT it.itemID, t.name, it.type
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        ORDER BY it.itemID, lower(t.name)
        """
    ).fetchall()
    for item_id, tag_name, tag_type in rows:
        name = str(tag_name or "").strip()
        if not name:
            continue
        grouped[item_id]["all"].append(name)
        if tag_type == 1:
            grouped[item_id]["manual"].append(name)
        else:
            grouped[item_id]["automatic"].append(name)
    return {
        item_id: {kind: unique(values) for kind, values in kinds.items()}
        for item_id, kinds in grouped.items()
    }


def load_attachments(conn: sqlite3.Connection) -> dict[int, list[dict[str, Any]]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT ia.parentItemID, ia.itemID, ai.key, ia.linkMode, ia.contentType, ia.path
        FROM itemAttachments ia
        JOIN items ai ON ai.itemID = ia.itemID
        """
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for parent_item_id, attachment_item_id, attachment_key, link_mode, content_type, raw_path in rows:
        grouped[parent_item_id].append(
            {
                "attachment_item_id": attachment_item_id,
                "attachment_key": attachment_key,
                "link_mode": link_mode,
                "content_type": content_type,
                "raw_path": raw_path,
            }
        )
    return grouped


def resolve_pdf_paths(attachments: list[dict[str, Any]]) -> list[str]:
    pdfs: list[str] = []
    for att in attachments:
        if (att.get("content_type") or "").lower() != "application/pdf":
            continue
        raw_path = att.get("raw_path") or ""
        resolved: Path | None = None
        if raw_path.startswith("storage:"):
            filename = raw_path.split("storage:", 1)[1]
            resolved = ZOTERO_STORAGE / att["attachment_key"] / filename
        elif raw_path:
            cleaned = raw_path.replace("\\\\?\\", "")
            resolved = Path(cleaned)
        if resolved:
            pdfs.append(str(resolved))
    # Preserve order but dedupe.
    seen = set()
    unique = []
    for path in pdfs:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def resolve_attachment_keys(attachments: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for att in attachments:
        key = att.get("attachment_key")
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def resolve_fulltext_cache_paths(attachments: list[dict[str, Any]]) -> list[str]:
    caches: list[str] = []
    for att in attachments:
        key = att.get("attachment_key")
        if not key:
            continue
        cache_path = ZOTERO_STORAGE / key / ".zotero-ft-cache"
        caches.append(str(cache_path))
    seen: set[str] = set()
    unique: list[str] = []
    for path in caches:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def path_exists_loose(path_str: str) -> bool:
    try:
        return Path(path_str).exists()
    except PermissionError:
        return True
    except OSError:
        return False


def load_previous_index() -> dict[str, dict[str, Any]]:
    path = INDEX_DIR / "zotero_library_index.jsonl"
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("item_key"):
            out[row["item_key"]] = row
    return out


def scan_existing_notes() -> dict[str, list[Path]]:
    notes: dict[str, list[Path]] = defaultdict(list)
    if not NOTES_DIR.exists():
        return notes
    for path in NOTES_DIR.rglob("*.md"):
        stem = path.stem
        if "__" not in stem:
            continue
        item_key = stem.rsplit("__", 1)[-1]
        if item_key:
            notes[item_key].append(path)
    return notes


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_dirs() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.touch(exist_ok=True)


def choose_primary_collection_path(paths: list[list[str]]) -> list[str]:
    if not paths:
        return ["0. 待分类", "未分类条目"]
    noisy_terms = {
        "去重",
        "savedrecs",
        "scopus",
        "ebsco-metadata-51-100",
        "ebsco",
        "metadata",
        "unfiled",
    }
    theme_terms = ("主题研究", "理论文献", "模型", "顶刊每日阅读")

    def is_noisy_part(part: str) -> bool:
        lowered = part.lower().strip()
        return (
            lowered in noisy_terms
            or "metadata" in lowered
            or "savedrecs" in lowered
            or "scopus" in lowered
            or "ebsco" in lowered
        )

    def has_theme_signal(parts: list[str]) -> bool:
        return any(any(term in part for term in theme_terms) for part in parts)

    def infer_fallback_label() -> str:
        flattened = " / ".join(" / ".join(parts) for parts in paths).lower()
        if "ebsco" in flattened:
            return "EBSCO导入"
        if "scopus" in flattened:
            return "Scopus导入"
        if "savedrecs" in flattened:
            return "SavedRecs导入"
        if "metadata" in flattened:
            return "Metadata导入"
        if "unfiled" in flattened:
            return "未归档导入"
        return "来源待判定"

    def score(parts: list[str]) -> tuple[int, int, int, list[str]]:
        lowered = [part.lower() for part in parts]
        noisy_hits = sum(
            1
            for part in lowered
            if is_noisy_part(part)
        )
        has_theme = 0 if has_theme_signal(parts) else 1
        return (noisy_hits, has_theme, -len(parts), parts)

    best = sorted(paths, key=score)[0]
    all_paths_are_noisy = all((not has_theme_signal(parts)) and all(is_noisy_part(part) for part in parts) for parts in paths)
    if all_paths_are_noisy:
        return ["0. 待分类", infer_fallback_label()]
    return best


def select_active_note_path(note_paths: list[Path]) -> Path | None:
    existing = [path for path in note_paths if path.exists()]
    if not existing:
        return None
    stable_notes = [path for path in existing if "_papers" in path.parts]
    if stable_notes:
        return max(stable_notes, key=lambda p: p.stat().st_mtime)
    return max(existing, key=lambda p: p.stat().st_mtime)


def build_collection_tree(collections: dict[int, CollectionNode], path_names: dict[int, list[str]], memberships: dict[int, list[int]]) -> list[dict[str, Any]]:
    child_map: dict[int | None, list[int]] = defaultdict(list)
    direct_counts: dict[int, int] = defaultdict(int)
    for item_id, collection_ids in memberships.items():
        for cid in collection_ids:
            direct_counts[cid] += 1
    for cid, node in collections.items():
        child_map[node.parent_id].append(cid)

    def make_node(cid: int) -> dict[str, Any]:
        children = [make_node(child) for child in sorted(child_map.get(cid, []), key=lambda x: collections[x].name)]
        return {
            "collection_id": cid,
            "collection_key": collections[cid].key,
            "collection_name": collections[cid].name,
            "collection_path": " / ".join(path_names[cid]),
            "depth": len(path_names[cid]),
            "direct_item_count": direct_counts.get(cid, 0),
            "children": children,
        }

    roots = [cid for cid, node in collections.items() if node.parent_id not in collections]
    return [make_node(cid) for cid in sorted(roots, key=lambda x: collections[x].name)]


def main() -> None:
    db_path, db_kind = choose_db()
    ensure_dirs()
    status_map = read_status_map()
    previous_index = load_previous_index()
    existing_notes = scan_existing_notes()
    conn = connect_ro(db_path)
    collections = load_collections(conn)
    path_names, _ = build_collection_paths(collections)
    memberships = load_collection_memberships(conn)
    items = load_items(conn)
    attachments = load_attachments(conn)
    item_tags = load_item_tags(conn)

    rows: list[dict[str, Any]] = []
    note_moves = 0
    duplicate_note_cleanup = 0
    fallback_collection_count = 0
    for item in items:
        item_id = item["item_id"]
        collection_ids = sorted(set(memberships.get(item_id, [])))
        collection_name_lists = [path_names[cid] for cid in collection_ids if cid in path_names]
        collection_paths = [" / ".join(parts) for parts in collection_name_lists]
        primary_path = choose_primary_collection_path(collection_name_lists)
        used_fallback_collection = primary_path[:1] == ["0. 待分类"]
        if used_fallback_collection:
            fallback_collection_count += 1
        pdf_paths = resolve_pdf_paths(attachments.get(item_id, []))
        fulltext_cache_paths = resolve_fulltext_cache_paths(attachments.get(item_id, []))
        attachment_keys = resolve_attachment_keys(attachments.get(item_id, []))
        tags = item_tags.get(item_id, {"all": [], "manual": [], "automatic": []})
        active_note = select_active_note_path(existing_notes.get(item["item_key"], []))
        active_note_path = str(active_note) if active_note else None
        status_row = status_map.get(item["item_key"], {})
        rows.append(
            {
                "item_key": item["item_key"],
                "title": item["title"],
                "item_type": item["item_type"],
                "year": extract_year(item["raw_date"]),
                "doi": item["doi"],
                "zotero_item_id": item_id,
                "publication_title": item.get("publication_title"),
                "journal_abbreviation": item.get("journal_abbreviation"),
                "publication_tags": item.get("publication_tags") or [],
                "journal_rank_tags": item.get("journal_rank_tags") or [],
                "jcr_quartile": item.get("jcr_quartile"),
                "cas_partition": item.get("cas_partition"),
                "cas_partition_basic": item.get("cas_partition_basic"),
                "impact_factor": item.get("impact_factor"),
                "impact_factor_5y": item.get("impact_factor_5y"),
                "elite_journal_tags": item.get("elite_journal_tags") or [],
                "publication_extra_fields": item.get("publication_extra_fields") or {},
                "zotero_tags": tags.get("all") or [],
                "zotero_manual_tags": tags.get("manual") or [],
                "zotero_automatic_tags": tags.get("automatic") or [],
                "collection_names": [parts[-1] for parts in collection_name_lists],
                "collection_paths": collection_paths,
                "primary_collection_path": " / ".join(primary_path),
                "used_fallback_collection": used_fallback_collection,
                "collection_depth": max((len(parts) for parts in collection_name_lists), default=0),
                "attachment_keys": attachment_keys,
                "pdf_paths": pdf_paths,
                "primary_pdf_path": pdf_paths[0] if pdf_paths else None,
                "has_pdf": any(path_exists_loose(p) for p in pdf_paths),
                "fulltext_cache_paths": fulltext_cache_paths,
                "primary_fulltext_cache_path": fulltext_cache_paths[0] if fulltext_cache_paths else None,
                "has_fulltext_cache": any(path_exists_loose(p) for p in fulltext_cache_paths),
                "zotero_select_uri": f"zotero://select/library/items/{item['item_key']}",
                "zotero_open_pdf_uri": (
                    f"zotero://open-pdf/library/items/{attachment_keys[0]}" if attachment_keys else None
                ),
                "active_note_path": active_note_path,
                "reading_status": status_row.get("status"),
                "updated_at": now_iso(),
            }
        )
    conn.close()

    rows.sort(key=lambda row: ((row["title"] or "").lower(), row["item_key"]))
    current_keys = {row["item_key"] for row in rows}
    previous_keys = set(previous_index)
    added_count = len(current_keys - previous_keys)
    removed_count = len(previous_keys - current_keys)
    previous_collections = {
        key: tuple(previous_index[key].get("collection_paths") or [])
        for key in previous_keys & current_keys
    }
    previous_primary_targets = {
        key: previous_index[key].get("primary_collection_path")
        for key in previous_keys & current_keys
    }
    collection_changed_count = sum(
        1 for row in rows if tuple(row["collection_paths"]) != previous_collections.get(row["item_key"], tuple(row["collection_paths"]))
    )
    primary_target_changed_count = sum(
        1 for row in rows if row["primary_collection_path"] != previous_primary_targets.get(row["item_key"], row["primary_collection_path"])
    )
    missing_pdf_count = sum(1 for row in rows if not row["has_pdf"])
    publication_tag_count = sum(1 for row in rows if row.get("publication_tags"))

    tree = build_collection_tree(collections, path_names, memberships)
    generated_at = now_iso()
    meta = {
        "generated_at": generated_at,
        "source_db": str(db_path),
        "source_db_kind": db_kind,
        "total_items": len(rows),
        "total_collections": len(collections),
        "added_items": added_count,
        "removed_items": removed_count,
        "collection_changed_items": collection_changed_count,
        "primary_target_changed_items": primary_target_changed_count,
        "migrated_notes": note_moves,
        "duplicate_notes_removed": duplicate_note_cleanup,
        "fallback_collection_items": fallback_collection_count,
        "missing_pdf_items": missing_pdf_count,
        "publication_tagged_items": publication_tag_count,
    }
    summary = [
        "# Zotero Index Summary",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Source DB: `{db_path}` ({db_kind})",
        f"- Indexed items: `{len(rows)}`",
        f"- Collections: `{len(collections)}`",
        f"- Added since last index: `{added_count}`",
        f"- Removed since last index: `{removed_count}`",
        f"- Collection path changes: `{collection_changed_count}`",
        f"- Primary target changes: `{primary_target_changed_count}`",
        f"- Migrated notes: `{note_moves}`",
        f"- Duplicate notes removed: `{duplicate_note_cleanup}`",
        f"- Fallback-classified items: `{fallback_collection_count}`",
        f"- Items missing PDF: `{missing_pdf_count}`",
        f"- Items with publication tags: `{publication_tag_count}`",
    ]

    write_jsonl(INDEX_DIR / "zotero_library_index.jsonl", rows)
    write_json(INDEX_DIR / "zotero_collection_tree.json", tree)
    write_json(INDEX_DIR / "zotero_index_meta.json", meta)
    (INDEX_DIR / "zotero_index_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"update_index_{stamp}.md"
    log_lines = [
        "# Update Index Log",
        "",
        f"- Time: `{generated_at}`",
        f"- Source DB: `{db_path}` ({db_kind})",
        f"- Indexed items: `{len(rows)}`",
        f"- Added items: `{added_count}`",
        f"- Removed items: `{removed_count}`",
        f"- Collection changes: `{collection_changed_count}`",
        f"- Primary target changes: `{primary_target_changed_count}`",
        f"- Migrated notes: `{note_moves}`",
        f"- Duplicate notes removed: `{duplicate_note_cleanup}`",
        f"- Fallback-classified items: `{fallback_collection_count}`",
        f"- Missing PDF items: `{missing_pdf_count}`",
        f"- Publication-tagged items: `{publication_tag_count}`",
        "",
        "## Outputs",
        "",
        f"- `{INDEX_DIR / 'zotero_library_index.jsonl'}`",
        f"- `{INDEX_DIR / 'zotero_collection_tree.json'}`",
        f"- `{INDEX_DIR / 'zotero_index_meta.json'}`",
        f"- `{INDEX_DIR / 'zotero_index_summary.md'}`",
    ]
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "log_path": str(log_path), "meta": meta}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
