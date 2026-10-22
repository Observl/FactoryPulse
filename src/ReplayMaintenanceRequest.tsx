import {useExclusiveOperation} from "./useExclusiveOperation";
import {useUnsavedChanges} from "./useUnsavedChanges";
import {useState} from "react";
import {useAuth} from "./Auth";
import {apiRequest,errorMessage} from "./api";

export function ReplayMaintenanceRequest({runId,readingId,equipmentId,timestamp,onOpenWorkOrder}:{runId:string;readingId:string;equipmentId:string;timestamp:string;onOpenWorkOrder?:(id:string)=>void}){
 const auth=useAuth();const unsaved=useUnsavedChanges();
 const [open,setOpen]=useState(false);
 const openOperation=useExclusiveOperation(()=>{setOpen(false);unsaved.clear();setAction("");setConfirmed(false)});
 const [action,setAction]=useState(""),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(""),[workId,setWorkId]=useState(""),[requestId,setRequestId]=useState(()=>crypto.randomUUID());
 if(!auth.canManage||!runId||!readingId)return null;
 const submit=async()=>{if(!confirmed)return;setBusy(true);setError("");try{const result=await apiRequest("/maintenance-requests",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({equipment_id:equipmentId,action,priority:"中",request_id:requestId,prediction_run_id:runId,evidence_reading_id:readingId})});unsaved.clear();setWorkId(result.work_order_id)}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 return <details className="operation-form" open={open}><summary onClick={event=>{event.preventDefault();if(busy)return;if(open){if(unsaved.discard())setOpen(false)}else if(openOperation())setOpen(true)}}>基于当前历史记录创建人工维护需求</summary><p className="hint">引用 {equipmentId} · {timestamp} · {readingId}。这是今天创建的人工需求，不表示当年曾实际派工。</p>{error&&<p className="alert error" role="alert">{error}</p>}{workId?<><p>维护需求 {workId} 已创建，历史证据引用已保存。</p>{onOpenWorkOrder&&<button onClick={()=>onOpenWorkOrder(workId)}>进入维护中心核对与排程</button>}</>:<form onChangeCapture={unsaved.mark} onSubmit={event=>{event.preventDefault();void submit()}}><label>检查动作与人工依据<textarea required minLength={2} maxLength={1000} rows={2} value={action} onChange={event=>{setAction(event.target.value);setRequestId(crypto.randomUUID());setConfirmed(false)}}/></label><label className="check-line"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>我已核对设备身份，理解这是基于历史证据的人工需求；正式维修仍需配置、排程与审批。</label><button className="primary" disabled={busy||!confirmed||action.trim().length<2}>{busy?"正在创建…":"确认创建人工需求"}</button><button className="secondary" type="button" disabled={busy} onClick={()=>{if(unsaved.discard())setOpen(false)}}>取消</button></form>}</details>;
}
