# assistant

供 Codex 调用的本地工具库。用户描述需求，Codex 找到能力、读取必要说明并调用脚本。脚本处理确定性工作，完整业务数据留在本机。

```powershell
./assistant.ps1 list --query 'xlsx'
./assistant.ps1 describe catalog
./assistant.ps1 run catalog search --query '耳机' --limit 5
```

当前能力：**catalog** — XLSX 有界观察、结构映射、增量检索、选品、生成有来源校验的 PPT。首次使用先读 [短流程](catalog_tool/WORKFLOW.md)，不必通读实现。默认交付一份 `outputs/产品图册.pptx`。

## 文档按任务加载

| 任务 | 入口 |
| --- | --- |
| Codex 工作规则与路由 | [AGENTS.md](AGENTS.md) |
| 查找工具 | `assistant.ps1 list --query 关键词`；`describe 工具ID` |
| 新设备、运行时、目录迁移 | [WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md) |
| 了解路线评估或接入新能力 | [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 确有必要的子代理分工 | [AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md) |

入口与发现只需 Python 3.11+ 标准库，不读取业务数据；每个工具自行声明依赖。PowerShell 启动器按 `ASSISTANT_PYTHON` → Codex 运行时 Python → PATH Python 选择，显式配置错误直接报错。`doctor` 只检查入口环境，不代表某项工具的依赖齐全。

`data/`、产出、私有映射、索引和本地配置不进 Git。仓库地址：[GuoLuPM/codex-assistant](https://github.com/GuoLuPM/codex-assistant)。本地文件夹可自由命名。
