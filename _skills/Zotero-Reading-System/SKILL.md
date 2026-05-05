---
name: zotero-reading-system
description: 收到“更新索引”或“请精读 Zotero 中 xxx”时使用。先刷新本地索引，再由 Python 精读流水线优先读取 Zotero 的全文缓存（.zotero-ft-cache），必要时才回退 PDF，并结合外部 embedding / LLM 生成结构化精读笔记。
---

# Zotero Reading System

## 触发条件

- `更新索引`
- `更新 Zotero 索引`
- `请精读 Zotero 中 xxx`
- `继续精读 Zotero 中 xxx`
- `重跑 Zotero 中 xxx`

## 新工作流总原则

1. 调度、规划、检查由 agent 负责。
2. 真正的论文精读和写笔记由 `.py` 工作流负责。
3. 阅读优先级改为：
   - `Zotero .zotero-ft-cache`
   - `PDF 原文`
   - 没有这两者则记为 `needs_pdf`
4. 允许使用外部接口：
   - DeepSeek: `https://api.deepseek.com`，模型 `deepseek-v4-flash`
   - SiliconFlow Embeddings: `https://api.siliconflow.cn/v1/embeddings`，模型 `BAAI/bge-m3`
5. 即使外部接口暂未配置，脚本也必须能以 fallback 模式跑通，但优先使用外部接口。

## 执行顺序

1. `zotero-index-updater`
- 刷新索引，并强化以下字段：
  - 分组路径
  - PDF 路径
  - 附件 key
  - Zotero 全文缓存路径

2. `zotero-reading-orchestrator`
- 按索引决定本轮目标条目，不先扫 Zotero，不先扫旧笔记。

3. `scripts/zotero_ai_reading_pipeline.py`
- 从索引读取目标条目。
- 优先加载 `.zotero-ft-cache`。
- 对全文切块。
- 使用 embedding 检索与 LLM 结构化生成。
- 按模板写入 `notes\zotero_reading\_papers`。
- 将 Zotero 分类、主分类、理论/方法/主题分类状态写入 note frontmatter 属性。
- 更新状态文件与运行日志。

## 强制约束

- `notes\zotero_reading\` 是唯一有效笔记目录。
- 单篇精读笔记使用稳定存储目录 `_papers`；分类不再由文件夹路径表达。
- 不复用旧版 note。
- 不把 Zotero note / 批注当作精读依据。
- 允许保留 Zotero 自己生成的全文缓存文本，因为那本质上是 PDF 的更好识别结果。
- 同一 `item_key` 的旧输出允许覆盖。

## 默认输出位置

- 索引：`${RESEARCHVAULT_ROOT}\indexes`
- 日志：`${RESEARCHVAULT_ROOT}\logs`
- 新版笔记根目录：`${RESEARCHVAULT_ROOT}\notes\zotero_reading`
- 新生成单篇笔记：`${RESEARCHVAULT_ROOT}\notes\zotero_reading\_papers`

## 关键脚本

- 索引刷新：`${RESEARCHVAULT_ROOT}\_skills\Zotero-Reading-System\scripts\update_zotero_index.py`
- AI 精读：`${RESEARCHVAULT_ROOT}\_skills\Zotero-Reading-System\scripts\zotero_ai_reading_pipeline.py`
- 配置：`${RESEARCHVAULT_ROOT}\_skills\Zotero-Reading-System\config\reader_config.json`

