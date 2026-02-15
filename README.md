# hwmonitor-mqtt workspace

此儲存庫是 AI 開發工作區，主要用途是開發 `hwmonitor-core/`。

## 結構

- `.claude/`：AI 協作設定與插件
- `.mcp.json`：MCP server 設定
- `AGENTS.md`：代理規範
- `hwmonitor-core/`：產品程式碼（git submodule）

## 開發流程

先初始化 submodule：

```bash
git submodule update --init --recursive
```

日常開發在 `hwmonitor-core/` 內進行：

```bash
cd hwmonitor-core
```

可在 root 直接操作 submodule：

```bash
git -C hwmonitor-core status
git -C hwmonitor-core pull
```
