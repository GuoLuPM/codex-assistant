# 网页交流工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 主代理持续完成有关联的任务；确有独立收益才按项目规则派发有界协助，不为每个步骤新开代理。

**Goal:** 在每位用户自己的 Windows 电脑上，提供一个能自然对话、展示图文、直接操作并交付真实成果的网页助手，保留 Codex 的通用办事能力。

**Architecture:** 网页通过本地服务连接 Codex，模型负责理解和工具使用；明确按钮操作直接进入共用业务执行。保留现有产品池、证据核验与 PPT 引擎，增加会话连接、任务恢复和受校验的图文展示；首版先验证能力接入，再实现产品主流程和一个非产品任务。

**Tech Stack:** Python、FastAPI / ASGI、Codex App Server 的 stdio 连接、React / TypeScript / Vite、SQLite；Python unittest、前端 Vitest 和 Playwright。优先评估官方 Python SDK 作为连接器，在 Task 1 确认所用实现与精确版本。所有新依赖在引入时固定版本、记录许可证；不把当前开发机版本当通用安装路径。

**Spec:** [设计与价值评估](../specs/2026-10-02-local-workspace-design.md)。本计划是下一步执行依据，复用其中已确认的每人本机使用范围；本轮只写计划，所有实现项尚未开始。

## Global Constraints

- “正常 / 低消耗档、普通速度、来源准确、最终只交付一份业务成品的原则继续保留。”正常为最新可用 Sol / Terra，低消耗为 Terra / Luna；不使用 Astra 或快速模式，不静默替换型号。
- “产品与选择继续以现有业务数据库为真值”；模型文字、浏览器缓存和任务摘要不能替代数据库与实际成品核验。
- “数据存本机不代表模型在本机推理”；账号与密钥由正式登录链路管理，不传给网页或公开分享服务。
- “不通过删证据、降验证、限制用户自由表达获得表面节省。”价格角色、预算、未知值、来源及图片校验继续执行。
- “22px 为正文起点，主要点击目标至少 44px”；详情默认收起，局部更新保留输入、焦点、滚动与勾选。
- “用户照常说话，不必先选‘入库 / 检索 / 智能分析’等模式。”固定控件辅助沟通，开放需求仍由 Codex 理解。
- 只监听本机 loopback；从 Codex 启动与授权。不承诺识别浏览器必须来自 Codex；外网分享仍为独立只读快照。
- 保留 CLI 兼容入口；工作台运行期间，同一正式池的所有写入经过同一个 owner。测试使用隔离合成资料，不能改真实库或现有成品。
- 根入口保持轻量。新包只携带代码、静态界面和经审计的依赖，私有状态统一放 `data/`；不重写第二套模型规划器。

## Review Focus

1. 页面在等待用户回答或授权时刷新：恢复同一请求，不丢问题、不自动同意、不重复发起任务。Task 2 / 5。
2. 用户连点生成、追加需求后立刻停止：只有一次业务效果，取消状态不能冒充回滚或成功。Task 2 / 3 / 6。
3. 中文输入法、大字体、长商品名和流式回答同时出现：输入不被提交或覆盖，价格和主要按钮可读可用。Task 5。
4. 账号退出、额度不足或模型不可用：准确显示原因，保留输入和已选项，不悄悄切模型或一直假装处理。Task 1 / 5。
5. 旧卡片对应的来源、价格或修订已变化：停止旧状态执行，说明需要核对；不让已展示的旧价被无声替换。Task 3 / 4 / 6。

## 交付阶段与文件边界

| 阶段 | 任务 | 独立交付与继续条件 |
| --- | --- | --- |
| P0 连接验证 | Task 1 | 真实验证 Codex 会话、工具、图像、PPT 和非产品任务；关键能力不通就记录证据并重新评估，不继续建完整页面 |
| P1 完整工作台 | Task 2—7 | 同一网页完成交流、选品、成品；恢复和准确性通过，取得消耗对照数据 |
| P2 可选朗读 | Task 8 | 有合适本机语音才启用，文字工作台不依赖它；连续语音对话暂不进入本计划 |
| 交付 | Task 9 | 新 Windows 安装验收、帮助文档、私有数据检查通过后再发布 |

