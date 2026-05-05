# Codex Setup

## 推荐打开方式

在 Codex 中把仓库根目录作为工作区打开。Codex 会读取 `AGENTS.md`，并理解默认入口、配置规则和安全边界。

## 常用指令

```text
更新 Zotero 索引。
```

```text
请精读 Zotero 中 ABC12345。
```

```text
根据已精读笔记，总结金融传染理论的关键机制。
```

```text
运行健康检查，并告诉我 notes 与索引是否同步。
```

```text
生成分类审核队列，但不要写回 Zotero。
```

## 对 Codex 的约束

- 默认只读真实 Zotero 数据库。
- 默认不上传真实研究材料。
- 写回 Zotero 必须显式 `--apply`。
- 公开说明只能基于合成样例或已确认可公开的内容。
- 对话链接和本地会话缓存只用于提炼配置经验，不应作为公开资料。

## 本地配置提示

如果 Codex 报路径不可读，先检查 `.env` 和当前终端工作目录。若要用演示数据，可临时设置：

```powershell
$env:RESEARCHVAULT_ROOT=(Resolve-Path .\examples\demo-vault)
```

完成演示后清除：

```powershell
Remove-Item Env:\RESEARCHVAULT_ROOT
```

