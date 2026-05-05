# Extension Policy

MindCite 的长期原则是：新增功能可以很快，但写入数据必须很慢、很清楚、可恢复。

## 安全等级

| 等级 | 含义 | 要求 |
| --- | --- | --- |
| S0 | 只读分析 | 只读 Zotero、indexes、logs、notes，不写文件。 |
| S1 | 生成报告 | 只新增报告或缓存，不修改既有核心数据。 |
| S2 | 修改 MindCite 数据 | 会修改 notes、indexes、logs，必须支持 dry-run、备份或原子写入。 |
| S3 | 写回外部系统 | 会修改 Zotero 或其他外部数据库，必须显式 `--apply`，并在写回前生成备份。 |

## 新脚本准入规则

- 脚本顶部或文档中标明安全等级。
- 读取路径必须来自 `_skills/common/mindcite_config.py`，不要写死本机路径。
- 核心输出使用 `_skills/common/safe_io.py` 的原子写入函数。
- 不直接删除研究笔记；需要清理时先移动到 `logs/quarantine`。
- 修改数据结构时先更新 `schemas`，再补 `tools/migrate.py` 和 smoke test。
- 写回 Zotero 或其他外部系统时，默认 dry-run，真实写回必须显式传 `--apply`。

## 数据契约

v0.2.0 起，核心数据都应该带 `schema_version`：

- `indexes/zotero_library_index.jsonl`
- `logs/reading_status.jsonl`
- `notes/zotero_reading/_papers/*.md` frontmatter
- `indexes/classification_taxonomy.json`
- `indexes/classification_review_queue.jsonl`

新增字段时尽量保持向后兼容；删除或重命名字段时必须提供迁移脚本。

## 推荐开发流程

```powershell
python tools/structure_check.py
python tools/safety_scan.py
python tools/validate_data_contracts.py --demo-only
python tools/migrate.py --dry-run
python tools/smoke_test.py
```

如果要在真实 Vault 上迁移：

```powershell
python tools/migrate.py --dry-run
python tools/migrate.py --apply
python tools/validate_data_contracts.py
```