新增代码集中在 `workspace_tool/`：`runtime.py` 对接 Codex，`tasks.py` 管任务与事件，`app.py` / `auth.py` / `uploads.py` 管本地 HTTP 边界，`pool_adapter.py` / `mcp.py` 连接现有能力，`views.py` 生成展示投影；`web/` 放前端与前端测试，`tests/` 放 Python 测试。数据仍由各业务模块管理，不另建一套商品库。

对现有模块只做必要接缝：`catalog_tool/pool.py` 保留 CLI，新增 `pool_commands.py` 与 `pool_owner.py` 收口执行和写入归属；选择事务与幂等回执仍放 `pool_selection.py` 等业务 owner。`present.py` / `run.ps1` 继续唯一负责 PPT 管线。若实施发现不同拆分更小且合同不变，先在本计划记清调整。

本计划不创建独立模型路由服务、用户体系、云数据库或多代理控制台。语音输入、全天候监听、多用户与完整 EXE 分别在有明确需求后规划。

## 共用接口约定

下列是待实现接口；统一使用现项目的 snake_case JSON，协议版本为 `1`。

- `TaskSnapshot`：`task_id, revision, state, thread_id?, active_turn_id?, pending_requests[], blocks[], artifact_ids[], last_event_seq`。state 为 `ready / running / awaiting_user / interrupted / completed / failed`。问答结束后可回 ready；只有业务核验回执能进入 completed。
- `UiEvent`：`task_id, seq, type, revision, data`。持久事件 seq 单调；恢复读取快照后续接事件，不能因重连重发 turn。usage / 流式文本聚合入相应项，不全量重绘页面。
- `ClientAction`：`request_id, task_id, expected_revision, kind, payload`。Task 2 管幂等接收；有业务效果的操作由业务 owner 在提交效果时写同事务回执。
- `TurnRequest`：`task_id, text, input_ids, model_profile`。上传返回的 input_id 映射到任务内文件，不接受网页传任意绝对路径。
- `RuntimeEvent`：`kind, thread_id, turn_id?, item_id?, request_id?, payload`；原生未知事件保留诊断，未知需回答请求显式失败，不能自动批准。
- `ViewRequest`：`kind, refs, caption?`；kind 为 `text / question / progress / products / comparison / artifact`。商品、价格、进度和成品由 refs 解析，caption 是模型解释，不能覆盖来源字段。question 绑定原生待答请求。
- `PoolResult` 保持既有业务 JSON 内容；`OperationReceipt` 包含 `operation_id, payload_hash, state, result_ref`。成功业务提交与 completed 回执同事务，记录在所属业务库；TaskStore 只保存它的引用。
- `InputRef` 包含 `input_id, display_name, sha256, media_type`；`JobRef` 包含 `job_id, task_id, state`；`ArtifactRef` 包含 `artifact_id, task_id, display_name, sha256, verification_ref`。本地路径只由后端管理。`ActionReceipt`、事件和引用结构以 `workspace_tool/tasks.py` 为定义入口；业务 OperationReceipt 由 `pool_commands.py` 定义，引用时不复制字段合同。

最小网页 API：`POST /api/tasks`，`GET /api/tasks/{id}`，`GET /api/tasks/{id}/events`，`POST /api/tasks/{id}/messages`，`POST /api/tasks/{id}/actions`，`POST /api/tasks/{id}/inputs`，`GET /api/artifacts/{id}`；登录交换使用 `POST /api/bootstrap`。所有资源验证当前本地会话和任务归属。

## Task 1：验证 Codex 连接与完整能力

