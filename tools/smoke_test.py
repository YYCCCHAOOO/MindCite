from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
DEMO_ROOT = ROOT / "examples" / "demo-vault"
DEMO_OUTPUTS = [
    DEMO_ROOT / "indexes" / "vault_health_report.md",
    DEMO_ROOT / "indexes" / "orphan_notes.jsonl",
    DEMO_ROOT / "indexes" / "classification_review_queue.jsonl",
]


def run_step(name: str, args: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        [PYTHON, *args],
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
    )
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def cleanup_demo_outputs() -> None:
    for path in DEMO_OUTPUTS:
        if path.exists():
            path.unlink()


def parse_last_json(stdout: str) -> dict[str, Any]:
    if not stdout:
        return {}
    lines = [line for line in stdout.splitlines() if line.strip()]
    for start in range(len(lines)):
        candidate = "\n".join(lines[start:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def check_demo_expectations(steps: list[dict[str, Any]]) -> dict[str, Any]:
    expected_path = DEMO_ROOT / "expected" / "smoke_expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    health = parse_last_json(next(row["stdout"] for row in steps if row["name"] == "demo_health"))
    queue = parse_last_json(next(row["stdout"] for row in steps if row["name"] == "demo_queue"))
    checks = {
        "demo_index_rows": health.get("indexed_items") == expected["demo_index_rows"],
        "demo_notes_total": health.get("notes_total") == expected["demo_notes_total"],
        "demo_queue_rows": queue.get("rows") == expected["demo_queue_rows"],
    }
    return {"name": "demo_expectations", "ok": all(checks.values()), "checks": checks}


def run_empty_index_probe() -> dict[str, Any]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="mindcite-empty-"))
    try:
        config_path = tmp_dir / "mindcite.empty.json"
        config = {
            "vault": {
                "root": str(tmp_dir),
                "indexes_dir": "indexes",
                "logs_dir": "logs",
                "notes_dir": "notes/zotero_reading",
                "notes_papers_dir": "notes/zotero_reading/_papers",
            },
            "zotero": {
                "database_path": "",
                "snapshot_database_path": "",
                "storage_path": "",
            },
            "llm": {
                "reader_config_path": str(ROOT / "_skills" / "Zotero-Reading-System" / "config" / "reader_config.json")
            },
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        step = run_step(
            "empty_index_probe",
            ["_skills/Zotero-Reading-System/scripts/zotero_ai_reading_pipeline.py", "--next-count", "1"],
            env={"MINDCITE_CONFIG": str(config_path)},
        )
        payload = parse_last_json(step["stdout"])
        step["ok"] = step["ok"] and payload.get("processed") == 0 and "No indexed papers found" in payload.get("message", "")
        return step
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    cleanup_demo_outputs()
    steps: list[dict[str, Any]] = []
    demo_env = {"MINDCITE_ROOT": str(DEMO_ROOT)}
    try:
        steps.append(run_step("structure_check", ["tools/structure_check.py"]))
        steps.append(run_step("safety_scan", ["tools/safety_scan.py"]))
        steps.append(run_step("demo_health", ["_skills/Zotero-Library-Sync/scripts/vault_health_check.py"], env=demo_env))
        steps.append(run_step("demo_queue", ["_skills/Classification-Governance-System/scripts/build_classification_review_queue.py", "--all"], env=demo_env))
        steps.append(run_step("validate_contracts", ["tools/validate_data_contracts.py", "--demo-only"]))
        steps.append(run_empty_index_probe())
        steps.append(check_demo_expectations(steps))
    finally:
        cleanup_demo_outputs()

    ok = all(step.get("ok") for step in steps)
    print(json.dumps({"ok": ok, "steps": steps}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
