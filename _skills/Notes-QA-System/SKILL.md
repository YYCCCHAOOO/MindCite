---
name: notes-qa-system
description: 根据新版精读笔记回答问题。只使用 notes\\zotero_reading 下的有效笔记，不扫描旧 note，不回到 Zotero 原库重新阅读。
---

# Notes QA System

## 给 0 代码用户的 Codex 指令

用户可以直接这样说：

```text
请只基于 MindCite 已生成的新版 notes，回答这个问题：<你的问题>。如果当前 notes 中证据不足，请明确说证据不足，不要用外部常识补答案。
```

Codex 应该先定位相关 note，再引用 note 中已有内容回答。不要要求用户提供脚本名或文件路径，除非找不到相关笔记。

## 触发条件

以下类型的问题默认触发本技能：

- 根据文献笔记回答问题
- 比较几篇已精读论文
- 总结某个主题在已生成 notes 中的发现
- 判断某个说法是否已被当前笔记支持

## 唯一证据范围

只使用：

- `${MINDCITE_ROOT}\notes\zotero_reading`
- 必要时可辅助读取 `${MINDCITE_ROOT}\indexes\zotero_library_index.jsonl` 定位对应 note

明确不使用：

- `notes` 根目录下其他旧文件
- Zotero 中的 note、批注、摘要
- 外部记忆补全

## 回答规则

1. 先定位相关 note
2. 再读取 note 内容
3. 只基于 note 中已写出的证据回答
4. 如果找不到足够证据，明确写出“当前新版 notes 中证据不足”

## 默认回答结构

1. 结论
2. 支持笔记
3. 差异或争议
4. 证据不足处
