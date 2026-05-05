# ResearchVault Skills

本目录现在保留三条明确主线：

1. `Zotero-Reading-System`
用于更新 Zotero 本地索引、按索引定位条目，并优先基于 Zotero 全文缓存生成新的精读笔记。

2. `Notes-QA-System`
用于只基于新版本精读笔记回答问题。

3. 分类治理与脉络系统
- `Zotero-Library-Sync`
用于检查 Zotero 索引、notes、状态日志之间的同步健康状况，并生成旧 note frontmatter 补齐 dry-run。
- `Classification-Governance-System`
用于生成理论/方法/主题分类审核队列、可审计标签体系提案，以及 Zotero 写回 dry-run。分类规则优先读取 `${RESEARCHVAULT_ROOT}\indexes\classification_taxonomy.json`。
- `Theory-Method-Synthesis-System`
用于基于现有 notes 生成理论、方法或主题分类综述草稿。
- `Xiaohongshu-Knowledge-Translation`
用于把已审核的分类综述转为小红书草稿流程。

目录说明：
- `common/`
存放公开版共享配置读取逻辑。
- `Zotero-Reading-System/config/reader_config.json`
存放 LLM 与 embedding 的 provider 默认配置。真实 API key 只放在 `.env` 或系统环境变量中。
- `${ZOTERO_SNAPSHOT_DB_PATH}`
可选的 Zotero 数据库快照路径，仅作为索引构建和排障时的只读备用源，不应提交到仓库。

当前默认有效输出目录：
- `${RESEARCHVAULT_ROOT}\indexes`
- `${RESEARCHVAULT_ROOT}\logs`
- `${RESEARCHVAULT_ROOT}\notes\zotero_reading`

新生成的单篇精读笔记默认进入 `${RESEARCHVAULT_ROOT}\notes\zotero_reading\_papers`；分类信息写入 note 属性和索引，不再通过文件夹路径表达。

分类治理默认输出：
- `${RESEARCHVAULT_ROOT}\indexes\vault_health_report.md`
- `${RESEARCHVAULT_ROOT}\indexes\classification_taxonomy.json`
- `${RESEARCHVAULT_ROOT}\indexes\classification_review_queue.jsonl`
- `${RESEARCHVAULT_ROOT}\indexes\audited_tag_taxonomy_proposal.md`
- `${RESEARCHVAULT_ROOT}\indexes\audited_tag_taxonomy_proposal.json`
- `${RESEARCHVAULT_ROOT}\indexes\orphan_notes.jsonl`
- `${RESEARCHVAULT_ROOT}\indexes\note_frontmatter_backfill_preview.jsonl`
- `${RESEARCHVAULT_ROOT}\indexes\note_frontmatter_backfill_summary.md`
- `${RESEARCHVAULT_ROOT}\indexes\zotero_writeback_dryrun.jsonl`
- `${RESEARCHVAULT_ROOT}\indexes\classification_synthesis_*.md`

