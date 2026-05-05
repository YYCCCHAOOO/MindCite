# Codex Setup

## 一句话启动

在 Codex 里新建一个本地工作区，然后直接说：

```text
请从 https://github.com/YYCCCHAOOO/MindCite 拉取仓库，帮我创建一个私有 MindCite Vault。只读连接我的 Zotero，本地配置 .env，不要提交真实论文、API key、indexes、logs 或 notes。
```

Codex 应该做的事情：

1. 克隆公开仓库。
2. 复制 `.env.example` 为 `.env`。
3. 自动探测或询问 `ZOTERO_DB_PATH` 和 `ZOTERO_STORAGE_PATH`。
4. 运行结构检查和 demo smoke test。
5. 用真实 Zotero 只读生成本地索引。
6. 只在用户确认后运行精读，不做 Zotero 写回。

## 推荐打开方式

在 Codex 中把仓库根目录作为工作区打开。Codex 会读取 `AGENTS.md`，并理解默认入口、配置规则和安全边界。

## 新建私有 Vault 快速配置

如果你已经安装好 Git、Python、Zotero 和 Codex，可以让 Codex 执行下面的本地流程：

```powershell
git clone https://github.com/YYCCCHAOOO/MindCite.git MindCite
cd MindCite
Copy-Item .env.example .env
Copy-Item config/mindcite.example.json config/mindcite.json
python -m pip install -r requirements.txt
python tools/structure_check.py
python tools/smoke_test.py
```

然后让 Codex 帮你探测 Zotero：

```text
请帮我只读探测本机 Zotero 数据库和 storage 路径，写入 .env，然后运行 update_zotero_index.py。不要执行任何 --apply。
```

常见 Zotero 路径：

```text
ZOTERO_DB_PATH=D:\Zotero\zotero.sqlite
ZOTERO_STORAGE_PATH=D:\Zotero\storage
```

如果只是测试通路，不想调用任何远程模型：

```powershell
$env:MINDCITE_OFFLINE=1
python _skills/Zotero-Reading-System/scripts/zotero_ai_reading_pipeline.py --next-count 1
Remove-Item Env:\MINDCITE_OFFLINE
```

`MINDCITE_OFFLINE=1` 会让精读流程跳过 LLM 和 embedding API，即使你的 Windows 用户环境变量里已经配置了 API key。

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
- 测试模式可设置 `MINDCITE_OFFLINE=1`，避免意外调用远程模型。
- 公开说明只能基于合成样例或已确认可公开的内容。
- 对话链接和本地会话缓存只用于提炼配置经验，不应作为公开资料。

## 本地配置提示

如果 Codex 报路径不可读，先检查 `.env` 和当前终端工作目录。若要用演示数据，可临时设置：

```powershell
$env:MINDCITE_ROOT=(Resolve-Path .\examples\demo-vault)
```

完成演示后清除：

```powershell
Remove-Item Env:\MINDCITE_ROOT
```
