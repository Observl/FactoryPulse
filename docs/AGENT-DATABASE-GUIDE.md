# FactoryPulse Agent SQL 数据库指南：事实表与动态视图（V2）

更新日期：2026-10-26。

**实际状态：新版前端和兼容 Worker 已发布到线上，数据库迁移被 Cloudflare D1 当日读取额度耗尽阻塞，业务库仍为 V1。** 当前查询使用 [V1 指南](AGENT-DATABASE-GUIDE-V1.md)，本页 V2 表名尚不可用。此次采用同一业务库 UUID 原地事务升级，不创建原库备份或导出，不需要更换 Dify database_id。只有线上 database_schema.version=2 且 migration_state='ready' 后，才能启用本页 V2 查询。

## 1. 两个库的职责

| 库 | 当前 ID | 职责 |
| --- | --- | --- |
| 业务库 factorypulse_testdata（现有 V1） | abc7cb74-5be4-49a2-827a-3bd8b639f257 | 设备、监测、维护资源、工单和库存；仅在已授权范围查询 |
| 账号库 factorypulse_users | af5776ef-c7f8-48c7-8f21-1bb36f98061c | 登录、账号、权限、会话。此次不修改，不向业务 Agent 提供密码哈希和会话 |
| V2 升级目标 | 沿用业务库 ID，等待额度恢复后原地迁移 | 本指南下述的新表和视图；不能将准备完成误报为迁移完成 |

执行前查询 sqlite_master 确认结构。V2 的 database_schema.version=2 且 migration_state='ready' 才表示迁移工具已读回校验成功；不表示网站已适配或现场验收已通过。

## 2. 存储原则

- 物理表仅保存观测、用户输入、业务决定、审计与必要身份/来源信息。
- 库存可用量、记录数量、最新采样、时长及费用合计使用 v_ 开头的普通 SQL 视图，查询时计算，没有手动刷新步骤。
- 模型推理、SHAP、排程求解必须在计算服务运行，不能用 SQL 视图伪装。V2 不保存“当前概览”或“当前模型结果”缓存。
- 当时的预测证据、批准的方案、实际费用和验收结果属于历史事实；保留在有明确历史含义的表中，不把它们作为当前状态。
- 不盲删未知字段：已有有效自定义输入保存到 attributes；清理过渡字段须有来源和引用检查。
- 相同信息不在多个字段重复存储；工单外层 ID、状态、更新时间从 details 中去重。

## 3. 基础事实表

| 表名 | 保存什么 | 关键字段 |
| --- | --- | --- |
| equipment | 设备档案 | equipment_id、equipment_name、equipment_type、status、production_line、required_skill、data_origin |
| sensor_readings | 实际采样和已观察故障标签 | reading_id、equipment_id、timestamp、温度、转速、扭矩、振动、负载、电流、油温、failure、label_status |
| maintenance_requirements | 每台设备的维护输入条件 | equipment_id、检查/维修单价与工时、人数、技能、允许窗口、损失假设 |
| maintenance_required_parts | 每台设备维护需要的备件 | equipment_id、part_name、quantity |
| maintenance_history | 原有维护/故障历史 | maintenance_id、equipment_id、failure_at、failure_end、maintenance_date、maintenance_type |
| maintenance_staff | 人员技能、班次与人工确认的可用工时 | staff_id、staff_name、skills、available_hours、shift_start、shift_end |
| production_orders | 生产订单和设备占用输入 | order_id、equipment_id、order_name、start_at、end_at、due_at、delay_cost_cny_per_hour |
| maintenance_scenarios | 人工设置的预算及策略限制 | scenario_id、scenario_name、maintenance_budget_cny、available_staff_count、max_downtime_h、risk_threshold、assumed_failure_probability |
| business_settings | 来源、当前版本、库存范围及字段配置 | key、value；只迁入允许的业务键，不包含 API 密钥 |

