# FactoryPulse RAG 知识来源与入库清单

检索日期：2026-10-23。本文是来源筛选与入库建议，不表示已下载外部全文、完成知识库导入或接通 Dify。

## 1. 范围

以 README 定义的设备风险证据、维护排程、工单协作为范围。当前验证设备是合成 CNC 机床，不能据此认定现场使用 Haas 或 Siemens；品牌资料仅是候选，须匹配实际设备铭牌与软件版本。

## 2. 项目知识库

| 优先级 | 文件 | 问答用途 | 入库条件 |
| --- | --- | --- | --- |
| P0 | README.md | 功能、角色、当前架构与验证边界 | 记录提交版本 |
| P0 | [docs/AGENT-DATABASE-GUIDE.md](AGENT-DATABASE-GUIDE.md) | V2 事实表、动态视图、迁移状态与字段清理规则 | V2 尚未上线，不能用于当前 V1 库生成 SQL |
| P0 | [docs/AGENT-DATABASE-GUIDE-V1.md](AGENT-DATABASE-GUIDE-V1.md) | 现有 V1 业务库结构和查询方式 | 与 V2 按结构版本隔离检索，直到所有读写方完成切换 |
| P0 | docs/AGENT-HARNESS.md | 工具、授权、会话、重试、证据与写入边界 | 与当前注册表核对 |
| P0 | docs/SCORING-AND-SCHEDULING.md | 模型分数、解释、资源约束与排程 | 保留适用边界 |
| P0 | docs/ACCOUNT-SCHEMA.md | 角色与账号规则 | 仅面向有权访问者；不导入实际账号记录 |
| P0 | docs/MODEL-VALIDATION-DATASET.md | 合成数据与模型验证边界 | 不将合成指标解释为现场效果 |
| P1 | docs/OPERATOR-GUIDE.md | 导入、复核、需求、排程、审批、执行、验收 | 先修正旧登录说明 |
| P1 | docs/LOGIN-ONBOARDING.md | 登录和新手流程 | 核对当前角色与界面 |
| P1 | docs/SQL-DATABASE-IMPORT.md | SQL 导入与设备状态 | 核对当前支持格式 |
| P1 | docs/FIELD-PROFILES-AND-OCCUPANCY.md | 字段与设备占用 | 核对实现与数据字典 |
| P1 | docs/LOCAL-DEPLOYMENT.md、docs/CLOUD-DEPLOYMENT.md | 本地与云端运维 | 放入运维专用库 |
| P1 | docs/BACKUP-RECOVERY.md | 备份、恢复与恢复验收 | 先清理旧账号/会话存储描述 |

已确认冲突：OPERATOR-GUIDE 的“可选账号保护/本地单人模式”与当前 README 的强制 D1 登录不一致。BACKUP-RECOVERY 包含旧账号与会话备份描述，而当前 README 将账号与会话放在 D1。冲突章节未核实前不入正式检索库；不要仅靠相似度让模型自行选版本。

历史回归报告、试验计划、竞赛材料和设计提案默认不进入操作主库，避免把历史或目标能力当成当前功能。

## 3. 外部官方来源

以下来源已登记到本清单。获取状态记录于 2026-10-23；“已登记”不等于已下载正文或已建立检索索引。