**Files:** Create `workspace_tool/__init__.py`、`workspace_tool/runtime.py`、`workspace_tool/requirements.txt`、`workspace_tool/tests/test_runtime.py`、`scripts/check_workspace_runtime.py`；Modify `docs/AGENT_WORKFLOW.md` 的实际档位探测说明（只在接入验证完成后）。

**Interfaces:** `CodexRuntime.start(config) -> RuntimeCapabilities`，`start_thread(cwd, profile) -> str`，`resume_thread(thread_id)`，`start_turn(TurnRequest) -> str`，`answer(request_id, answer)`，`interrupt(thread_id, turn_id)`，`events() -> AsyncIterator[RuntimeEvent]`，`close()`。`RuntimeCapabilities` 返回版本、实际模型目录、支持的事件与工具可见性，不返回令牌。只选择一个受测连接实现，优先官方 SDK；缺必需事件时明确选 stdio 适配器，不做隐形运行时切换。

- [ ] 写 `test_runtime.py`：initialize 必须先完成；请求 ID 对应正确；failed / interrupted 不映射成功；未知审批不自动批准；登录 / 额度错误显式返回；关闭时结束所拥有子进程；stderr 不混入 JSON 协议。
- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -p test_runtime.py -v`，先看到缺少接口的失败，再实现最小连接并运行至通过。模拟协议只验证协议行为，不能替代真模型验收。
- [ ] 实现 `check_workspace_runtime.py --work-dir <空的私有目录>`，用普通速度受测 Sol 完成中文多轮、打断、追问、恢复、真实图像读取和工具执行。P0 复用现有 CLI 与选择页验证接缝，不提前构建完整前端，整页操作在 Task 6 验收。正常 / 低消耗型号从真实可用目录核验，成功推理才记 access_verified；不改全局模型配置。
- [ ] 在合成池完成入库 → 选择 → 实际 PPT，另做一个非产品任务（例如将用户提供的几条信息整理成文本文件）。确认原桌面专有工具、插件及 Presentations 组件哪些可用；不从另一个桌面聊天偷取会话、账号或权限。
- [ ] 保存私有检查证据，公共文档只写版本与通用限制。关键能力全部可维护地接入才进入 Task 2；否则给出具体缺项和已可用范围。通过后提交该任务代码。

## Task 2：任务、事件和恢复

**Files:** Create `workspace_tool/tasks.py`、`workspace_tool/auth.py`、`workspace_tool/app.py`、`workspace_tool/tests/test_tasks.py`、`workspace_tool/tests/test_http_boundary.py`。

**Interfaces:** `TaskStore.create() -> TaskSnapshot`，`snapshot(task_id)`，`accept_action(ClientAction) -> ActionReceipt`，`append_event(task_id, event) -> UiEvent`，`events_after(task_id, seq)`，`reconcile(task_id, effect_receipts)`。运行记录位于 `data/workspace/workspace.sqlite3`；`ActionReceipt` 含 request_id、accepted / pending / completed / failed 状态和业务回执引用。

- [ ] 测试同 request_id 重试返回同一接受回执；旧 revision 返回冲突；刷新后恢复同一 pending request；重放事件不重复文本；原生回合结束且无业务成品时不能标 completed。示例关键断言：

  ```python
  self.assertEqual(store.accept_action(action).request_id, action.request_id)
  self.assertEqual(store.accept_action(action), store.accept_action(action))
  self.assertNotEqual(store.snapshot(task_id).state, 'completed')
  ```

- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -p test_tasks.py -v`，观察失败，再实现状态机与事件游标。每任务至多一个活动 turn；已有回合时用实际支持的 steer 或显式排队，不悄悄开第二个代理。
- [ ] 实现同源 HTTP / SSE 与一次性启动凭据交换。HTTP 边界测试拒绝错误 Host / Origin、无会话、过期凭据和跨任务资源；启动凭据交换后从地址清除，日志不含凭据。SSE 断开不取消任务或重启回合。
- [ ] 请求答案和批准始终绑定原始 request / turn ID；过期回答返回明确冲突。停止发出中断请求并保留已提交效果；直到实际确认才显示已停止，不能承诺撤销。
- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -v`；用服务重启模拟恢复，不重新执行未知效果的请求。通过后提交。

## Task 3：共用业务入口、写入归属和幂等

**Files:** Create `catalog_tool/pool_commands.py`、`catalog_tool/pool_owner.py`、`workspace_tool/pool_adapter.py`、`workspace_tool/tests/test_pool_adapter.py`；Modify `catalog_tool/pool.py`、`catalog_tool/pool_selection.py`、`catalog_tool/pool_server.py`；扩展相应现有业务测试。

**Interfaces:** `execute_pool(command, params, context) -> PoolResult` 收口原 CLI 分支；`PoolOwner.submit(operation) -> OperationReceipt` 统一排队；`PoolAdapter.execute(task_id, command, payload, request_id) -> PoolResult` 将 input / session / artifact 引用解析到领域操作。`context` 包含池根目录与任务暂存目录；网页及模型工具不能选择任意池路径或运行时路径。

- [ ] 先测试原 CLI 与新适配器对同一合成输入得到相同事实；改名重复文件仍只入库一次，原预算和价格口径不变，未知价格不变成零。运行 `python -m unittest discover -s workspace_tool/tests -p test_pool_adapter.py -v` 观察新接口失败。
- [ ] 最小提取 pool.py 已有业务编排，参数校验沿用现合同；不要复制解析 / 检索逻辑或新增品牌 / 文件名分支。写入线程拥有自己的 SQLite 连接，长解析与 PPT 进程不占据写事务。
- [ ] 统一 owner 锁：服务运行时，CLI 与模型工具写入通过同一 owner；旧选择页也需调用同入口或在启动前明确迁入。服务不存在时的单次 CLI 拿同一互斥锁后执行；失效锁需核验进程和身份，不靠删锁后直写兜底。测试 CLI / 旧页并发不能绕过。
- [ ] `Selections.create(..., operation_id=None)` 增加兼容的可选幂等参数；业务写入以 request_id + 载荷摘要在同事务保存效果回执。相同 ID、不同内容拒绝。梳理原领域方法的事务边界，不能只在外面套事务就假设内部提交也原子。故障注入测试“效果提交后响应丢失”可以找回结果。跨工作台 DB 的恢复通过领域回执对账，不宣称分布式原子提交。
- [ ] 校验 stale revision / sealed / closed、来源撤回或修改、图片变化、连续勾选保存；旧状态拒绝执行。重跑 workspace 测试与 `python -m unittest discover -s catalog_tool/tests -v`，通过后提交。

## Task 4：图文展示与安全动作合同

**Files:** Create `workspace_tool/views.py`、`workspace_tool/mcp.py`、`workspace_tool/tests/test_views.py`、`workspace_tool/tests/test_mcp_contract.py`。

**Interfaces:** `build_view(task_id, ViewRequest) -> UiBlock`；UiBlock 具有 `block_id, kind, revision, body, actions[]`，action 只有注册的 action_id 与允许的资源引用。`capabilities.find(query, limit=5)`、`capabilities.describe(id)`、`capabilities.call(id, payload, request_id)`、`ui.present(ViewRequest)` 为薄工具合同，复用 tools.json 的能力发现，不再维护第二份能力目录。

- [ ] 写测试：产品 card 和 comparison 从冻结 session refs 读取价图；模型 caption 不能注入或覆盖商品数据；跨任务 refs、任意 shell action、未知 block、HTML / 脚本注入均拒绝或作为普通文本展示。来源片段中的“指令”不能变成动作。
- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -p test_views.py -v` 观察失败；实现固定展示器：短文字、问题、阶段进度、商品、对比、成品。对比最多 4 款；同一候选批次价格角色一致，缺少属性显示未知，推荐理由与原事实分开。
- [ ] 普通回复用原生流式文字；只有展示能帮助理解或选择时才调用 ui.present。progress 来自任务事件，artifact 来自已验证成品回执，模型不能提交假百分比或不存在的文件。问答按钮绑定原生待答问题，不建立关键词意图分类器。
- [ ] MCP 调用走 Task 3 的同一服务，声明真实读写性质与副作用；默认只暴露短目录 / 合同，完整说明和图片按 refs 获取。批准由既有服务权限和原生请求决定，不能因为是模型调用而跳过。
- [ ] 运行 views / MCP 合同测试；核对原资料字节和数据库记录无变化。通过后提交。