sensor_readings 的标准量值字段：air_temperature_k、process_temperature_k、rotational_speed_rpm、torque_nm、tool_wear_min、vibration_mm_s、spindle_load_pct、motor_current_a、oil_temperature_c。缺失量值保持 NULL，不填零。K 不能直接显示为摄氏度。

时间迁移为带 Z 的 UTC ISO 字符串，固定微秒精度；原无时区时间按北京时间解释。展示时转换为 Asia/Shanghai。details 中的顶层计划和实际起止时间同样规范化，历史证据中的原始时间不递归改写。

attributes 保留自定义字段、采样配置等尚不能证明无用的输入。skills 为来源文本；来源为数组时保存 JSON 文本，解析前检查实际格式。

## 4. 业务事实与历史证据表

| 表名 | 保存什么 | 注意事项 |
| --- | --- | --- |
| maintenance_work_orders | 工单标识、设备、状态、更新时间和 details | 正式计划时间、人员、执行履历在 details；跨版本工单不强制绑定当前设备外键，以保留历史事实 |
| equipment_alert_reviews | 预警的人工复核、说明、延期与版本 | 复核完成不表示设备已维修 |
| maintenance_acceptance_records | 工单正式验收与维修记录 | 完工提交不等于验收通过 |
| schedule_decision_history | 当次排程决定的 evidence 快照 | 不是可直接执行的当前计划 |
| model_run_history | 当次模型版本和 evidence 证据 | 数值属于历史推理事实，不代表当前风险 |
| business_audit_log | 操作人、操作类型、对象、时间和 details | 不是现场事实自动证明，也不与账号库同名旧表混用 |
| operation_receipts | 请求签名与已保存响应 | 用于幂等、防重复提交，保留原请求标识 |
| spare_part_stock | 按 scope 与 part_name 分隔的实盘数量 | on_hand 为库存观测输入，不改为从不完整旧流水倒推 |
| spare_part_reservations | 工单、范围、备件、预留数量与状态 | 只将 state='reserved' 计入有效预留 |
| spare_part_movements | 实际库存变化流水 | quantity 有正负符号；验收耗用为负 |
| database_schema | 结构版本、安装时间与迁移状态 | 不是业务计数或模型状态 |

业务状态保留原中文含义，不改成推测的英文枚举。工单 details.deleted_at 非空表示删除/归档标记，原始表含历史，当前业务统计通过视图排除。

## 5. 查询视图：优先给 Agent 使用

| 视图 | 动态结果 |
| --- | --- |
| v_equipment_latest_reading | 各设备最新采样；相同时间按 reading_id 排序确定唯一行，reading_rank=1 |
| v_equipment_summary | 设备档案、最新指标和采样数量，未采样设备仍保留 |
| v_maintenance_requirements | 维护总工时 maintenance_hours、总费用 maintenance_cost_cny |
| v_maintenance_history | 按起止时间计算 downtime_hours，若存在独立观测时长则优先使用 |
| v_spare_part_availability | 各 scope 实盘、有效预留、可分配库存、reservation_shortage 与带符号余额 |
| v_current_spare_part_availability | 只保留当前库存范围 |
| v_work_order_schedule | 从工单 details 提取版本、计划/实际起止、人员与删除标记，计算计划时长 |
| v_work_order_counts | 按状态汇总未删除工单数量，不擅自筛掉其他版本的有效工单 |
| v_reading_duplicates | 按设备与采样时间识别重复组，不在迁移时擅自删重复记录 |
| v_reading_gaps | 相邻采样间隔 gap_seconds；没有预期采样频率时不直接判定漏采 |
| v_data_quality_summary | 采样数、设备数、采样范围、无效时间、重复组和未知设备计数 |
| v_business_counts | 当前基础记录与原始工单行数；工单行数含历史/删除项，业务统计另看 v_work_order_counts |

这是一组基础检查，不包含全部业务质量规则。负载阈值、模型概率、故障根因、现场收益均不能由这些视图自动证明。

