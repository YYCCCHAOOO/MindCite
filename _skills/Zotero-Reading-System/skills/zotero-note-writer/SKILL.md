---
name: zotero-note-writer
description: 将 PDF 原文阅读结果写成新版本精读笔记，只写入 notes\\zotero_reading，并同步操作日志与断点状态。
---

# Zotero Note Writer

## 输出目录

只写入：

`${RESEARCHVAULT_ROOT}\notes\zotero_reading\_papers\`

Zotero 分类、主分类、理论/方法/主题分类只写入 note frontmatter 属性，不再用文件夹路径表达。

## 覆盖规则

- 同一 `item_key` 已存在旧版本时，允许覆盖或替换
- 用户只关心新版本 note，旧版本不再作为有效输出

## 模板

使用：

`${RESEARCHVAULT_ROOT}\模板\论文精读模板.md`

## 操作日志

每轮任务必须在 `${RESEARCHVAULT_ROOT}\logs` 下生成一份日志，记录：

- 处理时间
- 目标分类或目标条目
- 新增了几篇文献
- 每篇论文的简要总结
- 缺失 PDF 的论文
- 写入失败或待补 note 的论文

## 断点状态文件

必须维护：

`${RESEARCHVAULT_ROOT}\logs\reading_status.jsonl`

每条至少包含：

- `item_key`
- `title`
- `target`
- `status`
- `note_path`
- `updated_at`
- `reason`

状态只允许使用：

- `done`
- `skipped`
- `needs_pdf`
- `needs_note`

## 目标

下次继续处理时，只处理 `status != done` 的条目。

