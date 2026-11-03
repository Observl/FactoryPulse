# 部署、运行与备份恢复

本地与目标服务器使用同一套 React 页面和 Python 业务代码，账号及业务数据统一读写 Cloudflare D1。当前 Workers 已部署完整前端、业务读取及原生工单流程；Python CP-SAT 三方案比较、模型训练及企业数据导入等能力仍需计算服务。不能将准备完成的部署配置描述为完整业务已经上线。

## 当前数据服务额度问题（2026-11-03）

用户反馈部署账号Cloudflare额度已用尽，本次未访问控制台核实具体额度类别、剩余量或恢复时间。现有发布记录仅证明发布当时检查通过，不保证当前登录、D1最新读取、业务写入和评审链接可用。静态资源或旧缓存可显示也不证明数据服务已恢复。

正常本地启动同样依赖云端账号和D1，不提供绕过额度的本地业务库回退。隔离测试使用临时SQLite或FakeD1，仅用于验证代码。额度恢复后需核对账号、数据读取和实际业务操作；当前按用户要求不访问云端、不部署。Dify上游503/50508繁忙另行记录，不自动归因于Cloudflare。

最后已核实的Worker服务修复版本为`6ca09696-a84f-440e-9172-381ed79a2de3`，当时原静态资源保持不变；随后本地新前端构建与Python修复未发布。详情见[当前项目说明](../README.md)及[验收交接](PROJECT-HANDOFF-2026-11-03.md)。

## 部署包

- `Dockerfile`：构建完整前端与 Python 服务，使用非 root 用户、单个业务进程。
- `compose.cloud.yaml`：Caddy HTTPS 入口、后端、上传文件及加密配置卷、TLS 证书卷；不使用本地业务数据库。
- `backend/cloud_server.py`：完整云端启动入口，校验构建文件、账号配置和加密主密钥。
- `backend/requirements-cloud.lock.txt`：Linux/Python 3.12 依赖锁，容器构建和启动需通过 CI 验证。
- `.secrets/`：运行凭据，不进入 Git 或容器构建上下文。D1 令牌只由服务器读取。

## 账号中心

目标 D1：`factorypulse_users` / `af5776ef-c7f8-48c7-8f21-1bb36f98061c`。

身份配置文件示例（保存为 `.secrets/identity.json`）：

```json
{
  "account_id": "af8b5dc2fceddfd9316d60164cb2e7e2",
  "database_id": "af5776ef-c7f8-48c7-8f21-1bb36f98061c",
  "token_file": "cloudflare-d1-token"
}
```

令牌写入配置文件同目录的 `cloudflare-d1-token`，不可写入前端、GitHub 公共仓库或日志。Cloudflare 当前账号令牌 UI 的 D1 权限为账号范围；不能将它描述成已限制为单个数据库。必须由所有者授权该范围后才能创建。不要授予其他产品权限。

身份表存入账号 D1；设备、工单、库存、模型证据及业务审计存入业务 D1 `abc7cb74-5be4-49a2-827a-3bd8b639f257`。业务配置保存为 `.secrets/business.json`，格式同上，使用业务库 ID。生产运行禁止本地 SQLite，上传 SQLite/SQL 文件的旧路径已关闭，可使用 CSV/XLSX 导入。D1 不开放匿名 SQL 接口；网站权限与 Cloudflare 控制台权限相互独立。

既有账号表升级运行：

```powershell
.venv\Scripts\python.exe scripts/upgrade-d1-account-schema.py
```

该操作保留有效的数字编号账号及密码，移除 username，修复内部事务表，并在私有目录备份。账号使用从 10001 开始的数字编号登录，不再自动创建默认管理员或访客。用户自行配置账号，密码使用 64 位 SHA-256；角色和人员编号约束见 [账号表规则](CLOUD-DEPLOYMENT.md)。

本地启动前设置：

```powershell
$env:FACTORYPULSE_IDENTITY_CONFIG=(Resolve-Path .secrets/identity.json).Path
```

账号及业务提交使用 D1 原子批处理与版本冲突校验，跨部署冲突返回 409；网络失败返回 503，不回退到本地数据库。查询及事务工作表也在 D1。部署准备读取既有账号配置，不再索取或生成默认管理员密码。

## 服务器启动

