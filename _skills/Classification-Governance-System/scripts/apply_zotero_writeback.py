from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
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
DRYRUN_PATH = CONFIG.indexes_dir / "zotero_writeback_dryrun.jsonl"
TREE_PATH = CONFIG.indexes_dir / "zotero_collection_tree.json"
REPORT_PATH = CONFIG.indexes_dir / "zotero_writeback_apply_report.jsonl"
SUMMARY_PATH = CONFIG.indexes_dir / "zotero_writeback_apply_summary.md"
LOCAL_API_BASE = "http://127.0.0.1:23119/api/users/0"


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


def api_request(path: str, method: str = "GET", body: Any | None = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    url = f"{LOCAL_API_BASE}{path}"
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Zotero-API-Version", "3")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        if not raw:
            return response.status, None
        return response.status, json.loads(raw.decode("utf-8"))


def get_item(item_key: str) -> dict[str, Any]:
    _, item = api_request(f"/items/{item_key}")
    if not isinstance(item, dict):
        raise RuntimeError(f"Unexpected Zotero item response for {item_key}")
    return item


def put_item(item: dict[str, Any]) -> int:
    data = item.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Zotero item has no data payload")
    version = item.get("version") or data.get("version")
    headers = {}
    if version is not None:
        headers["If-Unmodified-Since-Version"] = str(version)
    status, _ = api_request(f"/items/{data['key']}", method="PUT", body=data, headers=headers)
    return status


def select_rows(rows: list[dict[str, Any]], item_keys: set[str], limit: int | None) -> list[dict[str, Any]]:
    selected = [row for row in rows if not item_keys or str(row.get("item_key")) in item_keys]
    if limit is not None:
        return selected[:limit]
    return selected


def apply_rows(rows: list[dict[str, Any]], collection_by_path: dict[str, dict[str, Any]], apply: bool) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for row in rows:
        item_key = str(row.get("item_key") or "").strip()
        add_paths = [str(path).strip() for path in row.get("add_collection_paths") or [] if str(path).strip()]
        existing_paths = [path for path in add_paths if path in collection_by_path]
        missing_paths = [path for path in add_paths if path not in collection_by_path]
        target_keys = [collection_by_path[path]["collection_key"] for path in existing_paths]
        report: dict[str, Any] = {
            "item_key": item_key,
            "title": row.get("title"),
            "apply": apply,
            "attempted_add_collection_paths": existing_paths,
            "skipped_missing_collection_paths": missing_paths,
            "will_remove_collections": False,
            "generated_at": now_iso(),
        }
        if not item_key:
            report["status"] = "skipped_no_item_key"
            reports.append(report)
            continue
        if not target_keys:
            report["status"] = "skipped_no_existing_target_collection"
            reports.append(report)
            continue
        try:
            item = get_item(item_key)
            data = item.get("data") or {}
            before = list(data.get("collections") or [])
            missing_target_keys = [key for key in target_keys if key not in before]
            already_present_keys = [key for key in target_keys if key in before]
            report["before_collection_keys"] = before
            report["already_present_collection_paths"] = [
                path for path in existing_paths if collection_by_path[path]["collection_key"] in already_present_keys
            ]
            report["added_collection_paths"] = [
                path for path in existing_paths if collection_by_path[path]["collection_key"] in missing_target_keys
            ]
            if not missing_target_keys:
                report["status"] = "already_present"
                report["after_collection_keys"] = before
                reports.append(report)
                continue
            if apply:
                data["collections"] = before + missing_target_keys
                status = put_item(item)
                verified = get_item(item_key)
                after = list((verified.get("data") or {}).get("collections") or [])
                report["http_status"] = status
                report["after_collection_keys"] = after
                report["status"] = "updated" if all(key in after for key in missing_target_keys) else "verify_failed"
            else:
                report["after_collection_keys"] = before + missing_target_keys
                report["status"] = "preview"
        except urllib.error.HTTPError as exc:
            report["status"] = "http_error"
            report["error"] = f"{exc.code} {exc.reason}"
        except Exception as exc:
            report["status"] = "error"
            report["error"] = repr(exc)
        reports.append(report)
    return reports


def write_summary(reports: list[dict[str, Any]], apply: bool) -> None:
    updated = sum(1 for row in reports if row.get("status") == "updated")
    preview = sum(1 for row in reports if row.get("status") == "preview")
    already = sum(1 for row in reports if row.get("status") == "already_present")
    errors = [row for row in reports if row.get("status") in {"http_error", "error", "verify_failed"}]
    missing = sum(len(row.get("skipped_missing_collection_paths") or []) for row in reports)
    lines = [
        "# Zotero Writeback Apply Summary",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- apply: `{apply}`",
        f"- rows: `{len(reports)}`",
        f"- updated: `{updated}`",
        f"- preview: `{preview}`",
        f"- already_present: `{already}`",
        f"- skipped_missing_collection_paths: `{missing}`",
        f"- errors: `{len(errors)}`",
        f"- will_remove_collections: `false`",
        "",
        "## Rows",
        "",
    ]
    for row in reports:
        lines.append(f"- `{row.get('status')}` | `{row.get('item_key')}` | {row.get('title') or ''}")
        for path in row.get("added_collection_paths") or []:
            lines.append(f"  - add: `{path}`")
        for path in row.get("skipped_missing_collection_paths") or []:
            lines.append(f"  - skipped missing: `{path}`")
        if row.get("error"):
            lines.append(f"  - error: `{row['error']}`")
    SUMMARY_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Zotero collection writeback from zotero_writeback_dryrun.jsonl.")
    parser.add_argument("--apply", action="store_true", help="Actually update Zotero via the local API.")
    parser.add_argument("--item-keys", nargs="*", help="Limit to specific Zotero item keys.")
    parser.add_argument("--limit", type=int, help="Limit number of dry-run rows.")
    args = parser.parse_args()

    rows = select_rows(read_jsonl(DRYRUN_PATH), set(args.item_keys or []), args.limit)
    reports = apply_rows(rows, flatten_collection_tree(), args.apply)
    write_jsonl(REPORT_PATH, reports)
    write_summary(reports, args.apply)
    print(
        json.dumps(
            {
                "ok": True,
                "apply": args.apply,
                "rows": len(reports),
                "updated": sum(1 for row in reports if row.get("status") == "updated"),
                "preview": sum(1 for row in reports if row.get("status") == "preview"),
                "already_present": sum(1 for row in reports if row.get("status") == "already_present"),
                "errors": sum(1 for row in reports if row.get("status") in {"http_error", "error", "verify_failed"}),
                "report_path": str(REPORT_PATH),
                "summary_path": str(SUMMARY_PATH),
                "will_remove_collections": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

