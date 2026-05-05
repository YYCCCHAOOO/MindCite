# Security Policy

ResearchVault 的核心安全原则是：公开仓库只保存工具模板，真实研究资产留在本地。

## 不应提交的内容

- `.env` 或任何含真实 API key 的配置文件
- Zotero 本地数据库、数据库快照、数据库备份
- PDF、CAJ、Word、Excel、CSV、Parquet 等原始资料
- 真实精读笔记、真实索引、真实日志
- Codex、Claude、Obsidian 的本地私有状态
- 未发表论文、审稿意见、导师信息、项目合同、个人研究计划

## 发布前检查

```powershell
python tools/safety_scan.py
git status --short
```

如果 `safety_scan.py` 报错，先处理 findings，再提交。

## API key 处理

公开版只允许出现环境变量名，例如 `DEEPSEEK_API_KEY`。真实 key 必须放在 `.env`、系统环境变量或你自己的密钥管理工具中。

## Zotero 写回风险

写回 Zotero 前请：

1. 关闭 Zotero。
2. 备份 Zotero 数据库。
3. 先运行 dry-run 并人工检查输出。
4. 确认无误后再传 `--apply`。

## 报告安全问题

如果你发现仓库中误包含敏感信息，请立即删除公开提交、轮换相关密钥，并在 issue 或私下渠道说明受影响文件。