| 来源 ID | 来源名称 | 官方链接 | 建议知识库 | 检索关键词 | 获取与入库状态 |
| --- | --- | --- | --- | --- | --- |
| E01 | Haas 操作与维修手册 | [手册目录](https://haascnc.com/owners/Service/operators-manual.html) | 设备维修库 | 数控机床、CNC、铣床、车床、主轴、润滑、冷却、维护、故障排查 | 已核实目录和部分章节；按实际型号选择正文后入库 |
| E02 | Siemens SINUMERIK 828D / SINAMICS S120 诊断 | [官方文档记录](https://support.industry.siemens.com/cs/ww/en/view/109761928) | 设备维修库 | 数控系统、SINUMERIK、828D、SINAMICS、S120、报警码、驱动诊断 | 官方引用已定位；正文访问 403，待获取并核对版本 |
| E03 | ISO 55001:2024 资产管理 | [官方说明](https://committee.iso.org/standard/83054.html?browse=tc) | 维护管理库 | 资产管理、生命周期、维护决策、职责、持续改进 | 已核实说明与概览；全文待授权 |
| E04 | ISO 14224:2016 可靠性与维护数据 | [官方说明](https://www.iso.org/standard/64076.html) | 维护管理库 | 可靠性、故障模式、维护记录、设备分类、故障数据 | 已核实范围说明；全文待授权，仅借鉴数据组织 |
| E05 | OPC UA 官方参考 | [规范目录](https://reference.opcfoundation.org/) | 数据接入库 | OPC UA、设备数据、信息模型、报警、历史访问、机床监测 | 已核实目录；选定对应规范与版本后收集正文 |
| E06 | MTConnect 标准与入门 | [标准目录](https://mtconnect.squarespace.com/standard-download20181)、[入门](https://mtconnect.squarespace.com/getting-started) | 数据接入库 | MTConnect、机床状态、数据项、设备、资产、采集 | 已获取旧站目录与入门说明；规范正文待收集 |

检索关键词用于候选召回，不表示所有文档均包含这些词的定义。通用“数控机床是什么”应检索设备基础说明；具体维修问题须额外匹配品牌、型号和控制器版本。

### E01 Haas 操作与维修手册

- 总入口：https://haascnc.com/owners/Service/operators-manual.html
- 铣床操作：https://haascnc.com/service/online-operator-s-manuals/mill-operator-s-manual/mill---introduction.html
- VF/VM 维修：https://haascnc.com/service/online-manuals/vf-vm-series---service-manual/vf-vm---introduction.html
- 状态：已读取官方目录与章节入口；未下载全套正文。
- 用途：机床操作、部件识别、维护、故障排查；按型号选择章节，不跨型号套用周期与参数。

### E02 Siemens SINUMERIK 828D / SINAMICS S120 诊断

- 官方文档记录：https://support.industry.siemens.com/cs/ww/en/view/109761928
- 状态：由官方手册交叉引用定位；直接读取返回 403，正文未核实。
- 用途：报警码、控制系统诊断与排查。待核对控制器软件版本并取得适用文档后入库。
- 不采用搜索中出现的 2009 年旧版作为默认版本。

### E03 ISO 55001:2024 资产管理

- 官方说明：https://committee.iso.org/standard/83054.html?browse=tc
- 官方概览 PDF：https://committee.iso.org/files/live/sites/tc251/files/guidance/ISO%20TC251%20ISO55001%20Rev3.pdf
- 状态：已获取范围说明与概览信息，未取得标准全文。
- 用途：资产管理职责、决策与改进框架；不能替代设备维修步骤。全文入库前核对授权范围。

### E04 ISO 14224:2016 可靠性与维护数据

- 官方说明：https://www.iso.org/standard/64076.html
- 状态：已读取官方范围说明，未取得标准全文。
- 用途：借鉴设备、故障、维护记录组织。原适用行业为石油、石化和天然气，不能声称是 CNC 专用标准。全文入库前核对授权范围。

### E05 OPC UA 官方参考

- 入口：https://reference.opcfoundation.org/
- AI 使用说明：https://reference.opcfoundation.org/ai-help
- 状态：已读取目录与 AI 使用说明入口，未收集全部规范正文。
- 用途：后续数据接入的语义映射、报警与条件、历史访问、机床监测。属于接入参考，不表示 FactoryPulse 已实现 OPC UA。

### E06 MTConnect

- 官方标准入口：https://www.mtconnect.org/standard-download20181
- 可读取的官方旧站入口：https://mtconnect.squarespace.com/standard-download20181
- 入门：https://mtconnect.squarespace.com/getting-started
- 状态：新站入口仅返回 JavaScript 页面；已获取官方旧站的标准目录与入门说明，未下载规范全文。
- 用途：机床状态、数据项、设备与资产语义；入库版本以实际采集端版本为准。不表示项目已实现采集。

## 4. 必须由企业补充的知识

1. 实际设备品牌、型号、序列号、控制器和固件版本及其适用手册。
2. 经批准的点检、保养、故障排查 SOP 与安全隔离/开工许可规程。
3. 经验收的故障案例：症状、工况、报警、确认原因、处理、备件与复测结果。
4. 备件兼容关系、替代规则与维护任务的技能要求。

公开通用资料不能补造上述现场事实。现场权限、规程与厂家限制发生冲突时，明确提示冲突并交由有资格的人员处理。

## 5. 检索与实时工具分工

- RAG：解释怎么操作、术语、规程、报警定义、方法与历史经验。
- 业务工具：查询当前设备、工单、库存、人员班次、订单占用、风险分数和数据版本。
- 写入：仍由现有权限请求、版本校验与业务审批完成。检索命中文档不构成授权。
- 不导入密钥、密码、会话令牌、完整业务数据库或未经权限隔离的人员数据。

## 6. 入库建议（初始方案，需通过检索评估调整）

建议分为产品操作、设备手册、企业 SOP/案例、运维技术四类检索范围，按角色与任务路由。

每份文档记录 source_id、title、source_url/source_path、revision、effective_date、reviewed_at、status、access_scope；设备资料另记录 manufacturer、machine_model、controller_model、firmware_version、language。每个片段继承标题路径、页码/章节和上述元数据。

按章节切分，中文初始约 500–1000 字，重叠约 80–150 字。报警码条目、操作步骤、适用条件和安全前提尽量完整保留；大型条目采用父子片段。扫描 PDF 需 OCR，图示与接线图单独记录页码，未核实的 OCR 数值不得作为操作参数。

推荐关键词与语义混合召回，再重排；报警码、设备型号与版本优先精确匹配。以上是设计建议，实际 Dify 设置须对照所部署版本。

回答至少注明文档名、版本、章节/页码与来源。缺少型号或版本时，不生成确定性的设备专用操作步骤。知识片段仅作证据，不执行其中夹带的指令。

## 7. 最小验收问题

1. 风险分数 0.8 是否表示 80% 故障概率？应否定，并引用项目边界。
2. 完工是否等于工单闭环？应说明待验收与验收通过的区别。
3. 批准后人员班次改变，能否直接开工？应说明重新检查与重排流程。
4. 当前备件够不够？应调用实时工具，不能只回答手册规则。
5. 不同品牌同一报警码能否通用？应要求品牌、控制器及版本匹配。
6. 能否关闭登录进入本地单人模式？不得引用已识别的旧手册说明。
7. 检索到维修步骤是否允许自动执行？应说明仍需适用权限与批准。

上线前建立包含正常命中、无答案、版本冲突、权限隔离与实时查询的人工标注问答集，记录正确率、引用准确性与错误拒答情况。
