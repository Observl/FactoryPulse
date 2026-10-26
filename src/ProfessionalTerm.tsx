import {Fragment,useEffect,useId,useRef,useState,type ReactNode} from "react";
import {createPortal} from "react-dom";
import {metricMeaning} from "./metric-definitions";

const definitions={...metricMeaning,
 f1:{title:"同时考虑少漏报与少误报的综合分",definition:"F1把预警命中率和故障前窗口发现率合起来看，范围是0到1，越接近1越好。两项中有一项很低，F1也会偏低。",impact:"用于比较同一测试条件下的方案。"},
 threshold:{title:"达到多少分才发出提醒",definition:"阈值就是提醒的分数线。分数线低，通常提醒更多，也可能误报更多；分数线高，提醒更少，也可能漏报。",impact:"按复核工作量选择提醒线。"},
 calibration:{title:"分数能否当作真实发生机会",definition:"概率校准要检查：被预测为某个概率的一批案例，实际发生比例是否接近这个概率。当前项目尚未证明这一点。",impact:"因此70分不能解释成70%的故障概率。"},
 rms:{title:"一段振动的总体强度",definition:"RMS（均方根）概括一段振动信号的强度。",impact:"比较相近转速与负载下的振动强度。"},
 window:{title:"一次采样对应的观察时段",definition:"这里一个窗口是从某次采样起往后七天。相邻采样的七天范围大量重叠，同一次故障可以对应很多窗口。",impact:"窗口数量不能当作故障次数或设备数量。"},
 missing:{title:"本应有读数的位置有多少为空",definition:"缺失率为空值占应采集字段的比例。",impact:"用于发现采集缺口。"},
 confidence:{title:"字段映射建议的参考把握",definition:"表示字段名与目标指标的匹配程度。",impact:"确认编号、时间、单位和字段映射。"},
 mean:{title:"把数值相加后除以数量",definition:"平均值反映整批数据的总体水平，易受极值影响。",impact:"看平均提前量时，还要看实际发现了几次故障。"},
 median:{title:"按大小排序后位于中间的数",definition:"中位数表示一半数据不高于它、一半不低于它，受个别特别大或特别小数值的影响较少。",impact:"用于估计通常采样间隔。"},
 anomaly:{title:"与参考范围明显不同的读数",definition:"异常值可能来自真实工况变化、启停、传感器问题或录入错误，并不自动等于故障。",impact:"应先核对原始数据与工况，再判断是否维修。"},
 series:{title:"按采集时间排列的读数",definition:"时间序列展示同一设备的读数随时间的变化。",impact:"用于查看异常是突然出现、持续加重，还是只发生在启停时。"},
 sample:{title:"一次采集或汇总后的记录",definition:"样本量为参与统计的数据记录数量。",impact:"判断预测可信度还需要看独立设备和独立故障的数量。"},
 xgboost:{title:"从历史指标中学习规律的预测模型",definition:"XGBoost把多棵决策树的结果组合起来，根据历史标注学习哪些工况更常出现在故障之前。",impact:"通过独立测试数据评估模型表现。"},
 skill:{title:"完成维修所需的能力条件",definition:"排程只把任务分配给技能名称匹配、且在所需时间段有空的人员。多个人同时参与的任务要求全部人员都满足条件。",impact:"技能、班次和工时决定可安排的任务。"}
};
type TermKey=keyof typeof definitions;
export const termAliases:Record<string,TermKey>={"同窗对照":"matched","规则覆盖率":"coverage","全部指标缺失":"excluded","精确率":"precision","预警命中率":"precision","召回率":"recall","故障前窗口发现率":"recall","正常窗口误报率":"false_alarm_rate","误报率":"false_alarm_rate","假阳性率":"false_alarm_rate","平均提前量":"lead","提前量":"lead","风险评分":"risk","融合评分":"risk","组合风险":"risk","独立故障":"event","时间外测试":"test","时间外评估":"test","训练集":"test","验证集":"test","测试集":"test","规则基线":"baseline","概率校准":"calibration","EWMA":"ewma","SHAP":"shap","XGBoost":"xgboost","CP-SAT":"optimizer","F1":"f1","阈值":"threshold","RMS":"rms","采样窗口":"window","缺失率":"missing","置信度":"confidence","平均值":"mean","中位数":"median","异常值":"anomaly","时间序列":"series","样本量":"sample","技能":"skill","建议把握":"confidence","匹配建议":"confidence","模型参考分":"xgboost","近期工况变化":"ewma","检查优先分":"risk"};

type Meaning={title:string;definition:string;impact:string};
export function ProfessionalTerm({name,children}:{name:TermKey;children:ReactNode}){return <TermTooltip item={definitions[name]}>{children}</TermTooltip>}
export function FieldHint({text,children}:{text:string;children:ReactNode}){return <TermTooltip item={{title:"填写说明",definition:text,impact:""}}>{children}</TermTooltip>}
function TermTooltip({item,children}:{item:Meaning;children:ReactNode}){
 const id=useId(),[open,setOpen]=useState(false),[position,setPosition]=useState({left:0,top:0,width:300}),focused=useRef(false),timer=useRef<ReturnType<typeof setTimeout>>();
 const show=(element:HTMLElement)=>{if(timer.current)clearTimeout(timer.current);const rect=element.getBoundingClientRect();const width=Math.min(320,window.innerWidth-24);setPosition({left:Math.max(12,Math.min(window.innerWidth-width-12,rect.left+rect.width/2-width/2)),top:rect.bottom+248<window.innerHeight?rect.bottom+8:Math.max(12,rect.top-248),width});setOpen(true)};
 const hide=()=>{if(!focused.current)timer.current=setTimeout(()=>setOpen(false),160)};
 useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current)},[]);
 useEffect(()=>{if(!open)return;const close=(event:Event)=>{if(event.target instanceof Element&&event.target.closest(".term-tooltip"))return;setOpen(false)};window.addEventListener("scroll",close,true);window.addEventListener("resize",close);return()=>{window.removeEventListener("scroll",close,true);window.removeEventListener("resize",close)}},[open]);
 return <><span className="professional-term" tabIndex={0} aria-describedby={open?id:undefined} onMouseEnter={event=>show(event.currentTarget)} onMouseLeave={hide} onFocus={event=>{focused.current=true;show(event.currentTarget)}} onBlur={()=>{focused.current=false;setOpen(false)}} onKeyDown={event=>{if(event.key==="Escape"){setOpen(false);event.stopPropagation()}}}>{children}</span>{open&&createPortal(<div id={id} role="tooltip" className="term-tooltip" style={{position:"fixed",...position}} onMouseEnter={()=>{if(timer.current)clearTimeout(timer.current)}} onMouseLeave={hide}><strong>{item.title}</strong><p>{item.definition}</p><small>{item.impact}</small></div>,document.body)}</>;
}

const words=Object.keys(termAliases).sort((a,b)=>b.length-a.length);
const matcher=new RegExp("("+words.map(word=>word.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("|")+")","g");
export function ExplainText({text}:{text:string}){return <>{text.split(matcher).map((part,index)=>termAliases[part]?<ProfessionalTerm key={index} name={termAliases[part]}>{part}</ProfessionalTerm>:<Fragment key={index}>{part}</Fragment>)}</>}