服务器需有 Docker Compose，域名 A/AAAA 记录指向服务器，并开放 80/443。将源码和受保护的 `.secrets` 文件分别传到服务器，不上传已有本地业务数据库或浏览器配置。

Linux 上 Compose 的文件型 secrets 可能保留源文件权限。容器业务用户为 UID/GID 10001；上传后由服务器所有者设置 `.secrets` 目录仅自己可进入，机密文件组为 10001、权限 0640，使容器可读取但其他普通用户不可读取。使用 root 所有者部署时可执行：

```sh
sudo chown -R root:10001 .secrets
sudo chmod 0700 .secrets
sudo chmod 0640 .secrets/*
```

此后用 `sudo docker compose` 执行以下启动命令。不要为解决权限问题把机密文件设置为全员可读。

```sh
cp deploy/cloud.env.example deploy/cloud.env
# 编辑 FACTORYPULSE_DOMAIN 为计算服务域名，并设置 BUILD_COMMIT。
# FACTORYPULSE_FRONTEND_ORIGIN 保留实际 Cloudflare 页面来源。
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml up -d --build
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml ps
```

集中账号配置在 Compose 中作为机密挂载；缺少 D1 配置时拒绝启动，禁止使用独立 SQLite 账号库替代。共享访客只能读取，不能提升角色或修改共享密码。

## 更新、备份与回退

更新前停止写入并制作一致性业务备份，再更新镜像；保留 `factorypulse_data` 卷。`docker compose down` 不删除数据，**不要使用 `down -v`**。回退前确认数据库结构兼容，不能直接降级打开更高结构版本。

D1 账号及业务数据均由 Cloudflare 导出及 Time Travel 管理；本地数据库备份关闭。加密主密钥必须单独备份，丢失后不能解密已保存 AI 密钥。禁止把主密钥备份到公开仓库。

## 本地修改后发布

1. 在本地修改同一套 Python/React 源码，数据始终访问 D1。
2. 优先执行与改动相关的短时检查；完整训练、大数据导入、容器构建及全量验收另行安排。
3. 上传源码到 GitHub。上传源码本身不会为 Workers 增加 Python 求解能力。
4. 提供计算服务域名及服务器后，部署上述容器；将其 HTTPS 根地址设置为 Worker 的 `BUSINESS_API_ORIGIN`。
5. Python 的允许来源必须包含 `FACTORYPULSE_FRONTEND_ORIGIN`。Worker 保留请求方法、参数、正文和 D1 会话 Cookie，Python 再验证账号权限并读写同一 D1。
6. 先做一次小范围的读写与排程检查，再扩大验收范围。

服务器尚未提供时，可以准备部署包及运行隔离短测，不能宣称完整业务已经上线。当前线上部分接口仍返回 501；接入真实 Python 服务后由该服务处理。

## Workers 原生业务与计算服务边界

> 2026-10-27：业务库已原地迁移为 V2，线上 Worker 已启用 `BUSINESS_SCHEMA_VERSION=2`。24 台设备、34,560 条采样及其他分类数量核对一致，外键无错误，无旧表副本，未创建原库备份。页面、健康与登录状态接口 HTTP 200；真实云库的概览、数据质量、库存和工单 SQL 报告检查通过。当前 Agent 查询使用 [V2 指南](AGENT-DATABASE-GUIDE.md)，[V1 指南](AGENT-DATABASE-GUIDE.md) 仅保留历史参考。

业务库为 `factorypulse_testdata`，ID `abc7cb74-5be4-49a2-827a-3bd8b639f257`。
账号库仍为 `factorypulse_users`；两库不混用，不向浏览器公开 D1 令牌或通用 SQL 接口。

## 默认测试集

`model-validation-v1-4141a127f218`，合成 CNC 验证数据，共 24 台设备、34,560 条监测采样、34,814 条总记录。
原始文件 SHA-256 为 `4141a127f218e19c11e3231e8f5c1910fb13426d9b14623fb645c89a9861a947`。
`scripts/upload-d1-dataset.py` 上传后逐条回读比对，通过后才在 D1 的 `fp_app_settings` 切换默认版本。
`source_dataset_records` 保留原有冻结输入，当前业务事实位于 equipment、sensor_readings 等清晰表名中。records 为旧接口兼容视图；calculation_history 保留真实模型计算的历史证据，fp_computed_views 为按输入修订筛选的兼容投影。确定性计算由 SQL 动态视图完成。

