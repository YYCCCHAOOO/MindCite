from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


DATA_CONTRACT_VERSION = "0.2.0"


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_inside(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root:
        return
    if resolved_root not in resolved_path.parents:
        raise ValueError(f"Refusing to operate outside root: {resolved_path}")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding=encoding, newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    atomic_write_text(path, body + ("\n" if body else ""))


def backup_file(path: Path, backup_dir: Path, *, root: Path | None = None, reason: str = "") -> Path | None:
    if not path.exists():
        return None
    if root is not None:
        _ensure_inside(path, root)
    backup_dir.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix or ".bak"
    backup_path = backup_dir / f"{path.stem}.{now_stamp()}{suffix}.bak"
    shutil.copy2(path, backup_path)
    manifest_path = backup_dir / "manifest.jsonl"
    entry = {
        "schema_version": DATA_CONTRACT_VERSION,
        "source_path": str(path),
        "backup_path": str(backup_path),
        "reason": reason,
        "created_at": now_iso(),
    }
    with manifest_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return backup_path


def quarantine_file(path: Path, *, root: Path, quarantine_root: Path, reason: str, script: str) -> Path | None:
    if not path.exists():
        return None
    _ensure_inside(path, root)
    batch_dir = quarantine_root / now_stamp()
    rel = path.resolve().relative_to(root.resolve())
    target = batch_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}.{uuid.uuid4().hex}{target.suffix}")
    shutil.move(str(path), str(target))
    manifest_path = batch_dir / "manifest.jsonl"
    entry = {
        "schema_version": DATA_CONTRACT_VERSION,
        "original_path": str(path),
        "quarantine_path": str(target),
        "reason": reason,
        "script": script,
        "created_at": now_iso(),
    }
    with manifest_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return target
