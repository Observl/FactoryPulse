import {useState} from "react";
import {MetricsPrimer} from "./MetricMeaning";
const steps=[
 {title:"准备数据",place:"数据中心",page:"数据中心",action:"导入数据",who:"设备总管",text:"上传文件，核对字段与单位；预览通过后确认导入。",done:"设备和采样记录已显示，数据质量已核对。"},
 {title:"复核预警",place:"维护中心 · 预警复核",page:"执行审批",action:"打开维护中心",who:"设备总管",text:"查看设备工况、风险变化和维修记录，再确认、延期、驳回或创建维修需求。",done:"预警已有处理结果；需要维修的设备已创建需求。"},
 {title:"核对资源",place:"维护中心 · 资源配置",page:"维护计划",action:"配置维修资源",who:"设备总管",text:"填写检修工时与技能、人员班次、生产订单、备件和预算。",done:"维修所需条件已保存，时间和库存已核对。"},
 {title:"安排并审批",place:"维护中心 · 工单处理",page:"执行审批",action:"安排维修",who:"设备总管",text:"选择排程条件，点击“生成维修安排”。查看设备和人员时间轴，解决冲突后批准工单。",done:"工单已批准，人员和时间已确定。拖动调整后需重新审批。"},
 {title:"执行维修",place:"工作台 · 执行任务",page:"工作台",action:"查看维修待办",who:"维修人员",text:"打开工单接单、开始维修。需要时暂停或恢复；结束后填写实际工时、费用和结果，提交完工。",done:"工单进入待验收，实际维修结果已填写。"},
 {title:"验收归档",place:"工作台 · 待验收",page:"工作台",action:"查看验收待办",who:"设备总管",text:"核对维修结果与备件实际耗用。通过后归档；需要返修则退回维修。",done:"工单完成，设备维修记录和库存已更新。"},
];
export function HelpPage({onNavigate}:{onNavigate:(page:string)=>void}){
 const [tab,setTab]=useState("操作指南");
 return <div className="help-page"><nav className="section-tabs" aria-label="帮助主题">{["操作指南","指标词典","数据与备份"].map(item=><button key={item} className={tab===item?"active":""} aria-pressed={tab===item} onClick={()=>setTab(item)}>{item}</button>)}</nav>
 {tab==="操作指南"&&<section className="panel help-guide"><div className="panel-heading"><h2>完成一次维修</h2><span>日常从工作台待办开始</span></div><ol className="newcomer-steps">{steps.map((step,index)=><li key={step.title}><span className="guide-step-number">{index+1}</span><div><div className="guide-step-heading"><h3>{step.title}</h3><span>{step.who}</span></div><small>{step.place}</small><p>{step.text}</p><details className="guide-completion"><summary>怎样算完成？</summary><p>{step.done}</p></details><button className="text-link" onClick={()=>onNavigate(step.page)}>{step.action} →</button></div></li>)}</ol><details className="technical-details"><summary>撤回、删除与历史记录</summary><p>未开工安排可撤回待排程；完工提交可撤回执行中。允许删除的工单移入回收站后可恢复，维修履历和库存流水保留。不同数据版本的工单在工单页切换查看。</p></details></section>}
 {tab==="指标词典"&&<MetricsPrimer/>}
 {tab==="数据与备份"&&<section className="panel help-guide"><h2>数据与备份</h2><details className="help-topic"><summary>如何判断数据可用？</summary><p>检查缺失、重复、采样间断及格式，再核对单位、设备类型和采样时间。基础校验通过不代表已验证预测效果；历史数据不代表设备今天的状态。</p></details><details className="help-topic"><summary>风险评分是故障概率吗？</summary><p>不是。当前评分用于决定优先检查谁，尚未经过概率校准。标签或独立故障不足时，不生成模型评分。</p></details><details className="help-topic"><summary>备份范围与恢复</summary><p>启动后及每24小时自动备份业务数据库，包含工单、库存、账号与审计，不包含原始上传文件和系统凭据。恢复前停止服务，按项目恢复说明操作；备份需另行保存副本。</p></details></section>}</div>;
}