## 本地运行

本机 `.secrets/business.json` 配置 `account_id`、`database_id`、`token_file`；令牌只在服务端读取。
配置缺失或 Cloudflare 不可用时直接报错，不回退到本地数据库。
生产启动禁用所有 `sqlite3.connect`，包括内存 SQLite。原有本地文件保留，但不会打开。
账号和业务事务的临时表也在 D1；提交通过版本比较和原子批处理发布，失败或冲突不发布部分业务写入。
CSV/XLSX 导入的预览表已迁入 D1；不再打开上传的 SQLite 文件或在本地执行 SQL 转库。
SQLite 文件导入明确返回不支持，应先导出 CSV/XLSX。
本地数据库备份关闭；D1 导出与 Time Travel 在 Cloudflare 控制台管理。
只有显式隔离测试模式仍使用测试夹具库，网站运行不使用。

## Workers 部署与验收范围

`cloudflare/wrangler.jsonc` 的 `BUSINESS_DB` 绑定业务 D1，`DB` 绑定账号 D1，完整前端资源保留。
Workers 已支持 D1 概览、记录、设备历史、数据质量、工单/预警/审计/版本及基础资源读取。
`scripts/prepare-d1-overview.py` 从 D1 读取冻结输入，用原有 Python 模型计算并将结果存回 D1，不伪造评分。
版本不匹配时不返回旧模型结果。

## 原生工单迁移（2026-10-24）

`cloudflare/identity/work-orders.mjs` 直接在 Workers 执行以下业务，无需 Python 服务：

- 预警确认、驳回、延期、撤销和转工单；人工维修需求及既有预测运行证据关联。
- 生成维修安排；人员技能、可用工时、班次、生产占用、设备窗口、并行人数、预算和共享备件检查。
- 工单详情及流转记录；审批、接单、开工、暂停、恢复、完工、验收、返修、取消、修改需求。
- 时间轴预览/保存，保存后原审批失效；撤回、归档和回收站恢复。
- 库存实盘、预留、释放和实际耗用；维修履历、审计及资源维护。

所有写入与 Python 共用 `fp_business_revision` 原子批处理保护，更新对象为实际变更行，不克隆全量采样表。工单和预警操作保存请求签名及幂等回执；账号、数据版本或资源变化时拒绝旧操作。未携带时区的业务时间按北京时间解释，带时区的输入先换算为北京时间。

本机通过 `backend/remote_auth.py` 将工单、预警操作、资源、时间轴和排程请求送到既有 `auth_service_url` 指向的同一 Worker，保留查询参数、Cookie 和错误状态。因此日常本地站与主站使用同一工单实现，不维护两套工单规则。即使配置其他 Python 计算上游，Worker 也优先处理已迁入的原生工单接口，避免循环转发。隔离验收配置没有该生产入口，不会意外将测试写入正式库。

Workers 排程采用“优先级顺序、逐任务最早可行人员与时间”的明确策略，返回 `optimizer_status=feasible`，不声称全局最优，也不冒用 Python CP-SAT 名称。无可行安排时逐项返回冲突。Python CP-SAT 三方案比较、训练、企业数据导入等其他模块未在本次工单迁移内，未实现的接口仍返回 501；可另接 Python 计算服务。

快速隔离测试：`node cloudflare/identity/test-work-orders.mjs`。真实云端测试：`scripts/acceptance-workers-workorders.py`，仅绑定 `.secrets/acceptance-current.json` 的独立库；证据在 `outputs/full-acceptance/workers-workorders.json`，不修改正式数据。

本次不迁移内置 AI 设置或 Agent，Dify workflow 由所有者另行配置；没有向 Worker 新增 AI 密钥或设置存储。
Compose 已包含账号与业务 D1 机密绑定；`FACTORYPULSE_FRONTEND_ORIGIN` 指定 Cloudflare 页面来源，避免线上修改请求被 Python 来源校验拒绝。部署准备不需要创建默认管理员密码，既有账号和密码仍由 D1 管理。
不能把“线上已正确读取 D1”表述为“线上所有业务功能已完成迁移”。

## 本地开发、交付与恢复

当前本地站仍连接 D1，不回退独立 SQLite 业务库。启动方式见[README](../README.md)。账号与业务 D1 通过 Cloudflare 导出及 Time Travel 管理；加密主密钥单独保管。本地 SQLite 自动备份和物理离线业务链路属于旧架构，不是当前 D1 运行保证。

