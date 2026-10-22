import {Button} from "./components/Button";
import {useRef,useState} from "react";
import {apiRequest,errorMessage} from "./api";
import {useUnsavedChanges} from "./useUnsavedChanges";

export type HistoricalAlert={alert_id:string;equipment_id:string;dataset_version?:string;prediction_at?:string;version?:number;defer_until?:string;note:string;status:string};
export function HistoricalAlertReview({record,onSaved,onClose,onOpenDevice}:{record:HistoricalAlert;onSaved:()=>Promise<void>;onClose:()=>void;onOpenDevice:(id:string)=>void}){
 const [action,setAction]=useState("confirm"),[note,setNote]=useState(""),[until,setUntil]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const operation=useRef({signature:"",id:""}),savedReceipt=useRef(false),pending=useRef(false);
 const [saved,setSaved]=useState(false);const unsaved=useUnsavedChanges();
 const save=async()=>{
  if(pending.current)return;
  pending.current=true;setBusy(true);setError("");
  try{
   if(!savedReceipt.current){
    const body={action,note,defer_until:action==="defer"?new Date(until).toISOString():null,alert_id:record.alert_id,prediction_at:record.prediction_at,expected_dataset_version:record.dataset_version,version:record.version};
    const signature=JSON.stringify(body);
    if(operation.current.signature!==signature)operation.current={signature,id:crypto.randomUUID()};
    await apiRequest(`/alerts/${encodeURIComponent(record.equipment_id)}/action`,{method:"POST",body:JSON.stringify({...body,request_id:operation.current.id})});
    savedReceipt.current=true;setSaved(true);unsaved.clear();
   }
   await onSaved();onClose();
  }catch(reason){setError((savedReceipt.current?"复核已保存，刷新结果失败。请重试刷新：":"")+errorMessage(reason))}
  finally{pending.current=false;setBusy(false)}
 };
 return <section className="panel operation-form" aria-label="历史预警复核" onChangeCapture={unsaved.mark}><h2>{record.equipment_id} · 历史复核</h2><p className="hint">原预警：{record.prediction_at||"未提供"} · {record.status}</p>{record.note&&<p>{record.note}</p>}<Button className="secondary" disabled={busy} onClick={()=>onOpenDevice(record.equipment_id)}>查看当前设备证据</Button>{error&&<p className="alert error" role="alert">{error}</p>}<label>复核结果<select disabled={busy||saved} value={action} onChange={event=>{setAction(event.target.value);setError("")}}><option value="confirm">已复核</option><option value="reject">驳回原预警</option><option value="defer">再次延期</option></select></label><label>处理意见（必填）<textarea disabled={busy||saved} maxLength={500} rows={3} value={note} onChange={event=>setNote(event.target.value)}/></label>{action==="defer"&&<label>下次复核时间<input disabled={busy||saved} type="datetime-local" value={until} onChange={event=>setUntil(event.target.value)}/></label>}<div className="actions"><Button className="primary" disabled={busy||(!saved&&(!note.trim()||(action==="defer"&&!until)))} onClick={()=>void save()} busy={busy} busyLabel="正在处理…">{saved?"刷新处理结果":"保存复核"}</Button><Button className="secondary" disabled={busy} onClick={()=>{if(unsaved.discard())onClose()}}>返回</Button></div></section>;
}
