import {ArrowRight,Check,ChevronRight} from "lucide-react";

type Step={page:string;title:string;detail:string;state:string;done:boolean};

export function WorkflowGuide({page,hasData,hasPlan,onNavigate}:{page:string;hasData:boolean;hasPlan:boolean;onNavigate:(page:string)=>void}){
 const steps:Step[]=[
  {page:"数据中心",title:"载入与核对数据",detail:"确认设备、时间、指标和单位",state:hasData?"已载入，仍需核对质量":"需要导入数据",done:false},
  {page:"风险预测",title:"复核风险证据",detail:"查看曲线与维修记录，确认需求",state:hasData?"需人工复核":"等待数据",done:false},
  {page:"维护计划",title:"核对维护资源",detail:"人员、技能、窗口、备件和预算",state:"由企业确认真实条件",done:false},
  {page:"维护策略",title:"比较维护方案",detail:"检查费用、人员占用和冲突",state:hasPlan?"已计算，尚未审批":"等待方案计算",done:false},
  {page:"执行审批",title:"排程到执行验收",detail:"审批、接单、开工、完工和验收",state:"逐步记录处理结果",done:false},
 ];
 return <section className="workflow-guide" aria-labelledby="workflow-title">
  <div className="workflow-heading"><div><span className="workflow-kicker">标准操作流程</span><h2 id="workflow-title">从数据到维护执行</h2></div><p>按顺序完成复核与审批；模型评分只用于排序，最终决策由人员确认。</p></div>
  <div className="workflow-steps">{steps.map((step,index)=><button type="button" key={step.title} className={"workflow-step"+(page===step.page?" current":"")+(step.done?" completed":"")} onClick={()=>onNavigate(step.page)} aria-current={page===step.page?"step":undefined}>
   <span className="workflow-number" aria-hidden="true">{step.done?<Check size={15}/>:String(index+1).padStart(2,"0")}</span>
   <span className="workflow-copy"><strong>{step.title}</strong><small>{step.detail}</small><em>{step.state}</em></span>
   {index<steps.length-1?<ChevronRight className="workflow-chevron" size={16} aria-hidden="true"/>:<ArrowRight className="workflow-chevron" size={16} aria-hidden="true"/>}
  </button>)}</div>
 </section>
}