历史 Windows 离线安装和 SQLite 恢复演练保留证据，但不能替代当前版本的干净目标机、D1 不可用、物理断网及恢复验收。当前依赖远端 D1 的登录和业务不可因有静态文件或缓存而保证断网可用。

## 账号、权限与首次使用

Cloudflare D1 的 `auth_users` 不再包含 `username`。网站使用 `user_id` 登录。

| 字段 | 规则 |
| --- | --- |
| user_id | 整数主键，自 10001 递增；网站创建账号后自动分配 |
| display_name | 显示名称 |
| role | 开发者、管理员、普通用户、只读用户 |
| staff_id | 开发者为 0；管理员及只读为 -1；普通维修用户为正整数。以服务端约束核验 |
| password_hash | 密码 UTF-8 字节的 SHA-256，64 位十六进制；兼容旧 PBKDF2-SHA256 |
| active | 1 启用，0 禁用 |
| version | 从 1 起的并发版本号，修改账号时递增 |

开发者拥有系统配置和账号管理权限，管理员负责维护业务审批管理，普通用户仅能处理分配给自己的工单，只读用户不能修改业务数据。数据库直接保存中文角色，服务内部映射为 developer/admin/user/viewer。

单次 SHA-256 是按所有者指定采用的格式，抗密码穷举能力弱于加盐慢哈希。登录输入原始密码，不能用哈希代替密码登录。修改密码时旧会话失效。不要将明文密码、哈希、D1 令牌发布到仓库。

只有显式配置 `FACTORYPULSE_GUEST_USER_ID` 指向一个已启用的只读账号时，才提供该账号的一键访客入口。普通编号账号不会被自动作为访客开放。

已有账号表的结构升级使用 `scripts/upgrade-d1-account-schema.py`；保留账号、原密码与教程记录，先在受保护的 `.secrets` 目录备份，并使旧会话失效。不自动创建默认账号。


在本机私密设置已有账号的密码（输入时隐藏，不需要手工计算哈希）：

```powershell
.venv\Scripts\python.exe scripts/set-d1-password.py --user-id 10001
```

## 登录与入口

所有业务 API 先验证登录；本地、Cloudflare 主站与镜像使用同一账号服务。不存在默认匿名模式、自动创建默认管理员或通过浏览器角色字段授权。数字编号从 10001 自动分配；修改密码、停用或角色变化会撤销旧权限票据。

首次进入显示五步教程，进度绑定 user_id 并由服务端账号存储保存，刷新、换浏览器或重新登录后可续接，完成后帮助仍可访问。旧教程文档中的本地 SQLite 存储与 username 编辑不作为当前规则。

## 个人中心与角色

个人中心提供账号信息、本人改密、退出和相关待办。开发者管理账号和系统连接；管理员负责业务审批验收；普通维修用户处理分配给关联人员编号的工单；只读不能提交业务修改。前端隐藏按钮不替代服务端权限验证。

## 会话与跨站

认证 Cookie 使用 HttpOnly 与 Secure；跨站入口采用显式允许来源及凭据请求。浏览器限制会话时不得用离线身份绕过。当前加密权限票据、撤销、账号隔离与缓存清理见[刷新与缓存](CLOUD-DEPLOYMENT.md)。账号服务不可用时拒绝认证，不回退默认账号。

## 手动刷新、权限票据与缓存

业务 GET 优先读取按账号 ID、账号版本和角色隔离的 IndexedDB JSON 快照。快照不按时间失效；某项数据首次没有本地快照时加载一次。没有后台轮询、窗口聚焦刷新或写入后的自动版本检查。POST/PUT 等明确提交操作仍由服务端执行，业务快照在点击“更新数据”后更新。

“更新数据”读取资源版本，只重新请求依赖发生变化的 JSON。未提供版本信息的接口在手动更新时重新读取。云端无变化时继续使用原对象；读取失败保留本地快照并显示错误。页面订阅快照字段更新，不重新挂载表单。退出时清除本地业务快照，避免共享设备泄漏。

数据质量：deploy/d1-quality-report.sql 是查询来源，quality-query.mjs 是 Worker 打包副本；测试校验二者一致。物化当前采样与中间统计，一条 SQL 返回汇总、字段覆盖、采样间断、设备质量、指标统计和采样基线 JSON。Python 与 Worker 使用相同查询。总览只读取一次 v_dashboard_devices，并从该结果计算指标和排名，同时返回 all_devices 完整结果。

