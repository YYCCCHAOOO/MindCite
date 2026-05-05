---
name: zotero-index-updater
description: 收到“更新索引”时使用。查询 Zotero，生成支持 AI 精读流水线的本地索引，重点强化分组、PDF 路径、附件 key 和全文缓存路径。
---

# Zotero Index Updater

## 目标

刷新出一套能直接喂给 Python 精读流水线的索引文件，而不只是给人工搜索用。

## 强制流程

1. 读取 Zotero 数据库
- 优先实时库
- 若实时库不可读，再退回快照

2. 强化附件与文本字段
- 对每条文献尽量写入：
  - `attachment_keys`
  - `pdf_paths`
  - `primary_pdf_path`
  - `fulltext_cache_paths`
  - `primary_fulltext_cache_path`
  - `has_fulltext_cache`
  - `zotero_select_uri`
  - `zotero_open_pdf_uri`

3. 刷新索引文件
- `${RESEARCHVAULT_ROOT}\indexes\zotero_library_index.jsonl`
- `${RESEARCHVAULT_ROOT}\indexes\zotero_collection_tree.json`
- `${RESEARCHVAULT_ROOT}\indexes\zotero_index_summary.md`
- `${RESEARCHVAULT_ROOT}\indexes\zotero_index_meta.json`

4. 对齐新版 notes 元数据
- 仅检查 `${RESEARCHVAULT_ROOT}\notes\zotero_reading`
- 按 `item_key` 定位现有 note，并写入 `active_note_path`
- Zotero 分类变化只反映到索引字段，不在索引刷新时移动或删除 note 文件

5. 写日志
- 新增一份 `logs\update_index_*.md`

## 索引字段最低要求

- `item_key`
- `title`
- `item_type`
- `year`
- `doi`
- `collection_paths`
- `primary_collection_path`
- `attachment_keys`
- `pdf_paths`
- `primary_pdf_path`
- `has_pdf`
- `fulltext_cache_paths`
- `primary_fulltext_cache_path`
- `has_fulltext_cache`
- `reading_status`
- `active_note_path`
- `updated_at`

