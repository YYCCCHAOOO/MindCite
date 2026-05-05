---
name: notes-answering
description: 单次问答技能。根据新版精读笔记定位证据并回答用户问题。
---

# Notes Answering

## 工作方式

1. 从 `${MINDCITE_ROOT}\notes\zotero_reading` 中找相关笔记
2. 优先按题名、关键词、分类路径匹配
3. 只读最相关的几篇
4. 基于现有 note 输出结论

## 强制约束

- 不能把旧版 note 当证据
- 不能把 Zotero 数据库当答案来源
- 不能因为常识而替用户补写文献结论

## 证据不足时

直接说明：

`当前新版 notes 中证据不足`
