# workspace · 本机网页助手

用户希望在一个页面里聊天、加资料、挑商品和拿成品时使用。先 `./assistant.ps1 run workspace open`，再用 Codex 的打开网页工具打开返回 URL。URL 带一次性启动凭据，不转发、不保存到公开文档；网页打开后会清除。服务只监听本机，关闭网页不停止正在做的事。

## 接待

用户直接说要办什么。页面只在需要时出现资料、商品、问题和成品。正常档用当前可用最新 Sol；低消耗用最新 Terra，均普通速度；不可用时明确说明，不静默切换。一般无需辅助模型。不要反复解释已显示的信息。

## 产品

`pool` 仍是唯一产品事实与检索能力。先 describe pool，再按其合同 add / inspect / import / retrieve / choose。MCP 调用 `capabilities_call` 的参数：`id="pool"`，`command` 为子命令，`payload.args` 为后面的字符串参数数组。添加资料使用 `payload.input_id`；records、map、plan 直接放 `payload.json` 对应字段，不传磁盘路径。不在任务外另开库，不直接修改数据库。

图片或扫描件通过原生图片工具查看，`observe` 的转录原文放 `payload.text`，适配器创建受限文本引用。观察结果仍标记为视觉转录，不能声称是原文件的结构化事实。

`choose` 后立刻 `ui_present`，kind 为 products，refs 为 `{session_id}`。浏览器勾选保存后点“做成图册”，直接执行同一验证生成器，不消耗模型回合。不要代选；不要要求用户切回别的聊天说“选好了”。对比用 comparison + 同一 session_id 的 1—4 个 ids，保持相同价格口径。来源字段不可由 caption 覆盖。

用户在本工作台聊天里说“选好了，做 PPT”也要接着完成：先 `pool selection --session 会话ID` 读取实际勾选，再 `capabilities_call(id="workspace", command="export", payload={session_id,revision}, request_id=唯一操作ID)`。只能导出该任务已保存的选择，不传或补选商品 ID。响应是生成任务，后台核验后自动展示“保存”；不能把受理当作完成。响应丢失使用同一操作 ID 和相同会话/版本重试。空选择或多个无法确定的会话应明确指出，不猜选品。

## 其他事情与成品

保持 Codex 原生文件与工具能力。通用成品写到本轮开发指令给出的输出目录；只交付一个正式文件。用 `capabilities_call(id="workspace", command="publish", payload={filename}, request_id=唯一操作ID)` 校验文件存在、类型、完整性与任务归属，取得 artifact_id，再 `ui_present(kind="artifact", refs={artifact_id})`。检查文件内容是否满足用户要求仍由 Codex 负责，结构检查不能证明内容正确。

不要把 HTML、脚本、shell 命令或任意路径当作网页动作；ui_present 只接受固定类型与已注册引用。普通回复直接用文字，无需再发相同 text block。原生问题/权限请求由用户在同页回答；模型不得自答批准。

## 新电脑与异常

新电脑先读 [Windows 部署](../docs/WINDOWS_SETUP.md)。需要本机 Codex 已安装登录；优先探测 Codex 提供的实际 CLI 路径，其次已安装的新版本。账号凭据不进入网页。`status` 是连接检查，不等于已实际生成过 PPT；部署必须运行真实图册检查。

`stop` 只关闭本工作台；有活动任务或分享时会明确拒绝，先在页面停止它们。重开恢复任务、文字和选择，未知效果不自动重放。资料/报价变更拒绝旧选择，应重新核对并创建候选。旧成品在生成失败时保留。

网页中的“停止”会中断当前原生回合或正在生成的图册。重启后只根据已提交选择和对应生成任务的验证回执恢复结果，不根据模型口头回复宣布完成。

生成中断或完成后，点“重新挑选”会保留原来的勾选并新建可编辑选择；封存记录仍保留。浏览器对响应丢失的重试使用原操作编号，“停止”还绑定当时的消息/生成任务。重启关闭未知回执并明确请用户核对，不自行重做。连接失败后从 Codex 重新打开，会沿用原产品库和显式指定的 Codex 程序配置。

桌面专属面板/聊天管理工具不继承到独立网页。已连接的通用工具以实际可用为准；不可用时明确说明，不借用其他聊天的私有连接。临时分享仅开放独立只读快照，工作台和 Codex API 不进入公网隧道。

账号和聊天：网页连接运行它的那台电脑上已登录的 Codex，会消耗该账号额度。每项正式任务新建自己的原生会话，后续只恢复这一项；不会接到正在进行的其他聊天。正式会话为了续聊会保留，也可能出现在本机 Codex 列表；若用户自行同步 Codex 会话目录，也可能同步到其其他设备。安装包不含开发者账号、原生会话或产品库。

## 开发与验收（按需）

Python 依赖见 `requirements.txt`。前端用 Node 24、pnpm 11.19.0；`pnpm install --frozen-lockfile` 后运行 `test`、`build`、`test:e2e`。在本机 Windows 用 Edge 检查页面；浏览器测试只用合成资料和模拟模型，不启动 GitHub 虚拟环境。后台测试：`python -m unittest discover -s workspace_tool/tests -v`。

本机已装好 PPT 环境时，设置 `ASSISTANT_TEST_REAL_EXPORT=1`、`ASSISTANT_TEST_PYTHON=开发环境的python.exe` 再运行 `pnpm test:e2e`：连续 12 次实际生成、下载并核对商品/价格/页数，覆盖乱序勾选、重复请求、超时重试、刷新和停止后保留旧成品；仅模型使用替身。测试结果只存 `data/browser-checks/`。选择是商品 ID 集合，保存回执按候选顺序返回，不能把顺序变化当成勾选仍未保存。

真实 Codex 检查用 `scripts/check_workspace_runtime.py --work-dir data/runtime-check` 或 `scripts/evaluate_workspace.py --work-dir data/workspace-evaluation --case help`，会消耗当前账号额度；每次在指定目录下新建独立现场，不连接日常服务。二者共用 `scripts/workspace_rehearsal.py`：强制原生 ephemeral 临时会话、确认原生返回且无 rollout 路径，每回合核对工具清单，只允许该合成任务的四个 MCP 工具，关闭个人插件、桌面/浏览器、shell、记忆和 hooks；不支持或核对失败立即停止。新增真实模型脚本也必须复用这个入口，不能直接实例化普通 CodexRuntime/Workspace 来跑模型。

验收退出前核对临时会话未进入原生历史，结果只写私有 data。临时会话不支持重启恢复，不能把同进程多轮记忆称作持久恢复验收；通用通知案例只验证文本，不验证 shell 写文件。生成核验另用 `scripts/check_windows_deployment.py --workspace --require-pdf --ppt`。正式数据不用于公开测试；不能把模拟模型或连接成功当成全部能力已通过。用原生 usage 计数，未知保持未知；缓存输入不能等同免费，不承诺固定节省比例。

当前文字、图片、固定业务卡片和附件可用；语音朗读未启用。数据输入每份最多 64 MiB，压缩文档展开最多 256 MiB。商品库迁移读部署指南；跨设备不复制 Codex 登录凭据或原生会话。
