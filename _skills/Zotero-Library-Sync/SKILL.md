---
name: zotero-library-sync
description: 检查 Zotero 索引、精读 notes、分类属性、Publication Tag 与 Obsidian Bases 视图之间的同步状态；生成健康报告、属性补齐 dry-run、期刊等级同步和位置整理。
---

# Zotero Library Sync

## 给 0 代码用户的 Codex 指令

用户可以直接这样说：

```text
请帮我检查 MindCite 的 Zotero 索引、reading_status 和 notes 是否同步。请用自然语言告诉我 notes 总数、orphan notes、缺失 frontmatter 字段、done 但找不到 note 的条目，以及报告文件位置。
```

如果要修复旧数据，Codex 应先生成 dry-run 或迁移预览，再解释风险，不应直接改 notes。

## 触发条件

- `健康检查`
- `检查 Zotero 和 notes 是否同步`
- `补旧 notes 属性`
- `同步 publication tag`
- `同步期刊等级`
- `整理 notes 位置`
- `生成 Obsidian 数据库视图`

## 证据范围

- `${MINDCITE_ROOT}\indexes`
- `${MINDCITE_ROOT}\logs\reading_status.jsonl`
- `${MINDCITE_ROOT}\notes\zotero_reading`
- `${ZOTERO_DB_PATH}`

## 默认脚本

- 健康检查：`${MINDCITE_ROOT}\_skills\Zotero-Library-Sync\scripts\vault_health_check.py`
- 旧 note 分类属性补齐：`${MINDCITE_ROOT}\_skills\Zotero-Library-Sync\scripts\backfill_note_frontmatter.py`
- 旧 note 迁移到 `_papers`：`${MINDCITE_ROOT}\_skills\Zotero-Library-Sync\scripts\migrate_legacy_notes_to_papers.py`
- Publication Tag 同步：`${MINDCITE_ROOT}\_skills\Zotero-Library-Sync\scripts\sync_publication_tags_to_notes.py`

## Publication Tag 同步规则

- Zotero 期刊等级信息主要来自条目的 `Extra` 字段。
- 支持解析：`JCR分区`、`中科院分区升级版`、`中科院分区基础版`、`影响因子`、`5年影响因子`、`FT50`、`UTD24`、`EI`、`南农高质量`。
- 同步到 note frontmatter：
  - `publication_title`
  - `journal_abbreviation`
  - `publication_tags`
  - `journal_rank_tags`
  - `jcr_quartile`
  - `cas_partition`
  - `cas_partition_basic`
  - `impact_factor`
  - `impact_factor_5y`
  - `elite_journal_tags`
  - `publication_sync_status`
- 默认先 dry-run；真实写入必须备份。

## Obsidian Bases 视图

- 入口：`${MINDCITE_ROOT}\数据库视图\文献数据库入口.md`
- 总览：`${MINDCITE_ROOT}\数据库视图\文献总览.base`
- 高质量期刊：`${MINDCITE_ROOT}\数据库视图\高质量期刊.base`
- 理论/方法/主题：`${MINDCITE_ROOT}\数据库视图\理论方法主题.base`

## 强制规则

- 不写回 Zotero。
- 不删除 notes。
- 真实写入 note 前必须能回滚：需要备份目录或 dry-run 预览。
- 分类以属性表达，不再按文件夹表达。

## 汇报要求

每轮至少说明：
- notes 总数与 `_papers` 数量
- orphan notes 数
- 缺失分类属性数量
- Publication Tag 同步数量
- 备份位置
