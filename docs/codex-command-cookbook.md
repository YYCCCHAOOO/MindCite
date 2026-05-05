# Codex Command Cookbook

这份文档面向 0 代码基础用户。你不需要记脚本名，也不需要先理解目录结构；把下面的自然语言指令复制给 Codex，让 Codex 帮你执行、检查和解释结果。

核心安全规则：

- 默认只读 Zotero。
- 不提交 `.env`、真实 notes、indexes、logs、PDF、Zotero 数据库或 API key。
- 不执行任何 `--apply`，除非你明确要求并已经看过 dry-run。
- 测试精读通路时可以要求 Codex 设置 `MINDCITE_OFFLINE=1`，避免调用远程模型。

## 1. 智能部署

```text
请从 https://github.com/YYCCCHAOOO/MindCite 拉取仓库，帮我创建一个私有 MindCite Vault。请自动完成依赖安装、配置文件复制、结构检查和 demo smoke test。然后只读探测我的本机 Zotero 数据库和 storage 路径，写入本地 .env，并运行 update_zotero_index.py 生成本地索引。不要提交 .env、indexes、logs、notes、PDF、Zotero 数据库或任何 API key；不要执行任何 --apply。
```

Codex 应该汇报：

- 仓库路径。
- Python 依赖是否安装成功。
- Zotero 数据库和 storage 路径是否找到。
- `structure_check.py` 和 `smoke_test.py` 是否通过。
- 索引生成了多少文献、多少分类、多少缺 PDF。

## 2. 只跑 demo

```text
我现在只想试跑 MindCite 的合成 demo，不连接我的真实 Zotero，也不要使用 API key。请运行结构检查、数据契约检查和 demo smoke test，并告诉我是否能看到 ok: true。
```

适合第一次下载后确认环境可用。

## 3. 只读更新 Zotero 索引

```text
请只读连接我的 Zotero，更新 MindCite 本地索引。不要写回 Zotero，不要移动或删除 notes。完成后告诉我索引条目数、分类数、缺 PDF 数、fallback 待分类数量，以及生成的索引文件路径。
```

Codex 应该重点检查：

- `indexes/zotero_library_index.jsonl`
- `indexes/zotero_index_meta.json`
- `indexes/zotero_index_summary.md`
- `logs/update_index_*.md`

## 4. 离线测试精读

```text
请用 MindCite 离线测试精读通路。设置 MINDCITE_OFFLINE=1，只处理 1 篇有 PDF 或全文缓存的文献，不调用远程 LLM 或 embedding。完成后告诉我生成的 note 路径、reading_status 状态和日志路径。
```

适合确认精读流程能写出 notes，但不消耗模型额度。

## 5. 正常精读下一批文献

```text
请基于当前 Zotero 索引继续精读下一批 2 篇文献。优先读取 Zotero 全文缓存，其次读取 PDF。完成后告诉我成功生成几篇 notes、哪些条目 needs_pdf、哪些条目 needs_note，以及日志文件位置。
```

如果想指定某篇：

```text
请精读 Zotero item key 为 ABC12345 的文献。如果索引不存在，先更新索引。完成后告诉我 note 路径和生成模式。
```

## 6. 基于 notes 问答

```text
请只基于 MindCite 已生成的新版 notes，回答这个问题：金融传染理论下风险跨境传导的主要机制是什么？如果当前 notes 中证据不足，请明确说证据不足，不要从外部常识补答案。
```

适合做文献复习、论文开题和综述草稿前的证据整理。

## 7. 健康检查

```text
请运行 MindCite 健康检查，看看 Zotero 索引、reading_status 和 notes 是否同步。请告诉我 notes 总数、_papers 数量、orphan notes 数、done 但缺 note 的数量，以及报告路径。
```

建议在精读、迁移和分类前都跑一次。

## 8. 生成分类审核队列

```text
请基于当前新版精读 notes 生成分类审核队列。只生成 theory、method、topic 的候选分类，不写回 Zotero。完成后告诉我队列条目数、有理论/方法/主题候选的数量，以及 classification_review_queue.jsonl 路径。
```

然后人工审核：

```text
请帮我阅读 classification_review_queue.jsonl 的前 20 条，按置信度和证据摘要解释哪些分类建议比较可靠，哪些需要我人工确认。不要直接把 pending 改成 approved。
```

## 9. 生成 Zotero 写回 dry-run

```text
请只根据 review_status=approved 的分类审核队列生成 Zotero 写回 dry-run。不要执行 --apply。完成后告诉我会给哪些 item_key 添加哪些 collection path、是否会删除任何现有分类、目标 collection 是否已存在。
```

真实写回前必须再说一遍：

```text
请预览前 5 条 Zotero SQLite 写回计划，不要 --apply。我要先确认结果。
```

## 10. 标签体系 taxonomy

```text
请帮我查看 examples/demo-vault/indexes/classification_taxonomy.json 这个金融研究版 taxonomy 示例，并根据我的研究方向给出删减建议。不要直接改我的正式 taxonomy，先输出建议清单。
```

如果要生成提案：

```text
请基于当前 notes 生成标签体系提案和审计报告，告诉我哪些标签可能重复、哪些标签过细、哪些标签值得保留。不要写回 Zotero。
```

## 11. 生成理论/方法/主题综述

```text
请基于已生成的新版 notes，为“金融传染”生成一份理论综述入口。只使用 notes 中已有证据，不重读 PDF，不写回 Zotero。完成后告诉我综述文件路径，以及当前证据不足的地方。
```

方法综述示例：

```text
请基于已生成的新版 notes，为“DCC-GARCH”生成方法综述，重点整理它服务哪些研究主题、常见变量和主要发现。
```

## 12. 数据安全检查

```text
请在提交前帮我做 MindCite 安全检查。运行 safety_scan、structure_check、validate_data_contracts 和 smoke_test。确认没有 .env、真实 notes、indexes、logs、PDF、Zotero 数据库或 API key 会被提交。
```

## 13. 常见故障排查

Zotero 路径错误：

```text
Codex，MindCite 报 No readable Zotero database found。请只读探测我的 Zotero 数据库位置，检查 .env 的 ZOTERO_DB_PATH 和 ZOTERO_STORAGE_PATH，并告诉我应该怎么改。
```

没有 PDF：

```text
请统计当前索引中 missing_pdf_items 和 needs_pdf 条目，按 Zotero collection 或主题汇总，告诉我应该优先补哪些 PDF。
```

分类太乱：

```text
请根据 zotero_index_meta.json 和 zotero_library_index.jsonl，汇总 fallback 待分类条目最多的来源路径，例如 EBSCO、Scopus、SavedRecs、Metadata，并给我一个治理顺序。
```
