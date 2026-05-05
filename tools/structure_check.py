from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = [
    "config/mindcite.example.json",
    ".env.example",
    "README.md",
    "AGENTS.md",
    "SECURITY.md",
    "docs/architecture.md",
    "docs/codex-setup.md",
    "docs/troubleshooting.md",
    "docs/extension-policy.md",
    "_skills/common/mindcite_config.py",
    "_skills/common/safe_io.py",
    "_skills/Zotero-Reading-System/scripts/update_zotero_index.py",
    "_skills/Zotero-Reading-System/scripts/zotero_ai_reading_pipeline.py",
    "_skills/Notes-QA-System/SKILL.md",
    "_skills/Zotero-Library-Sync/scripts/vault_health_check.py",
    "schemas/zotero_library_index.schema.json",
    "schemas/reading_status.schema.json",
    "schemas/note_frontmatter.schema.json",
    "schemas/classification_taxonomy.schema.json",
    "schemas/classification_review_queue.schema.json",
    "tools/validate_data_contracts.py",
    "tools/migrate.py",
    "tools/smoke_test.py",
    "migrations/0001_add_schema_version.py",
    "examples/demo-vault/expected/smoke_expected.json",
    "examples/demo-vault/indexes/zotero_library_index.jsonl",
    "examples/demo-vault/notes/zotero_reading/_papers/Demonstration Paper on Global Risk Spillovers__DEMO2026A.md",
]


def main() -> int:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    print(json.dumps({"ok": not missing, "missing": missing}, ensure_ascii=False, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
