# 新 Windows 对接：交给 Codex 执行

目标：Windows 10/11 x64，用户已有 Codex；无需预装 Python、Git 或登录 GitHub。默认工程 `D:\code\assistant`，Python 环境、缓存和辅助文件放在工程的 `data/` 内；默认环境为 `data/runtime/`。用户只描述需要、提供文件、勾选产品。

验收在本机运行，不依赖 GitHub 虚拟环境。0.4 已在 Windows 11 实机验证安装、网页与实际 PPT；Windows 10 尚未实机验证，新设备仍须执行本文的验收脚本，不能只凭版本名称承诺通过。

**给用户看：**安装包顶层的 `使用手册.html` 是可直接双击打开的大字版说明。安装后，同一手册位于工程的 `docs/USER_GUIDE.html`。本文是给 Codex 执行的部署步骤；对用户按需打开使用手册，一次带他做一步。

## 先选使用档位

| 档位 | 主负责 | 需要时协助 |
| --- | --- | --- |
| 正常（默认） | 最新 Sol | 最新 Terra |
| 低消耗 | 最新 Terra | 最新 Luna |

每个系列都选这台电脑的 Codex 当前可用最新版，两档均普通速度，不开快速模式、不用 Astra。用户可说“用正常档”或“用低消耗档”；未指定用正常档。安装包不会切换聊天模型，Codex 应核对并在需要时提示用户切换。低消耗不减少数据核验，也不承诺固定节省比例；处理不了时明确说明并建议切正常档，不自动升档。

## 包里有什么

- 当前公开工程、官方 Python 3.13.15 x64、已固定版本的 Excel/Word/PPT 读取、图像和网页服务依赖、已构建的网页、pip、许可证及逐文件 SHA-256 清单。
- 临时分享组件 cloudflared 及 Apache-2.0 许可证也已包含；选品页可生成只读外网链接，使用时需要联网，无需额外账号或域名。
- PDF 的 PyMuPDF 固定版本由安装器从官方 PyPI 文件地址下载到用户电脑，可使用 HTTP 代理。`-SkipPdf` 可明确跳过，结果会标记 PDF 未安装。
- PPT 导出继续对接这台电脑由 Codex 提供的 Node、artifact-tool 和 Presentations skill。这些专用组件没有重新分发进公开包；首次使用可能需要 Codex 下载自己的运行时。不能说这是完全离线的全功能包。
- 产品数据库、报价文件、账号、API key、旧机器环境路径均不包含。新安装从空产品池开始。

