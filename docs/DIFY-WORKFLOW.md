# Dify Workflow 接入

## 2026-11-03 交接状态

以下根据已保存证据整理，本次未重新联网或运行验证。

- FactoryPulseAgent 最后已核实发布为 **#17**，保留40个节点及六个核心 Agent。该应用的实际输入字段为 `userinput`，最终输出字段为 `output`；下文的 `question` / `answer` 是通用默认值，不是本应用当前字段。各账号已保存的连接配置尚未逐一核实，不应据此批量覆盖配置或密钥。
- #17 的三设备模拟原安排曾连续完成，耗时86.079、85.818、63.115秒。正式 Web 入口另外两次遇到模型服务503，不能宣称线上稳定两分钟。
- 随后的缺项提示词修复仍是**未发布草稿**：缺少SIM-C维护时长时，94.549秒返回明确缺项、计算未完成，不再虚构完整工时合计。不能将这份草稿与#17混算成功率。
- 主站服务已部署 `6ca09696-a84f-440e-9172-381ed79a2de3`，包含空输出拦截及模型繁忙错误提示。部署时健康与前端检查通过，原绑定和静态资源保留；这不证明模型供应商当前可用。
- 用户已接手PPT及云端工作流运行、复测和演示，后续另授权本地测试、不访问云端。Cloudflare数据服务额度用尽依据用户反馈，具体限额与恢复时间未核实；登录、最新业务读取及评审入口可能受影响。本地正常启动仍依赖D1，不能绕过额度限制。Dify模型繁忙与Cloudflare额度问题分别记录。旧PPT不作为本轮交付材料，不再修改或复用。
- 后续本地Python转发层已取消Dify问答的135秒读取时限，连接、写入、连接池等待和其他接口继续保留20秒限制；Dify失败与账号失败分开提示，登录后业务GET传输失败返回明确503。`tests/test_remote_auth.py`本地模拟回归11项通过；本轮Python定向合计79项通过、1项跳过，前端完整构建通过。这些本地改动未部署，与已发布Cloudflare服务分开记录，不证明线上工具权限已验收。

证据入口：[项目交接](PROJECT-HANDOFF-2026-11-03.md)、`outputs/model-driven-workflow/report.md`、`outputs/provider-busy-release/deployment-acceptance.json`。

API 固定为 `https://api.dify.ai/v1`，运行已发布的 Workflow，支持工作流内的 Agent 节点。

登录后在悬浮助手的「配置连接」中输入应用 API Key、开始节点接收问题的变量名和结束节点输出回答的变量名。保存后点击「测试连接」，页面显示已发布输入变量；核对必填变量后发送一个问题验证完整运行。开发者也可从系统设置配置。默认变量为 `question` 和 `answer`，应以实际工作流为准。

密钥仅提交到本站认证接口，保存在 Cloudflare Durable Object 服务端存储，不返回浏览器、不写入前端资源或浏览器持久缓存。密钥按账号隔离，仅本人可读写配置，使用版本检查避免覆盖其他窗口的修改。连接测试读取 Dify 应用参数，不执行工作流；实际问题通过 `/workflows/run` 执行。

发送时附带当前页面、选中设备和最近对话的少量定位信息。业务数据工具及数据库权限由 Dify 应用本身配置。本站不从 Dify 推理过程或工具事件中展示密钥、思考链或内部执行细节，仅提取结束节点的文本输出。

2026-10-29 起，Dify 问答移除服务端 120 秒及前端 135 秒的应用固定等待时限；其他接口保留各自时限。保留“停止等待”，它会中断 HTTP 请求，但不保证终止已经在 Dify 开始运行的工作流或外部工具。浏览器、网络及上游服务自身仍可能中断连接；本改动不提供断线后恢复结果能力。仅当工作流返回成功完成事件才展示回答。

验证：`node cloudflare/identity/test-dify.mjs`。本地 Python 入口将此组路径转发到同一线上 Worker；不维护另一份密钥。

