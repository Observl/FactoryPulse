import {ActionDialog} from "./components/ActionDialog";
import {Button} from "./components/Button";
import {useExclusiveOperation} from "./useExclusiveOperation";
import {WorkOrderHistory} from "./WorkOrderHistory";
import {useUnsavedChanges} from "./useUnsavedChanges";
import {useAuth} from "./Auth";
import {apiRequest,errorMessage} from "./api";
import {useEffect,useState} from "react";

type Order={staff_id?:string;staff_ids?:string[];spare_parts?:{part_name:string;quantity:number}[];actual_parts?:{part_name:string;quantity:number}[];actual_start_at?:string;work_order_id:string;status:string;version?:number;execution_history?:{at:string;actor:string;from:string;to:string;note:string}[]};
const actions:Record<string,[string,string][]>={"草稿·待排程":[["cancel","取消需求"]],"待审批":[["cancel","取消待审批工单"]],"已退回":[["revise","修改需求并重新排程"],["cancel","取消需求"]],"已驳回":[["revise","修改需求并重新排程"],["cancel","取消需求"]],"已批准":[["accept","确认接单"],["cancel","取消工单"]],"已接单":[["start","开始维修"]],"执行中":[["pause","暂停"],["finish","提交完工"]],"已暂停":[["resume","恢复维修"],["cancel","取消工单"]],"待验收":[["verify","验收通过"],["rework","退回维修"]]};

