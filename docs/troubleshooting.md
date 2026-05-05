# Troubleshooting

## `No readable Zotero database found`

原因通常是 `ZOTERO_DB_PATH` 未配置、路径写错、Zotero 数据库被占用，或当前终端没有读取权限。

处理：

1. 检查 `.env` 是否在仓库根目录。
2. 检查 `ZOTERO_DB_PATH` 是否指向 Zotero 本地数据库文件。
3. 如果要真实写回，先关闭 Zotero。
4. 如果只是演示，改用 `examples/demo-vault`。

## `Missing config`

复制配置模板：

```powershell
Copy-Item config/researchvault.example.json config/researchvault.json
```

然后重新运行脚本。

## API key 无效

检查：

- `.env` 中变量名是否拼写正确。
- key 是否为空。
- provider 是否仍可用。
- 网络是否能访问对应 API。

公开仓库中不应该出现真实 key。

## 找不到 PDF 或全文缓存

精读脚本会优先读 Zotero 全文缓存，再回退 PDF。两者都没有时，条目会进入 `needs_pdf` 状态。补齐附件后重新更新索引。

## 中文路径乱码

脚本默认 UTF-8 读写。若 PowerShell 显示异常，可尝试：

```powershell
chcp 65001
```

路径里有空格或中文时，请使用引号包住路径。

## Obsidian 没有显示结果

确认：

- Obsidian 打开的 Vault 是当前仓库或你配置的 `RESEARCHVAULT_ROOT`。
- 笔记确实生成在 `notes/zotero_reading/_papers`。
- Dataview 等插件已由你自己安装。

## 安全扫描失败

先阅读 `tools/safety_scan.py` 输出的 `path` 和 `type`。常见处理：

- 删除误放入仓库的数据库、PDF、日志或真实 notes。
- 把真实 key 移到 `.env`。
- 把个人路径改成环境变量或相对路径。

