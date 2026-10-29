# 手动更新与本地 JSON 缓存

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


## 2026-10-28 发布记录

站点 https://factorypulse.griffonage2077.workers.dev 已发布版本 9b804685-c054-4a21-9688-ce8a4c48cb96。本次发布手动更新、本地JSON缓存、加密权限票据、BusinessResults云端JSON缓存、按需读取与统计复用；未包含三个待定诊断模型及其推理接口。算法转换代码和权重仅保留本地。

已核对主页与冻结发布包一致，主页和健康接口HTTP 200；线上BusinessResults与IdentityRuntime绑定正常，七个新增读取索引均存在。发布前版本为 eb94c72a-8d4d-404d-b453-534b49ee95b6。

尚未完成：v_equipment_latest_reading、v_reading_metrics 两个视图仍是旧定义，另两个目标视图已一致。Cloudflare明确返回D1每日免费读取额度耗尽（错误7500），阻止了这两个视图更新及登录后的业务验收。未升级套餐。额度预计北京时间2026-10-29 08:00重置；恢复后需补做视图刷新和业务验收，不能把本次发布记为全部验收完成。

发布证据位于 outputs/releases/reading-20261028-235342/deployment-verification.json；该目录的发布快照未包含 .secrets、训练数据或诊断模型。


## 2026-10-29 补充更新与验收

剩余两个视图已更新，四个优化视图及七个读取索引核对通过。随后发布版本7da0f692-eb76-4b4e-a3b7-5e0032b4bb78，将“更新数据”和缓存状态移入页头“历史／文件数据”打开的详情弹窗。

线上页面检查：更新按钮点击后显示“缓存已同步”，7项缓存保留；设备清单加载24台设备；风险统计为高6、中15、低3台；维护中心显示4项预警、0项在办工单和1项操作记录。未更改线上工单状态。隔离环境缓存回归及49项工单流程检查通过，测试的后端模块与冻结发布文件一致。

尚未直接核实：线上云端JSON缓存命中响应头、完整工单写入流程。已知界面缺陷：同步详情的数据版本启用时间显示Invalid Date。上述限制保留，不将本次检查记为全站全部验收通过。

离线诊断研究与转换脚本属于源码准备；未接入生产路由，模型权重、训练数据与输出目录不随Git提交。