## Task 5：自然、清楚的网页对话

**Files:** Create `workspace_tool/web/package.json`、锁文件、`vite.config.ts`、`index.html`、`src/App.tsx`、`src/state.ts`、`src/components/Conversation.tsx`、`Composer.tsx`、`RichBlock.tsx`、`ProductPicker.tsx`、`src/styles.css`、`tests/conversation.test.tsx`、`tests/workspace.spec.ts`。

**Interfaces:** `apply_event(state, UiEvent) -> state` 按 task / item / block ID 局部更新；`send_action(ClientAction)` 处理明确操作，`send_message(TurnRequest)` 才启动语义回合。`ProductPicker` 将已保存 revision 与当前用户勾选分别维护，不能以模型回复覆盖它们。

- [ ] 写前端行为测试：流式追加不会重建输入框；IME composing 的 Enter 不发送；用户向上阅读时不强制滚到底部；刷新恢复 pending question；断线不清空输入和选择；快速勾选只接受最新合法修订。
- [ ] 运行 `npm --prefix workspace_tool/web run test -- --run`，确认关键行为测试先失败，再实现对话 / 最近任务 / 输入区。首屏文案“今天想让我帮您做什么？”，只有当前需要的卡片和动作出现；所有功能保留自由输入路径。
- [ ] 状态使用简短口语：明确阶段才说“正在整理这份资料”；需要判断时问一个关键问题；已核验后才说“图册做好了”。额度或登录问题显示真实下一步，不自动切模型；用阶段状态代替编造进度。
- [ ] 完成基于同一组件的商品展开、少量对比、问题选项、成品卡片。全局正文默认 22px，可调；主控件至少 44px。减少动效偏好生效；屏幕阅读只播报阶段变化，不逐 token 播报；来源图片缺失时用自然文字布局。
- [ ] 运行组件测试与 `npm --prefix workspace_tool/web run test:e2e`。检查 Edge 桌面、390px 窄屏、200% 字体、长中文名、键盘、IME、滚动、焦点与勾选无闪烁。测试启动的浏览器 / 服务显式关闭；通过后提交。

