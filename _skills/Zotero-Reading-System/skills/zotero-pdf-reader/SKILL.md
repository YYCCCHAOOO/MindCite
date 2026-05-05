---
name: zotero-pdf-reader
description: 单篇文献阅读技能。只读取 PDF 原文，不看 Zotero 批注、不看 Zotero note、不看旧版 notes。
---

# Zotero PDF Reader

## 给 0 代码用户的 Codex 指令

```text
请只基于这篇文献的 PDF 或 Zotero 全文缓存提取研究问题、数据、方法、变量、核心发现和与我研究的相关性。没有 PDF 或全文缓存就标记 needs_pdf，不要用摘要或旧笔记替代。
```

Codex 应该明确告诉用户文本来源是 `zotero-ft-cache` 还是 `PDF`。

## 唯一阅读依据

只允许使用以下来源：

- 与目标 `item_key` 对应的 PDF 原文

明确禁止使用：

- Zotero highlights
- Zotero annotations
- Zotero notes
- 旧版 Obsidian notes
- 历史摘要

## 如果没有 PDF

- 立即停止阅读
- 返回 `needs_pdf`
- 不要尝试用摘要或 note 顶替全文阅读

## 阅读目标

从 PDF 原文中提取以下内容：

- 题目、作者、年份、来源
- 研究问题
- 研究对象或样本
- 数据来源
- 方法
- 关键变量
- 核心发现
- 与用户研究的相关性

## 质量要求

- 以原文为准
- 信息不足就如实写不足
- 不借用旧 note 补空白
