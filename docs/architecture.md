# Architecture

MindCite 采用“索引层 + 笔记层 + 治理层”的结构。

## 数据流

```mermaid
flowchart LR
  Zotero["Zotero 本地库"] --> Index["indexes/zotero_library_index.jsonl"]
  Index --> Reading["精读流水线"]
  Reading --> Notes["notes/zotero_reading/_papers"]
  Notes --> QA["Notes 问答"]
  Notes --> Governance["分类治理"]
  Governance --> Synthesis["理论/方法/主题综述"]
```

## 模块

- `Zotero-Reading-System`：建立索引、读取全文缓存或 PDF、生成结构化精读笔记。
- `Notes-QA-System`：只基于新版 notes 回答问题。
- `Zotero-Library-Sync`：检查索引、notes 和状态日志之间的一致性。
- `Classification-Governance-System`：生成分类审核队列、标签体系审计和写回 dry-run。
- `Theory-Method-Synthesis-System`：按理论、方法、主题标签生成综述草稿。

## 配置层

所有脚本复用 `_skills/common/mindcite_config.py`。配置优先级：

1. 系统环境变量。
2. `.env`。
3. `config/mindcite.json`。
4. `config/mindcite.example.json`。
5. 当前仓库根目录默认值。

## 扩展原则

- 新数据源先转成统一索引，再进入后续流程。
- 新分类维度要同步更新 taxonomy、frontmatter、queue 和 synthesis。
- 新模型 provider 只修改 reader config 和 provider 调用，不要把 key 写进脚本。
- 写操作默认 dry-run，并保留可审计报告。
- 核心数据文件带 `schema_version`，并由 `tools/validate_data_contracts.py` 校验。
- 关键写入使用 `_skills/common/safe_io.py` 的原子写入工具。
- 需要清理旧笔记时先进入 `logs/quarantine`，不要直接删除。

## v0.2.0 安全底座

```mermaid
flowchart TD
  Schemas["schemas/*.schema.json"] --> Validate["tools/validate_data_contracts.py"]
  SafeIO["_skills/common/safe_io.py"] --> Writers["核心脚本写入"]
  Migrate["tools/migrate.py"] --> Versioned["schema_version 升级"]
  Quarantine["logs/quarantine"] --> Recover["误删可恢复"]
  Smoke["tools/smoke_test.py"] --> Demo["examples/demo-vault"]
```

长期扩展时，先更新 schema 和迁移，再改脚本行为。这样即使后续加入新模型、新数据库、新分类维度，也能先发现旧数据是否会被破坏。
