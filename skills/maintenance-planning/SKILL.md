---
name: maintenance-planning
description: 综合人员技能与班次、订单占用、库存和预算准备维护排程草案。
---

1. 明确情景编号、设备范围和成功标准。用 operations_context 分页读取 staff、orders、inventory、requirements、scenarios；持续读取 next_offset 直到所需范围完整。
2. 分开识别人员能力、人员可用时间、生产占用和维护需求。未配置约束不得自行假设可用。
3. 使用 compare_plans 比较取舍，使用 draft_schedule 执行后端约束计算。不得由语言模型自行计算并声称排程可执行。
4. 向用户展示人员、起止时间、冲突及未满足条件。变更班次或订单只使用 request_change 申请授权。
5. 数据版本或 business_revision 改变后重算。排程草稿确认、工单批准、维修执行和验收保持为独立业务步骤。

参考 ISA-95 / IEC 62264 的业务计划与制造运行信息交换边界，属于项目流程映射，未进行条款级符合性认证。
来源：https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard
