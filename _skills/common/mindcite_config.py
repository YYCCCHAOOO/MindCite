from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")


def _find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "config" / "mindcite.example.json").exists():
            return candidate
        if (candidate / "config" / "mindcite.json").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def _load_dotenv(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _expand_env(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2) or ""
        return os.environ.get(name, default)

    return ENV_PATTERN.sub(replace, os.path.expandvars(value)).strip()


def expand_env_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: expand_env_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env_data(item) for item in value]
    return _expand_env(value)


def _deep_get(data: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return _expand_env(current)


def _resolve_path(value: Any, root: Path, fallback: str | Path) -> Path:
    expanded = _expand_env(value)
    if not expanded:
        expanded = fallback
    path = Path(str(expanded)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


def _optional_path(value: Any, root: Path) -> Path | None:
    expanded = _expand_env(value)
    if not expanded:
        return None
    path = Path(str(expanded)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


def load_raw_config(start: Path | None = None) -> tuple[Path, dict[str, Any]]:
    repo_root = _find_repo_root(start)
    _load_dotenv(repo_root)
    config_env = os.environ.get("MINDCITE_CONFIG", "").strip()
    if config_env:
        config_path = Path(config_env).expanduser()
    else:
        config_path = repo_root / "config" / "mindcite.json"
    if not config_path.exists():
        config_path = repo_root / "config" / "mindcite.example.json"
    if not config_path.exists():
        return repo_root, {}
    return repo_root, json.loads(config_path.read_text(encoding="utf-8-sig"))


@dataclass(frozen=True)
class MindCiteConfig:
    root: Path
    indexes_dir: Path
    logs_dir: Path
    notes_dir: Path
    notes_papers_dir: Path
    reader_config_path: Path
    zotero_db_path: Path | None
    zotero_snapshot_path: Path | None
    zotero_storage_path: Path | None

    @property
    def index_path(self) -> Path:
        return self.indexes_dir / "zotero_library_index.jsonl"

    @property
    def status_path(self) -> Path:
        return self.logs_dir / "reading_status.jsonl"

    @property
    def taxonomy_path(self) -> Path:
        return self.indexes_dir / "classification_taxonomy.json"


def load_config(start: Path | None = None) -> MindCiteConfig:
    repo_root, data = load_raw_config(start)
    root_value = os.environ.get("MINDCITE_ROOT") or _deep_get(data, "vault.root", "")
    root = _resolve_path(root_value, repo_root, repo_root).resolve()

    indexes_dir = _resolve_path(_deep_get(data, "vault.indexes_dir", "indexes"), root, "indexes")
    logs_dir = _resolve_path(_deep_get(data, "vault.logs_dir", "logs"), root, "logs")
    notes_dir = _resolve_path(_deep_get(data, "vault.notes_dir", "notes/zotero_reading"), root, "notes/zotero_reading")
    notes_papers_dir = _resolve_path(
        _deep_get(data, "vault.notes_papers_dir", "notes/zotero_reading/_papers"),
        root,
        "notes/zotero_reading/_papers",
    )
    reader_config_path = _resolve_path(
        _deep_get(data, "llm.reader_config_path", "_skills/Zotero-Reading-System/config/reader_config.json"),
        root,
        "_skills/Zotero-Reading-System/config/reader_config.json",
    )

    return MindCiteConfig(
        root=root,
        indexes_dir=indexes_dir,
        logs_dir=logs_dir,
        notes_dir=notes_dir,
        notes_papers_dir=notes_papers_dir,
        reader_config_path=reader_config_path,
        zotero_db_path=_optional_path(os.environ.get("ZOTERO_DB_PATH") or _deep_get(data, "zotero.database_path", ""), root),
        zotero_snapshot_path=_optional_path(
            os.environ.get("ZOTERO_SNAPSHOT_DB_PATH") or _deep_get(data, "zotero.snapshot_database_path", ""),
            root,
        ),
        zotero_storage_path=_optional_path(os.environ.get("ZOTERO_STORAGE_PATH") or _deep_get(data, "zotero.storage_path", ""), root),
    )


def configured_existing_paths(*paths: Path | None) -> list[Path]:
    return [path for path in paths if path is not None and path.exists()]
