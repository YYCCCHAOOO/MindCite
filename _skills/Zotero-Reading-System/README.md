# Zotero Reading System

新的默认流程不再直接依赖裸 PDF 解析。

## 当前设计

1. `update_zotero_index.py`
- 刷新本地索引
- 记录分类路径、PDF 路径、附件 key、`.zotero-ft-cache` 路径

2. `zotero_ai_reading_pipeline.py`
- 优先读取 Zotero 全文缓存
- 按块切分原文
- 可调用：
  - DeepSeek `deepseek-v4-flash`
  - SiliconFlow embeddings `BAAI/bge-m3`
- 最后生成接近 Obsidian 模板结构的精读笔记

3. 输出位置
- 索引：`${MINDCITE_ROOT}\indexes`
- 日志：`${MINDCITE_ROOT}\logs`
- 笔记：`${MINDCITE_ROOT}\notes\zotero_reading`

## 配置

配置文件：

`${MINDCITE_ROOT}\_skills\Zotero-Reading-System\config\reader_config.json`

优先读取环境变量：

- `DEEPSEEK_API_KEY`
- `SILICONFLOW_API_KEY`

如果没有配置 key，脚本会回退到本地 heuristic 模式，但推荐始终配置外部接口。
