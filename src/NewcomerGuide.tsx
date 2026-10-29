import {ArrowRight} from "lucide-react";
import {Button} from "./components/Button";
import {useState} from "react";
import {MetricsPrimer} from "./MetricMeaning";
const steps=[
 {title:"准备数据",place:"数据中心",page:"数据中心",action:"导入数据",who:"设备总管",text:"先核对数据版本、采样时间和质量。已有可用数据时直接进入预警复核；导入新文件需管理员确认来源、字段和单位，且导入计算服务已接通。",done:"当前数据版本明确，设备与采样数量正确；历史验证集不会自动变成实时数据。",check:"没有新数据无需重复导入；读取失败先检查连接和额度。"},
 {title:"复核预警",place:"维护中心 · 预警复核",page:"执行审批",action:"打开维护中心",who:"设备总管",text:"查看设备工况、风险变化和维修记录，再确认、延期、驳回或创建维修需求。",done:"预警已有处理结果；需要维修的设备已创建需求。"},
 {title:"创建维护需求",place:"维护中心 · 需求与工单",page:"执行审批",action:"查看维护需求",who:"设备总管",text:"对确认需处理的设备填写检查或维修内容、优先级及时间要求；也可从设备证据页创建人工需求。",done:"需求已保存且处于待排程，不代表已经获批或开始维修。",check:"证据不足先补充读数与记录，避免仅凭分数直接下达维修。"},
 {title:"核对资源",place:"维护中心 · 资源配置",page:"维护计划",action:"配置维修资源",who:"设备总管",text:"填写检修工时与技能、人员班次、生产订单、备件和预算。",done:"维修所需条件已保存，时间和库存已核对。"},
 {title:"安排并审批",place:"维护中心 · 工单处理",page:"执行审批",action:"安排维修",who:"设备总管",text:"选择排程条件，点击“生成维修安排”。查看设备和人员时间轴，解决冲突后批准工单。",done:"工单已批准，人员和时间已确定。拖动调整后需重新审批。"},
 {title:"执行维修",place:"工作台 · 执行任务",page:"工作台",action:"查看维修待办",who:"维修人员",text:"打开工单接单、开始维修。可暂停或恢复；填写实际工时、费用和结果后提交完工。",done:"工单进入待验收，实际维修结果已填写。"},
 {title:"验收归档",place:"工作台 · 待验收",page:"工作台",action:"查看验收待办",who:"设备总管",text:"核对维修结果与备件实际耗用。通过后归档；需要返修则退回维修。",done:"工单完成，设备维修记录和库存已更新。"},
];
export function HelpPage({onNavigate}:{onNavigate:(page:string)=>void}){
 const [tab,setTab]=useState("操作指南");
 return <div className="help-page"><nav className="section-tabs" aria-label="帮助主题">{["操作指南","指标词典","数据与备份"].map(item=><Button key={item} className={tab===item?"active":""} aria-pressed={tab===item} onClick={()=>setTab(item)} variant="navigation">{item}</Button>)}</nav>
 {tab==="操作指南"&&<section className="panel help-guide"><div className="panel-heading"><h2>完成一次维修</h2><span>7 步闭环 · 先核对证据，再执行变更</span></div><p className="hint">日常从工作台待办开始：设备总管负责复核、安排和验收，维修人员负责执行；只读用户可查看证据。已有数据和资源时跳过准备步骤。</p><nav className="help-flow-links" aria-label="维修流程步骤">{steps.map((step,index)=><a key={step.title} href={"#guide-step-"+index}>{index+1}. {step.title}</a>)}</nav><ol className="newcomer-steps">{steps.map((step,index)=><li id={"guide-step-"+index} key={step.title}><span className="guide-step-number">{index+1}</span><div><div className="guide-step-heading"><h3>{step.title}</h3><span>{step.who}</span></div><small>{step.place}</small><p>{step.text}</p><div className="guide-completion"><strong>完成标志</strong><p>{step.done}</p>{"check" in step&&<small>{step.check}</small>}</div><Button className="text-link" onClick={()=>onNavigate(step.page)}>{step.action} <ArrowRight size={15} aria-hidden="true"/></Button></div></li>)}</ol><details className="technical-details"><summary>遇到排程冲突或返修怎么办？</summary><p>排程失败先核对人员技能与班次、生产订单占用、共享备件、预算和停机窗口；补齐资源后重新生成，不要绕过冲突直接批准。已批准安排发生修改需重新审批。验收不通过时退回维修，保留原工单流转和实际耗用记录。</p></details><details className="technical-details"><summary>撤回、删除与历史记录</summary><p>未开工安排可撤回待排程；完工提交可撤回执行中。允许删除的工单移入回收站后可恢复，维修履历和库存流水保留。不同数据版本的工单在工单页切换查看。</p></details></section>}
 {tab==="指标词典"&&<MetricsPrimer/>}
 {tab==="数据与备份"&&<section className="panel help-guide"><h2>数据与备份</h2><details className="help-topic"><summary>如何判断数据可用？</summary><p>查看缺失、重复、采样间断、格式、单位和采样时间。</p></details><details className="help-topic"><summary>风险评分是故障概率吗？</summary><p>风险评分用于检查排序，不等于故障概率。</p></details><details className="help-topic"><summary>图表红点与指标区间怎么看？</summary><p>红点为故障标记，详情见故障履历。历史参考区间取本设备无故障标记样本的 P5–P95，非厂家限值。</p></details><details className="help-topic"><summary>切换页面会重复计算吗？</summary><p>页面始终复用本地 JSON 缓存；首次没有缓存时自动读取，之后仅点击“更新数据”才检查云端版本。有变化时更新相关数据，未变化的记录保留。看到“缓存已同步”表示已完成版本检查；连接失败时保留已加载数据并显示提示。</p></details><details className="help-topic"><summary>备份范围与恢复</summary><p>管理员通过 Cloudflare D1 控制台导出数据或使用 Time Travel 恢复。浏览器缓存不作备份。</p></details></section>}</div>;
}