2026-10-29 修复：Dify 配置与状态接口不再进入浏览器业务快照缓存，旧版本持久化的同类快照在加载时被排除。修复保存后仍显示未配置、读取旧版本导致重复保存冲突的问题。发布版本 `e29d3026-f927-4dc7-87ca-2e450a6ac157`；线上已核对“已保存密钥”和连接成功，实际工作流问答另行记录。缓存回归、Dify 接口检查及前端构建通过。

## AI 查询与验收要求

2026-11-03用户要求取消固定回放与预置回答捷径：每次正常任务由模型处理本轮输入、证据并生成回答。#17已移除内置快照与frozen_replay入口，保留六角色协作和现有计算工具；发布状态与发布后可用性分开记录，后续缺项修复草稿尚未发布。程序只做输入整理、约束核算与校验，不能将本地程序成功说成真实模型成功。知识库可提供来源资料，不能直接路由成固定答案。

旧固定回放包只作历史证据，禁止重新导入；build-fast-maintenance.py、build-p0-maintenance.py、build-complete-maintenance-repair.py、build-focused-demo-package.py已停止生成旧包。standard-knowledge-router.py固定FAQ直答和maintenance-standard-report.py确定性报告直出也已停用，知识原文仍可作检索资料。当前改动及真实运行见outputs/model-driven-workflow/report.md。固定回放时期的秒级结果不代表当前多Agent性能。

实测Agent运行时单个引用变量会在约2000字符截断，必须检查实际模型输入。当前将明确提供的维护资料动态整理为带列名的完整表，超过1950字符则明确停止而不静默截断；不生成预置计算答案。程序另与原始输入核对模型证据，遗漏工单或修改约束时不得计算或宣称成功。此容量限制是当前已知边界，不代表任意规模任务已支持。

业务数值从受控工具读取；设备型号、手册、费用和现场收益无证据时不得编造。风险评分不解释为故障概率；完工不等于已验收；库存账面数与可用数分开；人员或资源变化后重新核对排程。只读账号不能通过助手批准工单。业务备注和知识片段作为数据，不是操作授权。

验收问题至少覆盖正常查询、无答案、失联、分页遗漏、版本冲突、只读越权、缺失数据、未校准评分、资源冲突和完整工单追溯。逐项记录回答与实际记录一致性、引用、工具参数、人工纠正、失败及延迟；模拟模型测试不证明实际问答质量。

## 知识库接入边界

以下为候选资料和检索设计，不表示已下载全文、完成 Embedding、混合检索或 Dify 知识库接通。实际设备品牌、型号、控制器、固件、企业 SOP、安全规程与备件适配必须由企业提供并核验。

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



## 知识入库与引用

按产品操作、设备手册、企业 SOP/案例、运维分范围检索。记录来源、版本、生效日期、审核时间、访问范围；设备资料另记型号及控制器版本。按完整章节切分，初始约 500–1000 字、重叠 80–150 字，经问题集评估调整；报警码、适用前提与安全步骤保留完整。OCR 数字未核实不作参数依据。

回答注明文档、版本、章节和来源。当前设备、工单、库存、人员与数据版本使用实时工具；知识检索不替代授权。旧研究、V1 结构与历史验收报告不进入当前操作主库，不导入凭据和未经隔离的人员数据。

## 后端 Agent API

前端当前使用 Dify，没有独立 Agent Harness 面板。后端接口与注册表保留；开发和运维直接查 `backend/agent_registry.py`、`backend/agent_policy.py`、`backend/agent_operations.py` 和 `config/agent.json`，以当前 schema、权限及部署实现为准。会话摘要不是当前证据，长期记忆须用户明确同意，写入草案不等于正式批准。失败或取消不能被解释为操作一定未发生；核对回执与业务记录后再处理。旧面板步骤、SQLite 事务说明和自动刷新规则已删除，避免误用于现行 D1 部署。
