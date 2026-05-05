---
name: classification-governance-system
description: 基于新版精读 notes 生成理论、方法、主题候选分类与人工审核队列；也可生成 Zotero 写回 dry-run 计划，但第一版不真实写回 Zotero。
---

# Classification Governance System

## 给 0 代码用户的 Codex 指令

用户可以直接这样说：

```text
请基于当前新版精读 notes 生成 theory、method、topic 分类审核队列。只生成建议，不写回 Zotero。完成后告诉我队列有多少条、哪些建议需要人工审核、文件路径在哪里。
```

如果用户想进入写回流程，Codex 必须先引导 dry-run：

```text
请只根据 approved 的分类建议生成 Zotero 写回 dry-run，不要执行 --apply。请解释会添加哪些 collection path，确认不会删除现有分类。
```

Codex 不应该鼓励用户直接批量写回 Zotero。分类模块的默认语气应该是“先建议、再审核、再 dry-run、最后小批量 apply”。

## 触发条件

- `生成分类审核队列`
- `给这些论文建议理论/方法/主题分类`
- `检查哪些论文应该加入某个分类`
- `生成 Zotero 写回 dry-run`
- `调整分类词表`
- `生成标签体系提案`
- `审计标签体系`

## 输入范围

- `${MINDCITE_ROOT}\notes\zotero_reading`
- `${MINDCITE_ROOT}\indexes\zotero_library_index.jsonl`
- `${MINDCITE_ROOT}\indexes\zotero_collection_tree.json`
- `${MINDCITE_ROOT}\indexes\classification_taxonomy.json`

## 默认脚本

生成分类审核队列：
`${MINDCITE_ROOT}\_skills\Classification-Governance-System\scripts\build_classification_review_queue.py`

生成 Zotero 写回 dry-run：
`${MINDCITE_ROOT}\_skills\Classification-Governance-System\scripts\build_zotero_writeback_dryrun.py`

生成可审计标签体系提案：
`${MINDCITE_ROOT}\_skills\Classification-Governance-System\scripts\build_tag_taxonomy_proposal.py`

默认输出：
- `${MINDCITE_ROOT}\indexes\classification_review_queue.jsonl`
- `${MINDCITE_ROOT}\indexes\zotero_writeback_dryrun.jsonl`
- `${MINDCITE_ROOT}\indexes\audited_tag_taxonomy_proposal.md`
- `${MINDCITE_ROOT}\indexes\audited_tag_taxonomy_proposal.json`

## 分类词表

- 可执行配置：`${MINDCITE_ROOT}\indexes\classification_taxonomy.json`
- 人工维护模板：`${MINDCITE_ROOT}\模板\分类词表模板.md`
- 先编辑词表，再重新生成审核队列。
- 词表分为 `theory`、`method`、`topic` 三个维度；每个条目包含 `label`、`target_collection_base`、`keywords`、`negative_keywords`，可选 `target_collection_path` 用于精确映射现有 Zotero 分类。

## 强制规则

- 只提出候选分类，不覆盖原 Zotero 分类。
- `review_status` 默认必须是 `pending`。
- 写回计划必须是 dry-run，必须包含 `requires_user_approval=true`。
- 不调用 Zotero 写 API。
- 不改 note frontmatter；后续只有用户批准后才可进入写入步骤。
- 不把所有出现 `risk` 的论文都归入风险管理；不要把一般 `spillover` 直接等同于金融传染理论。
- 新增或拆分标签前先生成可审计提案，包含证据词、命中文献和 `review_status`。

## 分类维度

- `suggested_theory_tags`：理论体系，如金融传染、全球金融周期、避险资产理论、储备货币理论。
- `suggested_method_tags`：方法体系，如 MIDAS、DCC-GARCH、TVP-VAR、CoVaR、面板固定效应。
- `suggested_topic_tags`：研究主题，如汇率联动、系统性风险、人民币国际化、能源金融、波动溢出。

## 汇报要求

每轮结束至少说明：
- 审核队列条目数
- 有理论/方法/主题候选的数量
- dry-run 是否包含删除动作，必须为否
- 下一步需要用户审核的文件路径

## V2 标签级审计原则

- 用户主要审核“标签是否值得存在”，不逐篇审核“某篇论文是否属于某个标签”。
- 已批准标签可以由 AI 或规则自动分配并自动回填到 note frontmatter。
- 只有当系统发现新标签、建议拆分标签、建议合并标签或标签命名冲突时，才进入用户审计。
- 新标签在用户批准前不得写入正式 taxonomy，不得写入 Zotero。
- 标签级审计默认输出：
  - `${MINDCITE_ROOT}\indexes\tag_taxonomy_current.md`
  - `${MINDCITE_ROOT}\indexes\tag_taxonomy_audit.md`
  - `${MINDCITE_ROOT}\indexes\tag_taxonomy_audit.json`
- 标签级审计脚本：
  - `${MINDCITE_ROOT}\_skills\Classification-Governance-System\scripts\build_tag_taxonomy_audit.py`