权限：登录时验证账号并由 IdentityRuntime 生成 AES-GCM 加密权限票据，保存在浏览器的 HttpOnly / Secure Cookie；加密密钥保存在私有 Durable Object，前端不能伪造权限。有效票据在业务请求中不读取 D1 账号表。服务端仍检查票据、有效期及撤销状态。角色变更、停用、密码或资料变更会撤销旧票据；登出撤销当前票据。旧会话兼容期使用按会话与用户主键查询，不加载全表。票据有效期8小时，到期重新登录。

权限管理应通过账号接口执行；直接修改数据库的运维脚本必须同步调用 IdentityRuntime 的 invalidate-user，否则已签发票据会保留至到期。不要将浏览器 localStorage 中的角色字段作为服务端授权依据。

部署：两个 Wrangler 入口均需要 IDENTITY_RUNTIME Durable Object 绑定和 identity-runtime-v1 迁移。新逻辑在部署前不会改变线上读取量；无需修改业务表结构。

验证：npm run build；node scripts/test-api-client.mjs；node scripts/test-data-cache.mjs；Worker test.mjs、test-runtime.mjs、test-encrypted-session.mjs、test-inplace-v2.mjs、test-read-budget.mjs。400条采样的本地D1对照：质量报告读取从14422降到9625（约33%）；总览复杂视图查询从3次降到1次。该比例仅代表测试数据，不代表线上保证。


## 第二轮读取优化

- BUSINESS_RESULTS 私有 Durable Object 保存版本化完整 JSON。概览、质量和回放等对所有已登录用户相同的报告共享快照；工单等接口按账号、版本、角色和人员编号隔离。相同版本的并发请求合并，计算期间资源变化则不保存快照。大 JSON 按 Unicode 字符分块，避免存储单值限制。
- 统计快照按每个资源的版本保存计数。概览、数据摘要和记录列表共用计数；人员或情景变化不会重新统计采样表。采用变更后首次读取时按需更新，避免每条采样额外写一条 D1 计数记录。原始数据仍由 D1 保存，缓存使用 Durable Object 存储。
- V2 设置直接读取 business_settings，避免 settings 兼容视图隐含的 COUNT。概览不再重复查询 fp_v_data_source 计数。
- /analysis/quality 从完整质量 JSON 的 equipment_quality 字段筛选，不再运行另一套复杂质量视图。
- State.load 按读写接口选择数据。工单详情只读目标工单和事件；人员、时间检查和库存各自只读需要的资源。审批和执行仍保留人员冲突与库存校验，写入使用读取资源之前的修订号进行原子保护。
- 工单支持 dataset_version、equipment_id、status 筛选，及 limit / before_updated_at / before_id 游标分页。未传 limit 的旧客户端仍获得完整列表，不会被静默截断。预警支持同类 SQL 筛选及可选 limit。
- 回放只查询所涉设备、回放时间区间内的维修历史，最新模型运行使用组合索引。

部署需要发布更新后的 Worker 和 BUSINESS_RESULTS / business-results-v1 绑定迁移；已有 V2 D1 需运行 scripts/install-d1-read-indexes.py 安装 deploy/d1-read-indexes.sql。该脚本仅增加索引，不替换业务事实。创建新 V2 或从 V1 迁移时会自动安装相同索引。本轮未执行线上部署或索引安装。

新增验证：test-result-runtime.mjs、test-scoped-read-budget.mjs、test-replay-read-budget.mjs。本地300条无关资源样本中，人员读取从1809行降至7行，单工单详情为9行；这些数字仅代表测试样本，不是线上保证。

回放对照补充：300条区间外历史加1条相关记录的样本中，旧维修历史查询读取602行，新回放整个请求读取4行；时间线结果一致。




### 发布证据摘要

2026-10-28 已发布手动更新、加密票据及版本化 JSON 缓存。10 月 29 日四个优化视图和七个索引已核对，更新按钮、设备列表及维护列表完成部分页面检查。线上缓存命中响应头和完整工单写入仍缺直接验收；同步详情曾显示 Invalid Date，需以当前版本复核。旧每 5 秒轮询不再作为当前行为。
