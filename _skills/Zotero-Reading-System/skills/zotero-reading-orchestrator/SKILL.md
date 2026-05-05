---
name: zotero-reading-orchestrator
description: 处理“请精读 Zotero 中 xxx”时使用。先查本地索引，再把目标条目交给 Python AI 精读脚本执行，而不是由对话层手工提炼。
---

# Zotero Reading Orchestrator

## 给 0 代码用户的 Codex 指令

```text
请从当前索引里挑选下一批 2 篇可以精读的文献并生成 notes。优先使用 Zotero 全文缓存，其次使用 PDF。不要重读已完成条目，除非我明确要求重跑。
```

指定单篇时：

```text
请精读 Zotero item key 为 ABC12345 的文献；如果找不到，先更新索引并告诉我是否仍然缺失。
```

Codex 应该先确认索引是否存在，再交给精读脚本执行。

## 输入解析

优先匹配：

1. `collection_path`
2. collection 名称
3. 论文标题
4. `item_key`

## 强制规则

- 先查 `${MINDCITE_ROOT}\indexes\zotero_library_index.jsonl`
- 不直接先扫 Zotero
- 不先扫旧笔记
- 如果索引缺失或无命中，先触发 `zotero-index-updater`

## 队列筛选

进入本轮队列的条目需满足：

- 命中目标分类或目标标题
- `reading_status != done`，或用户明确要求重跑
- `has_fulltext_cache = true` 或 `has_pdf = true`

## 交给脚本执行

实际精读不在对话层完成，而是交给：

`${MINDCITE_ROOT}\_skills\Zotero-Reading-System\scripts\zotero_ai_reading_pipeline.py`

典型调用方式：

- 指定条目：`--item-keys A1B2C3D4`
- 顺序推进：`--next-count 20`
- 强制覆盖：`--rerun-done`

## 输出要求

每轮结束后，至少汇报：

- 命中的目标范围
- 成功处理篇数
- `needs_pdf` 篇数
- `needs_note` 篇数
- 本轮日志文件路径
