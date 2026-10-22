import {ExplainText} from "./ProfessionalTerm";
export type WindowMetrics={precision?:number|null;recall?:number|null;false_alarm_rate?:number|null;f1?:number|null};
export type BaselineComparison=WindowMetrics&{coverage?:number;evaluated_rows?:number;unavailable_rows?:number;matched_model?:WindowMetrics};
const percent=(value:number|null|undefined)=>value==null?"证据不足":`${(value*100).toFixed(1)}%`;
export function EvaluationComparison({baseline}:{baseline?:BaselineComparison}){
 const ready=!!baseline?.evaluated_rows&&baseline.matched_model?.f1!=null;
 return <details className="technical-details"><summary><ExplainText text="同窗对照"/> · {ready?`${baseline!.evaluated_rows!.toLocaleString()} 个窗口`:"暂无完整可比证据"}</summary>{ready?<><div className="table-scroll"><table aria-label="相同窗口上的模型与规则比较"><thead><tr><th>指标</th><th>模型</th><th>规则</th></tr></thead><tbody>{([{key:"precision",label:"预警命中率"},{key:"recall",label:"故障前窗口发现率"},{key:"false_alarm_rate",label:"正常窗口误报率"},{key:"f1",label:"F1"}] as const).map(item=><tr key={item.key}><td><ExplainText text={item.label}/></td><td>{item.key==="f1"?baseline!.matched_model![item.key]?.toFixed(3)??"证据不足":percent(baseline!.matched_model![item.key])}</td><td>{item.key==="f1"?baseline![item.key]?.toFixed(3)??"证据不足":percent(baseline![item.key])}</td></tr>)}</tbody></table></div><p><ExplainText text="规则覆盖率"/> {percent(baseline?.coverage)} · 缺少规则依据 {baseline?.unavailable_rows?.toLocaleString()??"—"} 个窗口。</p><p className="quiet-note">只对照双方都有依据的同一批窗口；提醒线由验证集确定。</p></>:<p className="quiet-note">当前证据没有完整的同窗统计。缺少规则必要指标时，不把空值当作正常结果。</p>}</details>;
}
