from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
QUEUE_PATH = CONFIG.indexes_dir / "classification_review_queue.jsonl"
TREE_PATH = CONFIG.indexes_dir / "zotero_collection_tree.json"
TAXONOMY_PATH = CONFIG.taxonomy_path
DRYRUN_PATH = CONFIG.indexes_dir / "zotero_writeback_dryrun.jsonl"

DIMENSIONS = {
    "theory": ("suggested_theory_tags", "3. 理论文献"),
    "method": ("suggested_method_tags", "2. 模型"),
    "topic": ("suggested_topic_tags", "4. 主题研究"),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
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


def load_collection_paths() -> set[str]:
    if not TREE_PATH.exists():
        return set()
    tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    if isinstance(tree, dict):
        nodes = tree.get("children") or tree.get("collections") or []
    else:
        nodes = tree
    paths: set[str] = set()

    def walk(items: list[dict[str, Any]]) -> None:
        for node in items:
            path = node.get("collection_path")
            if path:
                paths.add(path)
            walk(node.get("children") or [])

    walk(nodes)
    return paths


def load_taxonomy_targets() -> dict[str, dict[str, dict[str, str]]]:
    targets = {dimension: {} for dimension in DIMENSIONS}
    if not TAXONOMY_PATH.exists():
        return targets
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    dimensions = taxonomy.get("dimensions") or {}
    for dimension in DIMENSIONS:
        for entry in dimensions.get(dimension) or []:
            label = str(entry.get("label") or "").strip()
            base = str(entry.get("target_collection_base") or "").strip()
            exact_path = str(entry.get("target_collection_path") or "").strip()
            if label and (base or exact_path):
                targets[dimension][label] = {
                    "base": base,
                    "path": exact_path,
                }
    return targets


def normalize_label(text: str) -> str:
    text = re.sub(r"^\d+[\.\s_-]*", "", text.strip())
    return re.sub(r"[\s/_\-（）()\.]+", "", text).lower()


def resolve_existing_path(base: str, tag: str, existing_paths: set[str]) -> str:
    target_norm = normalize_label(tag)
    candidates = []
    for path in existing_paths:
        if not path.startswith(base + " / "):
            continue
        leaf = path.split(" / ")[-1]
        leaf_norm = normalize_label(leaf)
        if target_norm and (target_norm in leaf_norm or leaf_norm in target_norm):
            candidates.append(path)
    if candidates:
        return sorted(candidates, key=lambda value: (len(value.split(" / ")), len(value), value))[0]
    return f"{base} / {tag}"


def target_paths(
    row: dict[str, Any],
    existing_paths: set[str],
    taxonomy_targets: dict[str, dict[str, dict[str, str]]],
) -> list[str]:
    targets: list[str] = []
    for dimension, (field_name, default_base) in DIMENSIONS.items():
        for tag in row.get(field_name) or []:
            target = taxonomy_targets.get(dimension, {}).get(tag) or {}
            exact_path = target.get("path") or ""
            if exact_path:
                targets.append(exact_path)
                continue
            base = target.get("base") or default_base
            targets.append(resolve_existing_path(base, tag, existing_paths))

    out: list[str] = []
    for target in targets:
        if target not in out:
            out.append(target)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Zotero writeback dry-run plan from the review queue.")
    parser.add_argument("--approved-only", action="store_true", help="Only include rows already marked approved.")
    args = parser.parse_args()

    existing_collection_paths = load_collection_paths()
    taxonomy_targets = load_taxonomy_targets()
    rows = []
    for queue_row in read_jsonl(QUEUE_PATH):
        if args.approved_only and queue_row.get("review_status") != "approved":
            continue
        current = queue_row.get("current_zotero_collections") or []
        add_paths = [
            path
            for path in target_paths(queue_row, existing_collection_paths, taxonomy_targets)
            if path not in current
        ]
        if not add_paths:
            continue
        rows.append(
            {
                "item_key": queue_row.get("item_key"),
                "title": queue_row.get("title"),
                "add_collection_paths": add_paths,
                "existing_collection_paths": current,
                "target_collection_exists": {
                    path: path in existing_collection_paths for path in add_paths
                },
                "will_remove_collections": False,
                "requires_user_approval": True,
                "review_status": queue_row.get("review_status", "pending"),
                "dryrun_only": True,
            }
        )

    write_jsonl(DRYRUN_PATH, rows)
    print(
        json.dumps(
            {
                "ok": True,
                "dryrun_path": str(DRYRUN_PATH),
                "rows": len(rows),
                "will_remove_collections": False,
                "requires_user_approval": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
