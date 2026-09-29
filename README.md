# assistant

供 Codex 调用的本地工具库。用户描述需求，Codex 找到能力、读取必要说明并调用脚本。脚本处理确定性工作，完整业务数据留在本机。

新 Windows 可直接下载 [Releases 安装包](https://github.com/GuoLuPM/codex-assistant/releases/latest)，包含独立 Python 和基础依赖；[对接文档与转发提示词](docs/WINDOWS_RELEASE.md) 说明如何接通本机 Codex 的 PPT 组件。

## 选一个使用档位

| 档位 | 主负责 | 需要时协助 |
| --- | --- | --- |
| **正常（默认）** | 最新 Sol | 最新 Terra |
| **低消耗** | 最新 Terra | 最新 Luna |

可以直接说“用正常档”或“用低消耗档”。各系列都选当前 Codex 可用的最新版，两档均不开快速模式，数据核验标准相同。档位不会自动切换聊天模型，Codex 会在需要时提示你切换；低消耗不承诺固定节省比例。执行细则见 [档位与分工](docs/AGENT_WORKFLOW.md)。

## 开始使用

```powershell
./assistant.ps1 list --query '产品池'
./assistant.ps1 describe pool
./assistant.ps1 run pool search --query '耳机' --limit 5
```

当前能力：

- **pool** — 多格式文件持续加入产品池，内容去重，按价格/品类/推荐场景检索，HTML 勾选后生成 PPT；可生成临时只读链接给别人看。读 [产品池短流程](catalog_tool/POOL_WORKFLOW.md)。
- **catalog** — 既有 XLSX 坐标映射、增量检索与图册流程。读 [catalog 短流程](catalog_tool/WORKFLOW.md)。

两者共用检索和生成引擎，默认最终交付一份 `outputs/产品图册.pptx`。业务数据与推荐判断分开保存，完整记录不需要穿过模型上下文。

## 文档按任务加载

| 任务 | 入口 |
| --- | --- |
| Codex 工作规则与路由 | [AGENTS.md](AGENTS.md) |
| 查找工具 | `assistant.ps1 list --query 关键词`；`describe 工具ID` |
| 新设备、运行时、目录迁移 | [WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md) |
| 了解路线评估或接入新能力 | [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 确有必要的子代理分工 | [AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md) |

入口与发现只需 Python 3.11+ 标准库，不读取业务数据；每个工具自行声明依赖。PowerShell 启动器按 `ASSISTANT_PYTHON` → 项目本机配置 → Codex 运行时 Python → PATH Python 选择，显式配置错误直接报错。`doctor` 只检查入口环境，不代表某项工具的依赖齐全。

`data/`、产出、私有映射、索引和本地配置不进 Git。仓库地址：[GuoLuPM/codex-assistant](https://github.com/GuoLuPM/codex-assistant)。本地文件夹可自由命名。
