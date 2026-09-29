# Windows 部署与目录迁移

新设备、环境缺失或目录变动时读取。面向 Codex 执行；不需要用户自行掌握命令。项目建议 `D:\code\assistant`，可管理的运行时和缓存放 `D:\tools`。已有 Codex 自带运行时先复用，不强搬应用管理的文件。

## 取得工程

- 新电脑优先使用 [Releases 的 Windows x64 安装包](https://github.com/GuoLuPM/codex-assistant/releases/latest)，包内含 Python、基础依赖、临时分享组件、校验清单及安装器；对接步骤和可转发提示词见 [Windows Release 对接](WINDOWS_RELEASE.md)。PDF 在目标机器下载，PPT 对接目标机器自己的 Codex 组件；分享网络排查读 [临时分享](TEMPORARY_SHARING.md)。

- 公开仓库 `https://github.com/GuoLuPM/codex-assistant`，不需要 GitHub 账号登录。优先 `git clone https://github.com/GuoLuPM/codex-assistant.git D:\code\assistant`。
- 没有 Git：优先找 Codex 随附 Git；也可下载仓库默认分支 ZIP 解压。无 Git 仍可本地运行，公开历史检查与代码同步需要 Git。安装工具时以官方来源和当前设备为准。
- 在 Codex 打开实际项目目录并读根 AGENTS。不要复制旧机器的 node_modules、虚拟环境或临时构建目录；发行包里的环境来自锁定并校验过的官方安装材料。

## 入口与检索环境

入口发现只用 Python 3.11+ 标准库。Windows `assistant.ps1` 的顺序：显式 `ASSISTANT_PYTHON` → 项目 `environment.local.json` 的 python → 指定/本地配置/默认 Codex Runtime 的 Python → PATH Python。显式路径无效就报错，不悄悄换环境。安装器/`scripts/configure_windows.py` 写本机配置，它不进入 Git 或公开包。

配置重试保留用户选择的解释器、运行时和技能路径；不会把 Python 链接转换成底层解释器，以免跨出虚拟环境。入口输出固定为 UTF-8，英文 Windows 也能读取中文工具说明。

```powershell
# 使用 D 盘已有 Python / venv 的示意路径；先核对文件存在
$env:ASSISTANT_PYTHON = 'D:\tools\assistant-venv\Scripts\python.exe'
./assistant.ps1 doctor
& $env:ASSISTANT_PYTHON -m pip install -r catalog_tool/requirements.txt
./assistant.ps1 list
```

如需新建虚拟环境，用已核验的 Python 执行 `-m venv D:\tools\assistant-venv`，pip 缓存可通过 `PIP_CACHE_DIR` 指向 D 盘。`doctor` 返回实际 Python 和项目路径，只表示入口可用。pool/catalog 检索需 SQLite FTS5 与 requirements 中的 Python 依赖；多格式读取使用 PyMuPDF、python-pptx、python-docx、xlrd。选择页使用 Python 标准库 HTTP 服务，无须安装 Web 框架或单独数据库。运行测试验证实际依赖。

## PPT 环境

PPT 使用 Codex 桌面版提供的 Node/Python、`@oai/artifact-tool` 与 Presentations skill。普通 pip 安装不包含完整导出环境。通过 Codex 的 `load_workspace_dependencies` 查实际运行时，再读取当前 Presentations skill 定位；不要照抄另一台电脑的用户名或版本号。

- `ASSISTANT_RUNTIME_ROOT`：含 `python/python.exe`、`node/bin/node.exe`、`node/node_modules`、`bin/override` 的运行时根目录。
- `ASSISTANT_PRESENTATIONS_SKILL`：包含 `container_tools/artifact_tool_utils.mjs` 的 skill 目录。
- 单次也可 `run catalog ppt ... --runtime-root 路径 --skill-dir 路径`。PPT 管线使用这里选中的整套环境；`ASSISTANT_PYTHON` 只决定入口/检索 Python。
- `catalog_tool/node_modules` 是本机 Junction。已有链接若指向另一套运行时会明确报错；核对目标后只修复链接，不删除依赖目标目录。
- 默认从本机用户目录发现 Codex 运行时；没有该环境就报告缺少哪些依赖，不把未核验的文件称作已完成 PPT。

## 私有数据与迁移

### 产品池 pool（持续积累）

新文件放 `data/` 后，按 pool guide 执行 `add`；非 XLSX 或异形表由 Codex 看证据并提供映射/记录。Git 只传代码，不含产品数据库和原件。

迁移已有池：先停止使用中的选择服务与数据库写入，私下复制**整个 `data/product-pool/`**（数据库、objects、assets、sessions）到新项目同一相对目录，再复制必要的本地样式/配置。池内路径相对存储，无须 catalog relocate，产品 ID 保持不变。新机器 `run pool stats`、`show --ids 已知ID` 核验；开放选择会话用 `open --session ID` 取得本机新链接，旧设备的 127.0.0.1 链接不能远程访问。

### 既有 catalog 索引

全新部署将工作簿放 `data/`，复制必要的 `catalog.local.json` / `style.local.json` 与私有映射；这些均不上传。没有旧索引时，首次按 `来源.xlsx --map 映射.local.json` 登记，随后增量复用。

**完整项目改名 / 搬盘 / 迁往新 Windows：**保留来源相对目录、配置与 `.catalog-index`（含数据库和映射）。先迁移注册，再日常 index；不要在旧绝对路径失效时直接把所有来源按自动模式导入。

```powershell
./assistant.ps1 run catalog relocate --from 'E:\code\old-project' --to 'D:\code\assistant'
./assistant.ps1 run catalog relocate --from 'E:\code\old-project' --to 'D:\code\assistant' --apply
./assistant.ps1 run catalog index ./data
./assistant.ps1 run catalog search --query '关键词' --limit 5
```

`--from` 必须来自旧注册路径，而不是猜测；`sources` 可分页观察。第一条只检查并返回最多 10 项计划；`--apply` 在单次数据库事务内重读迁移来源，修复来源、映射、图片路径和产品 ID。哈希或配置变动、目标已注册、缺失文件都会失败，旧登记保留。不会修改或删除原始工作簿。迁移后重新检索，不复用旧 ID。

仅迁移旧根目录下的已登记来源；根目录外的来源/映射需单独保持可访问或另行明确迁移。文件内容也改变时先处理搬迁身份与新版本顺序，不跳过哈希校验。跨操作系统的路径格式转换不在此命令合同内。

## 验收

```powershell
& $env:ASSISTANT_PYTHON -m unittest discover -s tests -v
& $env:ASSISTANT_PYTHON -m unittest discover -s catalog_tool/tests -v
```

再查一条真实记录、核对价格标签与来源；pool 用 `choose/open` 打开选择页，确认勾选持久化后 `ppt --session ...` 导出；catalog 用明确 ID 通过 `ppt --ids ... --price-fields ...` 生成。PPT 环境齐全且视觉抽查后才能说 PPT 已部署成功。已有客户成品时，冒烟产物放私有临时目录并收尾，不替换客户成品。用户日常只收到一个最终文件。