## Task 6：资料到成品与一个通用任务闭环

**Files:** Create `workspace_tool/uploads.py`、`workspace_tool/artifacts.py`、`workspace_tool/tests/test_workflow.py`；Modify `workspace_tool/app.py`、`workspace_tool/pool_adapter.py`，必要时只扩展 `catalog_tool/present.py` 的结果适配，不新建 PPT 管线。

**Interfaces:** `accept_upload(task_id, stream, name) -> InputRef`，`export_selection(task_id, session_id, expected_revision, request_id) -> JobRef`，`publish_artifact(task_id, staged_path, verification) -> ArtifactRef`。ArtifactRef 含不透明 ID、展示名、内容哈希和验证回执；下载端点不接受客户端路径。

- [ ] 写 workflow 测试：重复上传不重复入库；部分解析仍明确未完成；双击导出返回同 JobRef；生成等待最后一次勾选保存；空选或旧修订拒绝。测试旧成品字节在失败后不变：`self.assertEqual(old_bytes, final_path.read_bytes())`。
- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -p test_workflow.py -v` 先失败；实现流式上传 / 文件大小上限 / 类型验证 / 解压预算。限制值由配置返回给页面，拒绝时保留用户任务；不要把整份二进制塞进模型消息。
- [ ] 按现有 add / inspect / import / retrieve 合同处理未知格式；返回 needs_mapping 或 partial 时交 Codex 继续有界核对。既有格式自动完成不新建多余模型回合。
- [ ] 生成调用原管线，显式 output 为 `outputs/workspace/<task_id>/产品图册.pptx`；对最终来源、图片、价格和选中项验证后发布唯一 artifact。停止不会抹掉已提交数据；重新导出仍要做新鲜度核验。分享复用独立 PublicView / ShareManager，永不把工作台 API 接入隧道。
- [ ] 用隔离合成资料跑完整页面和真实 PPT，再通过同一输入框完成一个文本整理任务。网页不能要求用户回原聊天完成产品主流程；如果宿主能力不足，记录未通过。通过业务 / 浏览器检查后提交。

## Task 7：消耗对照与口语体验验证

**Files:** Create `scripts/evaluate_workspace.py`、`workspace_tool/tests/test_usage.py`；Modify `workspace_tool/tasks.py` 的 usage 汇总；评测日志仅放 `data/workspace-evaluation/`。

**Interfaces:** `record_usage(thread_id, turn_id, usage_event)` 幂等记录原始输入 / 缓存输入 / 输出等计数；`evaluate_workspace(...)-> EvaluationResult` 同时返回真实产物、正确性、操作数、耗时和可用 usage。缺统计记 unknown，不能按字数估算。

- [ ] 写测试：重放 usage 不重复计数；推理 token 不重复加到已经包含它的输出；usage 缺失不是零；失败后的恢复调用计入任务总消耗。
- [ ] 运行 `python -m unittest discover -s workspace_tool/tests -p test_usage.py -v` 观察失败，实现记录至通过。确定性 UI 行为验证模型调用数不增加：`self.assertEqual(model_calls_after, model_calls_before)`。
- [ ] 固定输入和模型配置，对比原流程与新工作台：重复文件、异形报价、抽象礼品、换一批、改选生成、失败恢复、上次任务、非产品任务；保留未参与设计的改写需求。不能给新方案额外提供答案或已选 ID。
- [ ] 主代理模拟普通用户，以普通速度 Sol 和 Terra 做有限口语演练：“这个不要了”“帮我接着弄”“我没看懂”“页面没反应了”。按实际工具、状态与产物判断，关注是否沿用条件、问必要问题、准确报告失败。一次明确反馈后仍失败则记录原因，不围绕句子堆规则；不预设必须再跑一轮模型。
- [ ] 输出私有对照数据与简短结论。正确性不退步、主要流程不切窗口、确定性点击零模型回合为硬条件；token 总量无明显改善时如实记录，用户体验有提升仍可讨论保留。通过后提交评测入口，不提交真实资料或会话。

## Task 8：可选“读给我听”

**Files:** Create `workspace_tool/web/src/speech.ts`、`workspace_tool/web/tests/speech.test.ts`；Modify `Conversation.tsx` 的可选朗读控件。不新增语音模型服务。

**Interfaces:** `get_read_aloud_capability() -> {available, reason?, voice_id?}`，`read_aloud(final_text)`，`stop_reading()`。默认关闭，由用户点“读给我听”开始，只朗读眼前已完成且适合朗读的文字。

- [ ] 测试初次打开零播放、声音目录延迟加载、无中文本机声音、连续点读只保留一个播放、停止 / 切换任务立即结束。没有合适声音时不能自动选远程声音。
- [ ] 运行 `npm --prefix workspace_tool/web run test -- --run tests/speech.test.ts` 先失败，再实现浏览器能力探测与控制。使用 localService 信息并实际离线试听验证；无法验证时不称离线可用。
- [ ] 不朗读推理日志、未完成 token 流或尚未核验的报价；不为口播改写再调用模型。麦克风与自动播放都保持关闭；语音失败不影响文字和选择。
- [ ] 在受测 Windows / Edge 中人工试听中文、数字与暂停效果，记录支持范围。效果不清楚则保留文字版，不让语音阻塞 P1 交付；通过后提交。

## Task 9：安装、入口、文档与发布

**Files:** Create `workspace_tool/cli.py`、`workspace_tool/WORKFLOW.md`、`workspace_tool/tests/test_launcher.py`；Modify `tools.json`、`tests/test_assistant.py`、`.gitignore`、`scripts/build_windows_bundle.py`、`scripts/install_windows.py`、`scripts/configure_windows.py`、`scripts/check_windows_deployment.py`、`packaging/windows-lock.json`、`.github/workflows/check.yml`、`docs/WINDOWS_RELEASE.md`、`docs/USER_GUIDE.html`、`docs/USER_SERVICE.md`、`docs/ARCHITECTURE.md` 及受影响 pool 指南。

**Interfaces:** `assistant.ps1 run workspace open` 启动 / 复用本机服务，返回 URL 和实际 readiness；`status` 返回依赖、任务状态与已核验范围；`stop` 尊重活动任务与分享，不按关闭页面直接杀进程。未通过 readiness 不宣称完整部署。

- [ ] 写启动测试：重复 open 只启动一个 owner；进程关闭不残留子进程；已有安装版本与业务数据不被覆盖；新运行时缺项准确暴露。注册新能力仍使用现有 tools.json 五字段合同，assistant.py 不导入 Web 依赖。
- [ ] 前端源码和锁文件进 Git，`workspace_tool/web/dist/` 加 ignore。构建器在临时区从受测提交安装锁定依赖并构建静态文件，纳入 bundle 哈希；用户机器不跑前端构建。审核新增依赖、Codex 运行时来源及再分发许可，不复制桌面专有资源。
- [ ] 扩展部署检查，在新的空目录检查账号连接、文件入库、选品与实际 PPT；更新保留旧数据与旧程序回退方式，业务 schema 迁移必须有显式版本和验证。旧包的“base_ready”不等于新工作台 ready。
- [ ] 更新原来的唯一大字手册：上传、聊天、勾选、做成图册在同页完成；不再要求回另一窗口说“选好了”。帮助仍按需给，网页首版缺的功能明确标注，不能先把指南写成已完成。
- [ ] 运行共享、catalog 和 workspace 测试，前端行为测试与浏览器检查；在 Windows 实测 PPT，在 Linux 检查可移植部分。完成 `python scripts/audit_public.py`、安装包哈希及干净新目录验收后，按已有发布授权同步代码和 Release。只交付一个安装附件与现有使用手册，不额外堆用户报告。

## 执行与复核方式

建议主代理按依赖持续实现，P0 先形成真实证据；Task 4 / 5 的界面工作只有在接口冻结后才适合有界协助。使用子代理时按 docs/AGENT_WORKFLOW.md 核对普通速度与实际型号；无需为每个小步骤启动新上下文。完成主要链路后做一次独立复核，重点看能力缺失、状态恢复、来源准确与确定性按钮是否仍触发模型。

每个任务通过自己的必要检查后提交小变更；不要为了方便把同时发生的无关更改带入。执行中的新发现写回本计划对应任务，不另起一套矛盾的规则或多份用户手册。

### 本计划自查

- [x] 覆盖“网页沟通、图文表达、开放需求、产品闭环、token、恢复、分享、部署”；可选朗读单列，连续语音明确后续范围。
- [x] 分清待实现能力与现有能力，P0 不用协议模拟通过冒充真实宿主工具可用。
- [x] 统一 task / turn / request / revision / refs 合同；五个 Review Focus 均有任务中的行为验收。
- [x] 优先复用业务代码；不增加语义关键词路由、多模型常驻编排或任意代码网页渲染。
- [x] 只有计划和设计文档发生变化，尚未运行模型实验、修改正式库、启动新服务或发布新版。