export function WorkOrderActions({order,onChanged,onBusyChange,showHistory=true}:{order:Order;onChanged:()=>Promise<void>;onBusyChange?:(busy:boolean)=>void;showHistory?:boolean}){
 const auth=useAuth();const unsaved=useUnsavedChanges();
 const permitted=(action:string)=>!auth.required||!!auth.user&&(["developer","admin"].includes(auth.user.role)||(auth.user.role==="user"&&["accept","start","pause","resume","finish"].includes(action)&&(order.staff_ids||[order.staff_id]).includes(auth.user.staff_id)));
 const [partUse,setPartUse]=useState<Record<string,string>>({}),[partsConfirmed,setPartsConfirmed]=useState(false),[action,setAction]=useState(""),[actor,setActor]=useState(""),[note,setNote]=useState(""),[hours,setHours]=useState(""),[cost,setCost]=useState(""),[requestId,setRequestId]=useState(()=>crypto.randomUUID()),[busy,setBusy]=useState(false),[error,setError]=useState(""),[result,setResult]=useState("");
 const openOperation=useExclusiveOperation(()=>{setAction("");setNote("");unsaved.clear()});
 useEffect(()=>{if(auth.user)setActor(auth.user.display_name)},[auth.user?.user_id,auth.user?.display_name]);
 useEffect(()=>{onBusyChange?.(busy);return()=>onBusyChange?.(false)},[busy,onBusyChange]);
 const needsParts=!!order.spare_parts?.length&&(action==="verify"||(action==="cancel"&&(!!order.actual_start_at||order.status==="已暂停")));
 const invalidParts=Object.values(partUse).some(value=>value===""||!Number.isInteger(Number(value))||Number(value)<0);
 const submit=async()=>{
  if(busy)return;
  setBusy(true);setError("");setResult("");
  try{
   const body=await apiRequest(`/work-orders/${order.work_order_id}/transition`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,version:order.version||1,actor,note,actual_hours:hours===""?null:Number(hours),actual_cost_cny:cost===""?null:Number(cost),request_id:requestId,actual_parts:needsParts?Object.entries(partUse).map(([part_name,quantity])=>({part_name,quantity:Number(quantity)})):null})});
   unsaved.clear();setAction("");
   setResult(`${order.work_order_id} 已提交${body.status?" · "+body.status:""}。处理过程已保存。`);
   try{await onChanged()}catch(e){setError("操作已保存，但列表刷新失败。请刷新状态后再操作："+errorMessage(e))}
  }catch(e){setError(errorMessage(e))}finally{setBusy(false)}
 };

 return <>{result&&<p className="work-order-result" role="status">{result}</p>}{!action&&error&&<div className="error" role="alert">{error}<Button className="secondary" disabled={busy} onClick={async()=>{setBusy(true);try{await onChanged();setError("")}catch(e){setError("列表刷新失败："+errorMessage(e))}finally{setBusy(false)}}}>刷新状态</Button></div>}{showHistory&&order.execution_history?.length?<details className="work-order-history"><summary>处理记录 · {order.execution_history.length} 条</summary><WorkOrderHistory events={order.execution_history}/>{order.actual_parts?.length?<p className="quiet-note">实际耗用：{order.actual_parts.map(part=>`${part.part_name} × ${part.quantity}`).join("、")}</p>:null}</details>:null}<div className="table-actions">{(actions[order.status]||[]).filter(([value])=>permitted(value)).map(([value,label])=><Button className="secondary" aria-pressed={action===value} key={value} disabled={busy||!!result&&!!error} onClick={()=>{if(!openOperation())return;unsaved.clear();setAction(value);setNote("");setHours("");setCost("");setResult("");setPartsConfirmed(false);const counts:Record<string,string>={};for(const part of order.spare_parts||[])counts[part.part_name]=String(Number(counts[part.part_name]||0)+part.quantity);setPartUse(counts);setRequestId(crypto.randomUUID());setError("")}}>{label}</Button>)}</div>{action&&<ActionDialog title={actions[order.status]?.find(([value])=>value===action)?.[1]||"处理工单"} busy={busy} onClose={()=>{if(unsaved.discard()){setAction("");unsaved.clear()}}}><div className="operation-form" onChangeCapture={unsaved.mark}><strong>{actions[order.status]?.find(([value])=>value===action)?.[1]}</strong><label>操作人员<input readOnly={!!auth.user} value={actor} onChange={e=>{setActor(e.target.value);setRequestId(crypto.randomUUID())}} autoComplete="name"/></label><label>处理说明<textarea value={note} onChange={e=>{setNote(e.target.value);setRequestId(crypto.randomUUID())}} rows={2}/></label>{action==="finish"&&<><label>实际工时（小时）<input type="number" min="0" step="0.1" value={hours} onChange={e=>{setHours(e.target.value);setRequestId(crypto.randomUUID())}}/></label><label>实际费用（元）<input type="number" min="0" step="0.01" value={cost} onChange={e=>{setCost(e.target.value);setRequestId(crypto.randomUUID())}}/></label></>}{needsParts&&<fieldset><legend>确认备件实际耗用</legend>{Object.entries(partUse).map(([name,value])=><label key={name}>{name}<input type="number" min="0" step="1" value={value} onChange={event=>{setPartUse(old=>({...old,[name]:event.target.value}));setPartsConfirmed(false);setRequestId(crypto.randomUUID())}}/></label>)}<label className="check-line"><input type="checkbox" checked={partsConfirmed} onChange={event=>setPartsConfirmed(event.target.checked)}/>以上是实际耗用，未用填写0；提交后扣减库存并释放剩余预留。</label></fieldset>}<div className="ui-form-feedback" aria-live="polite">{error&&<p role="alert" className="error">{error}</p>}</div><div className="actions"><Button className="primary" disabled={busy||!permitted(action)||(needsParts&&(!partsConfirmed||invalidParts))||!actor.trim()||(["pause","finish","verify","rework","revise","cancel"].includes(action)&&!note.trim())||(action==="finish"&&(hours===""||cost===""))} onClick={()=>void submit()} busy={busy} busyLabel="提交中…">{"确认提交"}</Button><Button className="secondary" disabled={busy} onClick={()=>{if(unsaved.discard())setAction("")}}>取消</Button></div></div></ActionDialog>}</>;
}
