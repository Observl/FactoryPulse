# Cloudflare 业务数据

> 2026-10-27：业务库已原地迁移为 V2，线上 Worker 已启用 `BUSINESS_SCHEMA_VERSION=2`。24 台设备、34,560 条采样及其他分类数量核对一致，外键无错误，无旧表副本，未创建原库备份。页面、健康与登录状态接口 HTTP 200；真实云库的概览、数据质量、库存和工单 SQL 报告检查通过。当前 Agent 查询使用 [V2 指南](AGENT-DATABASE-GUIDE.md)，[V1 指南](AGENT-DATABASE-GUIDE-V1.md) 仅保留历史参考。

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
