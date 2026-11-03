# 本地收尾验证（2026-11-03）

用户恢复目标后明确允许本地测试，不访问云端。PPT及云端工作流运行仍由用户接手。本轮未调用Cloudflare、Dify或业务生产库。

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| node scripts/test-api-client.mjs | 退出0，全部断言通过 | 模拟传输；含非JSON 401缓存清理、无期限等待和手动取消 |
| node scripts/test-data-cache.mjs | 退出0，全部断言通过 | 模拟缓存；含双账号延迟响应交错、持久化及Dify配置排除 |
| node_modules/.bin/tsc.cmd --noEmit | 退出0 | 当前前端类型检查 |
| node scripts/test-sync-time.mjs | 15项通过，退出0 | 日期、缺项、无效值、闰日 |
| node scripts/check-button-system.mjs | 180处Button使用检查通过，退出0 | 静态组件规则，不证明文件窗口交互 |
| .venv/Scripts/python.exe -u -m pytest tests/test_remote_auth.py -q -o faulthandler_timeout=30 | 11 passed，2.66秒，退出0 | MockTransport；转发超时配置、错误反馈、权限与身份释放 |

Python首次受限执行无输出，被手动终止，退出1。诊断重跑收集11项后在首项初始化事件循环时阻塞；30秒栈显示socket._fallback_socketpair的accept等待，尚未进入业务断言。该进程也已终止，退出1。随后经系统审批在限制外运行相同本地测试，11项通过。两次受限尝试不计作业务通过，也不隐去。

Python测试有一条Starlette引用AnyIO旧别名的依赖弃用提示，不是断言失败。

当时未验证：FileButton真实浏览器交互、完整前端打包、生产部署、线上账号隔离、真实模型任务耗时及业务写入闭环。后续前端打包结果见下节；其他边界保留。上述本地通过不证明线上P0全部完成。

## 前端完整构建与交互逻辑回归

- `npm run build`退出0：按钮规则检查、TypeScript检查及Vite生产打包全部通过。Vite转换2262个模块，打包阶段7.59秒；输出位于dist。未执行部署。
- `node scripts/test-dify-stop.mjs`退出0：实际组件处理函数在模拟延迟响应下验证取消、提示、问题保留、晚到回答隔离及下一次请求状态；不调用Dify。
- `node scripts/test-mutation-outcomes.mjs`退出0，4项通过：区分写入拒绝与保存后刷新失败，不自动重复写入。
- `node scripts/test-approval-client.mjs`退出0，4项通过：丢失响应后的显式重试保留原版本和操作编号，刷新失败不冒充保存失败，刷新/放弃需要明确操作。
- `node scripts/test-operation-ownership.mjs`退出0，4项通过：操作互斥、未保存拒绝及监听清理。

这些为本地构建和模拟组件逻辑验证，未启动浏览器或服务，不证明像素布局、读屏、原生文件选择窗口及线上接口表现。未运行会访问发布工作流的test-published-workflow-app.mjs。

## 维护页面的补充本地回归

以下5个脚本均退出0，不访问浏览器或网络：

- `node scripts/test-device-state.mjs`：8项设备状态检查通过。
- `node scripts/test-device-sort.mjs`：11项设备排序及2项显示状态排序检查通过。
- `node scripts/test-operational-tasks.mjs`：12项业务待办和10项个人队列角色检查通过。
- `node scripts/test-historical-review.mjs`：3项历史复核回归通过，覆盖保存后刷新、稳定操作意图及重复提交。
- `node scripts/test-timeline-layout.mjs`：相邻任务、重叠分层、缺失/反向时间断言通过；脚本未给出独立用例数量，不自行换算数量。

上述逻辑检查不替代桌面/手机截图、触控、键盘焦点、读屏或真实浏览器文件选择验收。

## 权限和工具契约

`.venv/Scripts/python.exe -u -m pytest tests/test_security.py tests/test_d1_auth_flow.py tests/test_agent_contracts.py tests/test_agent_budget.py -q -o faulthandler_timeout=45`：**29 passed，10.50秒，退出0**；另有相同依赖弃用提示。

覆盖只读账号禁止导入/排程/审批、维修人员只处理所分配任务、退出和改密码撤销会话、最后管理员保护、来源限制、密码不回显、只读方案预览无写入、FakeD1账号流程、工具参数及禁用工具契约、无效模型参数不进入业务执行、版本范围/分页、预算计时与重复/空取证不延长预算。

D1通过FakeD1本地临时库模拟，唯一模型调用测试替换了AsyncClient。没有联网获取业务数据或调用真实模型。不得据此判定Dify线上工具配置和角色映射正确。

截至本节，本次授权本地测试后的Python定向测试累计**79项通过、1项默认跳过**。这是四组互不重复文件的合计，不是全量测试套件通过声明。

## 版本指纹与剩余完成条件

`local-closeout-source-fingerprints-2026-11-03.json`记录本轮测试结束后37个现有代码、测试及配置文件的SHA256。它标识记录时的文件内容，不是完整依赖证明或原始测试日志；后续修改有关文件时，须重新判断对应结果是否仍适用。

本轮已能确认的范围：前端完整构建、所列模拟前端逻辑脚本、79项本地Python定向断言。没有未结束的本轮测试进程。

总目标仍未达成，以下缺口不能由继续重复本地断言关闭：

1. Dify最新草稿真实问答、缺项/无解与人员缺席重排的最终正文、实际工具和权限记录、端到端耗时、发布及发布后验证。
2. 真实云端缓存与账号隔离、D1导入负载、三方案服务接入、部署工单完整闭环。
3. 桌面/手机视觉、原生文件选择交互、键盘焦点、读屏及减少动态效果验收。
4. 本校/实际赛区安排和详细评分权重、独立现场数据与收益证据。未安排工业人员访谈或体验。

用户授权仅限本地测试、禁止云端；PPT及云端运行仍由用户接手。当前没有把上述缺口标为已完成，也没有继续提交旧的网络断开任务。

## 导入、排程和工单的后续定向回归

1. `.venv/Scripts/python.exe -u -m pytest tests/test_import_recovery.py tests/test_staged_import.py tests/test_joint_schedule.py tests/test_resource_occupancy.py tests/test_work_order_lifecycle.py -q -o faulthandler_timeout=45`：**21 passed，50.54秒，退出0**。覆盖取消与提交竞争、预览缺失/损坏、重启恢复、暂存提交、生产和人员占用、共享备件/预算/工时、无解原因及本地工单流转。
2. `.venv/Scripts/python.exe -u -m pytest tests/test_import_capacity.py tests/test_database_import.py tests/test_data_sync.py tests/test_resources.py -q -o faulthandler_timeout=45`：**18 passed、1 skipped，18.22秒，退出0**。覆盖模拟磁盘不足、十万行预览取消及旧数据保留、共享上传的独立清理、SQLite/SQL导入边界、权限、304/增量响应、账号隔离、资源修改失效。跳过的是需显式设置FACTORYPULSE_IMPORT_SOAK_SECONDS的持续负载用例；没有重复运行旧长期压力任务。另有同一依赖弃用提示。

两组共39项通过、1项跳过，加上认证转发11项，本轮Python定向验证合计50项通过、1项跳过。测试使用conftest隔离临时数据库并清除真实身份配置；在系统限制外执行以支持本地事件循环通信。没有访问Cloudflare、Dify或生产业务库。测试中的临时SQLite仅为隔离验证，不改变生产仅用D1的设计。

这证明所列本地测试覆盖的行为，不能替代云端缓存命中、真实D1导入负载、模型回答、线上工单闭环及现场收益。原Notion任务保留未完成状态。
