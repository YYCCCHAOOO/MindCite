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
from safe_io import DATA_CONTRACT_VERSION


SCHEMA_DIR = ROOT / "schemas"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append({"__parse_error__": f"line {line_no}: {exc}"})
            continue
        rows.append(row)
    return rows


def frontmatter_text(text: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = frontmatter_text(text)
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


def type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def validate_object(obj: dict[str, Any], schema: dict[str, Any], location: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if "__parse_error__" in obj:
        return [{"path": location, "type": "json_parse_error", "detail": str(obj["__parse_error__"])}]
    for key in schema.get("required", []):
        if key not in obj:
            findings.append({"path": location, "type": "missing_required_field", "detail": key})
    for key, rules in (schema.get("properties") or {}).items():
        if key not in obj:
            continue
        value = obj[key]
        if "const" in rules and value != rules["const"]:
            findings.append(
                {
                    "path": location,
                    "type": "schema_version_mismatch" if key == "schema_version" else "const_mismatch",
                    "detail": f"{key} expected {rules['const']!r}, got {value!r}",
                }
            )
        expected_types = rules.get("type")
        if expected_types:
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            if not any(type_matches(value, expected) for expected in expected_types):
                findings.append(
                    {
                        "path": location,
                        "type": "field_type_mismatch",
                        "detail": f"{key} expected {expected_types}, got {type(value).__name__}",
                    }
                )
        if "enum" in rules and value not in rules["enum"]:
            findings.append({"path": location, "type": "enum_mismatch", "detail": f"{key}={value!r}"})
    return findings


def validate_jsonl(path: Path, schema: dict[str, Any], label: str) -> list[dict[str, str]]:
    if not path.exists():
        return []
    findings: list[dict[str, str]] = []
    for idx, row in enumerate(read_jsonl(path), 1):
        findings.extend(validate_object(row, schema, f"{label}:{idx}"))
    return findings


def validate_taxonomy(path: Path, schema: dict[str, Any], label: str) -> list[dict[str, str]]:
    if not path.exists():
        return []
    findings = validate_object(load_json(path), schema, label)
    data = load_json(path)
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict):
        return findings
    for dimension in schema.get("x_required_dimensions", []):
        values = dimensions.get(dimension)
        if not isinstance(values, list):
            findings.append({"path": label, "type": "missing_dimension", "detail": dimension})
            continue
        for idx, entry in enumerate(values, 1):
            if not isinstance(entry, dict):
                findings.append({"path": f"{label}:{dimension}[{idx}]", "type": "invalid_dimension_entry", "detail": "not an object"})
                continue
            for key in schema.get("x_dimension_entry_required", []):
                if key not in entry:
                    findings.append({"path": f"{label}:{dimension}[{idx}]", "type": "missing_dimension_field", "detail": key})
    return findings


def validate_notes(notes_dir: Path, schema: dict[str, Any], label: str) -> list[dict[str, str]]:
    if not notes_dir.exists():
        return []
    findings: list[dict[str, str]] = []
    for path in sorted(notes_dir.rglob("*.md")):
        rel = path.relative_to(notes_dir).as_posix()
        findings.extend(validate_object(parse_frontmatter(path), schema, f"{label}:{rel}"))
    return findings


def validate_root(root: Path, label: str) -> list[dict[str, str]]:
    schemas = {
        "index": load_json(SCHEMA_DIR / "zotero_library_index.schema.json"),
        "status": load_json(SCHEMA_DIR / "reading_status.schema.json"),
        "note": load_json(SCHEMA_DIR / "note_frontmatter.schema.json"),
        "taxonomy": load_json(SCHEMA_DIR / "classification_taxonomy.schema.json"),
        "queue": load_json(SCHEMA_DIR / "classification_review_queue.schema.json"),
    }
    indexes = root / "indexes"
    logs = root / "logs"
    notes = root / "notes" / "zotero_reading" / "_papers"
    findings: list[dict[str, str]] = []
    findings.extend(validate_jsonl(indexes / "zotero_library_index.jsonl", schemas["index"], f"{label}/zotero_library_index.jsonl"))
    findings.extend(validate_jsonl(logs / "reading_status.jsonl", schemas["status"], f"{label}/reading_status.jsonl"))
    findings.extend(validate_taxonomy(indexes / "classification_taxonomy.json", schemas["taxonomy"], f"{label}/classification_taxonomy.json"))
    findings.extend(validate_jsonl(indexes / "classification_review_queue.jsonl", schemas["queue"], f"{label}/classification_review_queue.jsonl"))
    findings.extend(validate_notes(notes, schemas["note"], f"{label}/notes"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate MindCite data contracts.")
    parser.add_argument("--root", type=Path, help="Optional vault root to validate.")
    parser.add_argument("--demo-only", action="store_true", help="Only validate examples/demo-vault.")
    args = parser.parse_args()

    roots: list[tuple[str, Path]] = []
    if not args.demo_only:
        config_root = args.root.resolve() if args.root else load_config(Path(__file__)).root
        roots.append(("configured", config_root))
    roots.append(("demo", ROOT / "examples" / "demo-vault"))

    findings: list[dict[str, str]] = []
    for label, root in roots:
        findings.extend(validate_root(root, label))

    result = {
        "ok": not findings,
        "schema_version": DATA_CONTRACT_VERSION,
        "validated_roots": [{"label": label, "path": str(root)} for label, root in roots],
        "findings": findings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
