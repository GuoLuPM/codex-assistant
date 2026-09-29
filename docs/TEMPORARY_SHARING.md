# 临时分享：Codex 按需读取

在 Windows x64 选品页点击分享图标，只打开设置。先设有效时间，再点“确认分享”生成本页全部候选的只读链接。默认“永久”；可直接填写“永久”或点快捷选项，也可填 1—8760 的整数小时（允许带“小时”后缀），用加减按钮或键盘上下键调整。关闭弹窗不停止已生成的分享，点击“停止分享”才撤销。用户勾选仍留在本机，最终由 Codex 导出 PPT。

## 使用边界

- 使用 Cloudflare Quick Tunnel，无需账号、域名或本机公网 IP。“永久”仅表示本程序不设到期时间，电脑、网络和本地服务需要持续运行；重启不恢复旧链接。封存选择/导出 PPT 后，有效分享继续；`close --session`、停止分享或退出服务会撤销。
- 链接对应本次冻结的候选及展示价，后续入库和改选不改变分享内容。价格口径先由 Codex 在 `choose` 时确定；未知信息不补造。
- 收件人只能看商品名称、型号/规格、说明、展示价和图片，不能勾选、下载数据库或请求 PPT。页面上的说明原文也会分享，Codex 需先确认候选页适合发给客户。
- 链接持有人均可访问和转发；未提供账号、验证码或访问人身份管理。停止阻止后续读取，无法收回已查看或保存的内容。
- 只有用户点击“确认分享”或明确要求才启动分享；打开弹窗、改数字、点“设为永久”都不启动。开发/验收使用合成数据，不能自动公开真实产品池。

## 实现合同

`pool_server` 保持本机 Host/Origin/令牌校验。`pool_share_view` 仅接收冻结状态，按允许字段创建随机公共 ID 和独立路径令牌，图片限制在池的 `assets/` 内并快照到内存（合计最多 64 MiB；PNG/JPEG/WebP/GIF）。超限明确失败。

`pool_share` 为该快照创建独立 loopback 服务；仅页面、状态、探测和图片可读，写入方法统一拒绝，未知路径拒绝。这个端口没有数据库连接和管理能力，绝不能把 Cloudflare 直接指向本机选品端口。

本机协议 `server_version=3`。`POST share/start` 仅接受 `{"minutes":null}`（永久）或 1—525600 的整数分钟；0、布尔、浮点、字符串均拒绝，非法值不能悄悄变成永久。网页把整小时转成分钟。ready 返回 `minutes` 与 `expires_at`；永久时两者为 null，定时分享从验证成功开始计时。分享中不修改期限，先停止再设置并确认。旧已生成链接保留原期限。

`pool_tunnel` 启动已校验的 cloudflared；公开 HTTPS 探测必须返回本次随机 share_id，才显示链接。重复启动复用当前分享。停止先撤销快照，再回收隧道和监听服务；到期及子进程异常也撤销。Windows Job 在主服务被终止时回收其隧道进程。公开响应不缓存，来源文本按纯文本渲染。

启动使用官方 `--no-prechecks` 省去全面网络诊断（包括当前未用的传输和更新 API）；实际隧道连接、TLS 校验和带 share_id 的外网探测仍执行。旧版实测日志中的这段诊断约耗时 22 秒。准备中网页每 300ms 读取短状态，ready 后降为 2 秒；未确认时不轮询。失败后可按官方 [连接诊断说明](https://developers.cloudflare.com/changelog/post/2026-05-27-cloudflared-connectivity-prechecks/) 单独诊断，不把诊断放到每次分享的关键路径。

## 运行时与网络

- Release 已含 `runtime/share/cloudflared.exe` 和 Apache-2.0 许可证。源代码运行时首次按 `packaging/share-lock.json` 下载到项目私有 `data/share-runtime/<版本>/`；运行前核对 SHA-256。版本更新必须一起更新二进制与许可证锁、跑连接验证。
- 显式组件路径：`ASSISTANT_CLOUDFLARED` → `environment.local.json` 的 `cloudflared`。无显式值时查当前 Python 同级的 `share/cloudflared.exe`，再查私有缓存；配置或哈希错误直接失败。
- 代理：`ASSISTANT_SHARE_PROXY` → 本地配置 `share_proxy` → 系统 HTTPS 代理；仅支持不含账号密码的 HTTP/HTTPS 代理地址。可使用已运行的 `http://127.0.0.1:7890`，不修改全局网络设置。
- 上游 Quick Tunnel 的申请请求不自动使用普通代理环境变量。适配器通过随机路径的本机小型中转，仅把空 POST 转发到固定官方申请接口；没有任意目标转发功能，临时凭据不进入公开状态。下载、申请和可用性探测使用上述代理。
- 隧道流量仍需 cloudflared 能访问 Cloudflare 边缘网络，本实现使用 HTTP/2（出站 TCP 7844）。本机有 7890 代理不等于所有网络都能连通，也不保证收件人的网络可打开。
- 状态依次为 preparing/connecting/checking/ready，失败为 failed，撤销为 stopping/stopped，到期为 expired。只在 ready 返回 URL。失败详情留在该会话私有 `share.log` / `share-error.log`，不要整段贴到上下文或公开仓库。

遇失败：检查本机代理是否存在 → 私有日志最后几条 → 网络出站条件 → 重试合成页面；不得关闭 TLS 校验或自动更改 VPN、防火墙。第三方临时服务无可用性承诺，不作为长期客户门户。官方说明：[Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)、[网络要求](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)。

## 验证

核心：`python -m unittest discover -s catalog_tool/tests -v`，覆盖公开字段/图片边界、拒绝写入与管理路由、Origin、停止/到期/重复启动、失败、封存后的有效期、组件篡改和 Windows 进程回收。发布还需独立合成池的真实外网、复制链接、桌面/手机、无控制台错误、勾选不重建卡片及撤销检查；不要把本机成功写成所有收件人网络均已验证。