来源：[Python 官方发行及校验值](https://www.python.org/downloads/release/python-31315/)、[PyMuPDF 说明](https://pymupdf.readthedocs.io/en/latest/)。核心依赖的源地址和哈希见 `packaging/windows-lock.json`；各许可证随 Python 与 `.dist-info` 保留。

分享组件的官方地址和哈希见 `packaging/share-lock.json`；网络条件及排错仅在需要时读 [临时分享](TEMPORARY_SHARING.md)。包内入口文档解压后的相应路径为 `application/docs/TEMPORARY_SHARING.md`。

## 1. 下载和安装

1. 从 [GitHub Releases](https://github.com/GuoLuPM/codex-assistant/releases/latest) 下载名字含 `windows-x64.zip` 的附件；**不是** GitHub 自动生成的 Source code ZIP。下载到 D 盘临时目录，核对 Release 正文 SHA-256，再解压。
2. 网络需要代理时，只给本次下载/安装传 `http://127.0.0.1:7890`。先确认本机代理正在监听；不要修改全局代理、TLS 校验、PATH 或安全设置。PowerShell 下载可用 `Invoke-WebRequest -Proxy`，curl 可用 `--proxy`。
3. 在解压后的 `codex-assistant` 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -Proxy http://127.0.0.1:7890
```

无需代理就省略 `-Proxy`。`-ProjectDir` 可指定其他**空目录**，默认环境自动跟随到该目录的 `data/runtime/`；一般无需 `-RuntimeDir`。旧安装器（如 0.4.0）仍有外置环境默认值，且不支持内嵌环境：由 Codex 先核对安装器能力，不能照搬新路径参数；旧包安装完成后再按部署指南搬入工程并重新验收。没有 D 盘时先说明实际盘符，再选择有空间的位置。`ExecutionPolicy Bypass` 仅用于这一进程，不永久更改执行策略。

安装器验证每个载荷哈希。相同版本重复执行可继续补齐 PDF/PPT 配置；已有数据及保存的本机路径保留，只有显式传入的新路径才替换对应配置。已有配置不可用时报告问题并保留原文件。无安装标记、版本不同或公共代码被修改时停止，不能覆盖旧工程。升级请先核对改动，或安装到新空目录后按迁移文档移动完整私有池。安装验收后，需要保留的 ZIP 和解压材料收进工程 `data/install/`，不要遗留外部测试目录。

## 2. 对接这台电脑的 Codex PPT 组件

读安装结果：`base_ready` 只代表 Python/FTS5；`pdf_ready` 表示 PDF 依赖已安装；`ppt_ready` 表示本机 Python、Node、PPT 组件实际加载探测通过，**不等于实际导出已验收**。配置阶段始终返回 `ppt_verified=false`，实际导出由下一步检查确认。

`ppt_ready=false` 时由 Codex 执行：

1. 调用 `load_workspace_dependencies` 获取本机真实的 Node/Python/模块位置；首次调用可能准备运行时。
2. 从当前已安装技能入口定位 Presentations skill，确认其 `container_tools/artifact_tool_utils.mjs` 存在。不要照抄发包机器的用户名/版本号，也不要下载来路不明的专用库。
3. 用真实路径写本地配置；下面两个变量由工具发现结果赋值：

```powershell
$assistantPython = 'D:\code\assistant\data\runtime\python\python.exe'
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
& .\data\runtime\python\python.exe scripts\check_windows_deployment.py --workspace --require-pdf --ppt
```

该检查只生成合成商品，验证原价、改名重复入库、预算检索、选择持久化和实际 PPT 管线。合成文件放独立私有目录，成功后清理；失败保留现场并返回路径。不会覆盖用户已有 PPT。`ppt_verified=true` 才能报告实际导出成功。若用户要看效果，另用其真实文件生成选择页，等用户自己勾选。

## 4. 日常使用与私有数据

- 在 Codex 打开 `D:\code\assistant`，先读 `AGENTS.md`，再由入口路由到一个指南。常用入口 `assistant.ps1 run workspace open`；用 Codex 打开工具显示返回 URL。启动链接只用一次，不转发给别人。
- 首次接待或用户不会操作时，读 `docs/USER_SERVICE.md`；需要帮助就打开 `docs/USER_GUIDE.html`。用户明确索要手册时直接给，用户拒绝阅读就继续口头引导，不反复问是否需要帮助。
- 用户可以说：“这几份报价加进去”“一百以内，适合过年送长辈，别要数码”“给我挑几款，我勾好了再做 PPT”。工作台里直接聊天、添加文件、勾选并点“做成图册”，核验完成后下载一个 PPT。
- 来源、产品池及本地配置留在当前电脑。数据迁移必须私下传完整 `data/product-pool/`；不是下载公开 Release 就有原来的产品。迁移时先停写入和选择服务，步骤见 `docs/WINDOWS_SETUP.md`。
- 新电脑要重新 `run workspace open` 获取本机地址；旧电脑的 `127.0.0.1` 链接不能通用。VPN 7890 只帮助联网，不是远程数据库或远程桌面地址。
- 给别人看商品时点击页头分享图标，先设时间、再点“确认分享”。默认“永久”（持续到停止或服务退出），也可输入整数小时并加减调整；电脑保持开机联网，可随时停止。分享本页全部候选及展示价，访客只能看。仅 HTTP 代理并不保证隧道连接，须实测收件人的网络。
- 按用户选择的正常 / 低消耗档分工，辅助模型只做范围明确的工作，主模型负责复核和正式写入。无需额外 API key 或独立 agent 服务。

## 打开工作台

确认 Codex 已安装并登录。运行 `./assistant.ps1 run workspace open`，使用 Codex 的打开网页工具打开返回 URL。页面只访问 127.0.0.1；初次打开会显示连接状态。`workspace status` 返回真实连接与可用型号，`workspace stop` 只关闭本项目拥有的服务。有任务或分享运行时先在页面停止。

`workspace_installed` 只说明依赖和静态页面存在；`workspace_ready` 说明本机 Codex 已连接且正常档可用；`ppt_verified` 才证明实际导出成功。这三项不能互相替代。用户无需安装 Node、pnpm 或配置 API key；Codex 账号由本机 Codex 管理。

网页里选“正常”实际使用当前可用最新 Sol，选“低消耗”实际使用最新 Terra，下一件事生效。都用普通速度；不自动升档，也不自动派发子代理。原来 Codex 聊天里的模型仍由该聊天设置决定。

## 发给用户的 Codex 提示词

```text
请帮我装好并打开 codex-assistant 工作台。
从 https://github.com/GuoLuPM/codex-assistant/releases/latest 下载 windows-x64.zip，核对校验值，按包内 START-HERE.md 完成安装。工程放 D:\code\assistant，环境、缓存和测试文件统一收在这个工程内；旧包若装到外部，安装后搬入 data/runtime 并更新配置、重新验收。已有文件和数据先检查，别覆盖。不要假设我有 Python、Git 或 GitHub 账号。需要代理时先检查本机 7890 端口，仅本次使用。
请对接本机已登录的 Codex 和 PPT 组件，用合成资料通过 check_windows_deployment.py --workspace --require-pdf --ppt，再打开工作台。有缺项继续处理，未通过就如实告诉我。
默认正常档，用最新 Sol、普通速度。以后我在网页里说需求、加资料、勾选商品，直接点“做成图册”下载。其他事情也可以帮我处理；只交付最终文件，不编造数据，不自动公开产品。
请用简单的话带我做，一次只讲眼前一步。我不会用时帮我；想看说明时打开项目里唯一的使用手册。
```
