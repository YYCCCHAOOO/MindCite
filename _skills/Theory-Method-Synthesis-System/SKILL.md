---
name: theory-method-synthesis-system
description: 对某个理论、方法或主题分类下的 Zotero 精读 notes 生成分类脉络综述；默认使用 Obsidian 双链交叉引用，方便从综述跳转到单篇论文笔记。
---

# Theory Method Synthesis System

## 给 0 代码用户的 Codex 指令

用户可以直接这样说：

```text
请基于已生成的新版 notes，为“金融传染”生成一份理论综述。只使用 notes 中已有证据，不重读 PDF，不写回 Zotero。完成后告诉我综述文件路径、引用了哪些笔记、哪些地方证据不足。
```

方法或主题也可以这样说：

```text
请为“DCC-GARCH”生成方法综述，重点整理它服务哪些研究主题、常见变量和主要发现。
```

Codex 应该把综述当成 Obsidian 入口和研究整理草稿，不应把它包装成可直接发表的论文文本。

## 触发条件

- 用户要求梳理某个理论、方法论、模型、研究主题或 Zotero 分类下的文献脉络。
- 用户要求生成“分类综述”“理论综述”“方法综述”“主题综述”“核心文献入口”。
- 用户希望在一个综述中快速跳转到相关论文笔记。

## 证据范围

- 默认只读取 `${MINDCITE_ROOT}\notes\zotero_reading\_papers` 中的现有精读笔记。
- 读取 `${MINDCITE_ROOT}\indexes\classification_taxonomy.json` 判断标签维度、父级、子级和组合模型关系。
- 可读取 note frontmatter 中的期刊、Zotero 分类、理论、方法、主题字段。
- 不把外部常识写成 Vault 已有结论；若需要外部文献补全，必须标为“缺口文献/后续检索”。

## 默认脚本

运行：

```powershell
python ${MINDCITE_ROOT}\_skills\Theory-Method-Synthesis-System\scripts\build_classification_synthesis.py --label <分类名>
```

默认输出按标签架构分层，不再使用 `classification_synthesis_` 前缀：

- 理论：`${MINDCITE_ROOT}\notes\classification_synthesis\理论\<父级理论>\<分类名>.md`
- 方法组合模型：`${MINDCITE_ROOT}\notes\classification_synthesis\方法\组合模型\<父级组合>\<分类名>.md`
- 主题：`${MINDCITE_ROOT}\notes\classification_synthesis\主题\<父级主题>\<分类名>.md`
- 总入口：`${MINDCITE_ROOT}\notes\classification_synthesis\分类综述入口.md`

## Obsidian 交叉引用规则

- 单篇论文必须使用 `[[笔记文件名|论文题名]]` 链接，保证能从综述跳转到原始精读笔记。
- 数据库视图使用 `[[文献总览|文献总览]]`、`[[理论方法主题|理论方法主题视图]]`、`[[高质量期刊|高质量期刊视图]]` 这类链接。
- 综述只组织入口和脉络，不改写单篇论文笔记正文。

## 综述结构规则

- 标题只用分类名，例如 `# 金融传染`，不带脚本前缀。
- 开头必须有一段标签总述，让用户快速知道这个标签是什么、当前 Vault 覆盖什么内容、该从哪里读起。
- `核心文献入口` 放在前部，并尽量抽取单篇笔记正文中的完整“研究结论/核心发现”段落。
- 每篇核心文献在完整关键发现后，补一句简短的“对该标签的贡献”。
- 统计类信息放在 `全部匹配文献` 前面，避免开头太重。

## 强制边界

- 不移动精读 notes。
- 不重读 PDF。
- 不写回 Zotero。
- 不修改精读主流程。
- 不批量生成发布内容。