## 6. 字段清理决策

| 旧数据 | 新处理 |
| --- | --- |
| readings.future_failure | 不存储，训练时按明确预测窗口及观察覆盖范围重新生成，防止标签泄漏 |
| readings._feature_fields、_equipment_profile、prediction_horizon_hours | 保留在 attributes，属于特征与采样/标签配置，不能未经核实认定为无用 |
| demo_risks | 不迁入当前事实库；原值保留在源备份，后续按实际规则或模型重新计算，不冒用旧评分 |
| maintenance_hours、maintenance_cost_cny | 等于分项和时删除重复值；不同则保存为 duration_override_h、cost_override_cny 人工输入，由视图优先使用 |
| maintenance_history.downtime_hours | 与起止推算相等时删除；不一致或缺少起止时保留 observed_downtime_h |
| 维护条件 spare_parts.available_quantity | 不作为库存事实；保留到 attributes.legacy_part_inputs 待核对，正式库存查询 stock 与 reservation |
| fp_computed_views、fp_computed_freshness | 不迁入 V2 当前库，由普通视图或实时计算服务取代；旧内容仍在备份 |
| settings 中设备数量、记录数量等派生计数 | 不迁入，查询 v_business_counts 或汇总视图 |
| records 的 JSON 包装与 row_index | 拆成直接可读的业务表，使用真实业务主键 |
| 旧版本归档、导入作业、助手记忆、修订和临时表 | 不混进当前事实库；保存在完整源备份中，恢复/运行层另行适配；没有静默删除 |

不能证明可计算或无关的字段不删除。历史档案暂留备份不等于已迁入新系统；需要在线历史版本、恢复和内置助手的部署，在切换前必须完成相应适配和验收。

## 7. SQL 示例（仅 V2 目标库）

```sql
SELECT version,migration_state FROM database_schema;
SELECT equipment_id,equipment_name,latest_sample_at,vibration_mm_s,reading_count
FROM v_equipment_summary ORDER BY equipment_id LIMIT 100;

SELECT timestamp,rotational_speed_rpm,torque_nm
FROM sensor_readings WHERE equipment_id=? ORDER BY timestamp DESC,reading_id DESC LIMIT 100;

SELECT * FROM v_work_order_schedule
WHERE equipment_id=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 100;

SELECT * FROM v_current_spare_part_availability ORDER BY part_name LIMIT 100;
SELECT * FROM v_data_quality_summary;
SELECT * FROM v_work_order_counts;
```

占位符必须由支持参数绑定的工具提供值。用户级权限仍由服务端限制；SQL 视图不提供行级授权。不能将分页样本作为全量统计。

## 8. 对各 Agent 的规则

- PLAN：明确当前连接为 V1 还是 V2，不能混用表名。
- ROUTER：只分派已有权限的查询；数据库 UUID 与业务数据集标识不同。
- RESEARCH：先确认结构，优先查询视图，保留查询范围、版本和数据时间。
- ANALYSIS：区分观测、人工假设和派生值；模型计算使用实际可用服务。
- EXECUTE：数据库查询默认只读；写入仍走获授权业务接口。
- REVIEW：检查实时性、覆盖范围、单位、历史/当前区别及验收证据。
- REPORT：引用本次工具结果，不把迁移测试或合成数据当成现场结论。

## 9. 交付与验证

- [V2 SQL](../deploy/d1-business-v2.sql)
- [迁移工具](../scripts/migrate-d1-business-v2.py)
- [转换与字段清理规则](../backend/database_v2.py)
- [迁移及动态视图测试](../tests/test_database_v2.py)
- [切换步骤与限制](D1-SCHEMA-V2-MIGRATION.md)

不提供兼容 V1 写入的伪视图。当前 Worker 和 Python 的事务、资源、导入、审计及模型接口仍依赖 V1；仅改 BUSINESS_DB 绑定会导致错误，不能直接切换。
