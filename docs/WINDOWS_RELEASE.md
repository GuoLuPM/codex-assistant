# 新 Windows 对接：交给 Codex 执行

目标：Windows 10/11 x64，用户已有 Codex；无需预装 Python、Git 或登录 GitHub。默认代码 `D:\code\assistant`，独立 Python 环境 `D:\tools\codex-assistant`。用户只描述需要、提供文件、勾选产品。

## 包里有什么

- 当前公开工程、官方 Python 3.13.15 x64、已固定版本的 Excel/Word/PPT 读取与图像依赖、pip、许可证及逐文件 SHA-256 清单。
- PDF 的 PyMuPDF 固定版本由安装器从官方 PyPI 文件地址下载到用户电脑，可使用 HTTP 代理。`-SkipPdf` 可明确跳过，结果会标记 PDF 未安装。
- PPT 导出继续对接这台电脑由 Codex 提供的 Node、artifact-tool 和 Presentations skill。这些专用组件没有重新分发进公开包；首次使用可能需要 Codex 下载自己的运行时。不能说这是完全离线的全功能包。
- 产品数据库、报价文件、账号、API key、旧机器环境路径均不包含。新安装从空产品池开始。

来源：[Python 官方发行及校验值](https://www.python.org/downloads/release/python-31315/)、[PyMuPDF 说明](https://pymupdf.readthedocs.io/en/latest/)。核心依赖的源地址和哈希见 `packaging/windows-lock.json`；各许可证随 Python 与 `.dist-info` 保留。

## 1. 下载和安装

1. 从 [GitHub Releases](https://github.com/GuoLuPM/codex-assistant/releases/latest) 下载名字含 `windows-x64.zip` 的附件；**不是** GitHub 自动生成的 Source code ZIP。下载到 D 盘临时目录，核对 Release 正文 SHA-256，再解压。
2. 网络需要代理时，只给本次下载/安装传 `http://127.0.0.1:7890`。先确认本机代理正在监听；不要修改全局代理、TLS 校验、PATH 或安全设置。PowerShell 下载可用 `Invoke-WebRequest -Proxy`，curl 可用 `--proxy`。
3. 在解压后的 `codex-assistant` 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -Proxy http://127.0.0.1:7890
```

无需代理就省略 `-Proxy`。可用 `-ProjectDir` / `-RuntimeDir` 指定其他**空目录**。没有 D 盘时先说明实际盘符，再选择有空间的位置。`ExecutionPolicy Bypass` 仅用于这一进程，不永久更改执行策略。

安装器验证每个载荷哈希。相同版本重复执行可继续补齐 PDF/PPT 配置；已有数据及保存的本机路径保留，只有显式传入的新路径才替换对应配置。已有配置不可用时报告问题并保留原文件。无安装标记、版本不同或公共代码被修改时停止，不能覆盖旧工程。升级请先核对改动，或安装到新空目录后按迁移文档移动完整私有池。

## 2. 对接这台电脑的 Codex PPT 组件

读安装结果：`base_ready` 只代表 Python/FTS5；`pdf_ready` 表示 PDF 依赖已安装；`ppt_ready` 表示本机 Python、Node、PPT 组件实际加载探测通过，**不等于实际导出已验收**。配置阶段始终返回 `ppt_verified=false`，实际导出由下一步检查确认。

`ppt_ready=false` 时由 Codex 执行：

1. 调用 `load_workspace_dependencies` 获取本机真实的 Node/Python/模块位置；首次调用可能准备运行时。
2. 从当前已安装技能入口定位 Presentations skill，确认其 `container_tools/artifact_tool_utils.mjs` 存在。不要照抄发包机器的用户名/版本号，也不要下载来路不明的专用库。
3. 用真实路径写本地配置；下面两个变量由工具发现结果赋值：

```powershell
$assistantPython = 'D:\tools\codex-assistant\python\python.exe'
& $assistantPython D:\code\assistant\scripts\configure_windows.py `
  --project-dir D:\code\assistant --python $assistantPython `
  --runtime-root $discoveredRuntimeRoot --skill-dir $discoveredPresentationsSkill
```

`environment.local.json` 自动保存此设备配置，之后从任意工作目录调用 `assistant.ps1` 都能读取；无需每次设置环境变量。显式 `ASSISTANT_PYTHON`、`ASSISTANT_RUNTIME_ROOT`、`ASSISTANT_PRESENTATIONS_SKILL` 和单次 CLI 参数仍优先。Codex 管理的运行时留在它自己的目录，不擅自搬动应用缓存。

若组件无法获取，报告具体缺项和可用范围。基础入库/检索仍可用；不要承诺 PPT 已完成部署。

## 3. 验收，不动用户的产品或现有成品

```powershell
Set-Location D:\code\assistant
.\assistant.ps1 doctor
.\assistant.ps1 list --query '产品池'
& D:\tools\codex-assistant\python\python.exe scripts\check_windows_deployment.py --require-pdf --ppt
```

该检查只生成合成商品，验证原价、改名重复入库、预算检索、选择持久化和实际 PPT 管线。合成文件放独立私有目录，成功后清理；失败保留现场并返回路径。不会覆盖用户已有 PPT。`ppt_verified=true` 才能报告实际导出成功。若用户要看效果，另用其真实文件生成选择页，等用户自己勾选。

## 4. 日常使用与私有数据

- 在 Codex 打开 `D:\code\assistant`，先读 `AGENTS.md`，再由入口路由到一个指南。常用入口 `assistant.ps1 run pool`。
- 用户可以说：“这几份报价加进去”“一百以内，适合过年送长辈，别要数码”“给我挑几款，我勾好了再做 PPT”。Codex 拆条件、查依据、显示 HTML；用户只勾选，最终交付一份 PPT。
- 来源、产品池及本地配置留在当前电脑。数据迁移必须私下传完整 `data/product-pool/`；不是下载公开 Release 就有原来的产品。迁移时先停写入和选择服务，步骤见 `docs/WINDOWS_SETUP.md`。
- 新电脑要重新 `open --session ID` 获取本机地址；旧电脑的 `127.0.0.1` 链接不能通用。VPN 7890 只帮助联网，不是远程数据库或远程桌面地址。
- 默认普通速度 GPT-6 Sol；Terra 用于有限核对。无需额外 API key 或独立 agent 服务。

## 发给用户的 Codex 提示词

```text
请在这台 Windows 电脑部署 GuoLuPM/codex-assistant。我已安装 Codex，本机可用的 HTTP 代理是 http://127.0.0.1:7890。

请从 https://github.com/GuoLuPM/codex-assistant/releases/latest 下载 windows-x64.zip 安装附件，核对 Release 正文的 SHA-256，并阅读包内 START-HERE.md。默认工程放 D:\code\assistant，环境放 D:\tools\codex-assistant。不要假设已有 Python、Git 或 GitHub 登录；已有工程和数据先核对，别覆盖。代理只作用于本次下载，未启动时明确告诉我。

按文档安装，并用 Codex 的 load_workspace_dependencies 和本机 Presentations skill 完成 PPT 环境对接。用合成资料跑 check_windows_deployment.py --require-pdf --ppt，实际导出成功后再说已完成；缺什么就继续处理或明确报告，不要猜已装好。公开安装包不含产品数据，有我提供的文件再加入产品池。

以后由你从 Codex 帮我入库和查产品，我只在 HTML 里勾选，选好后再生成一份 PPT。用普通速度的 GPT-6 Sol，不开快速模式。沟通尽量口语化，按项目 AGENTS.md 和按需指南执行。
```
