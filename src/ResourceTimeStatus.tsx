import {useEffect,useState} from "react";
import {ApiError,apiRequest,errorMessage} from "./api";
type Status={checked_at:string;issue_count:number;groups:{kind:"requirements"|"staff";title:string;records:number;issues:{id:string;reason:string}[]}[]};
export function ResourceTimeStatus({revision,disabled,onSelect}:{revision:number;disabled:boolean;onSelect:(kind:"requirements"|"staff")=>void}){
 const [status,setStatus]=useState<Status|null>(null),[error,setError]=useState("");
 useEffect(()=>{if(import.meta.env.VITE_STATIC_DEMO==="true")return;let active=true;const load=()=>apiRequest("/maintenance/time-readiness").then(value=>{if(active){setStatus(value);setError("")}}).catch(reason=>{if(active)setError(reason instanceof ApiError&&reason.status===404?"后端尚未启用时间检查，服务更新后将自动重试。":errorMessage(reason))});void load();const timer=window.setInterval(()=>void load(),60000);return()=>{active=false;window.clearInterval(timer)}},[revision]);
 if(import.meta.env.VITE_STATIC_DEMO==="true")return null;
 if(error)return <p className="quiet-note" role="status">时间条件检查暂不可用：{error}</p>;
 if(!status)return <p className="quiet-note" role="status">正在检查班次与停机窗口…</p>;
 if(!status.issue_count)return <p className="quiet-note">已录入班次与停机窗口未发现过期；完整可行性以排程结果为准。</p>;
 return <details className="resource-time-status"><summary>时间条件 · {status.issue_count} 项需更新</summary>{status.groups.filter(group=>group.issues.length).map(group=><div key={group.kind}><div className="panel-heading"><strong>{group.title}</strong><button className="text-link" disabled={disabled} onClick={()=>onSelect(group.kind)}>前往更新 →</button></div><ul>{group.issues.map(item=><li key={item.id}><span>{item.id}</span><span>{item.reason}</span></li>)}</ul></div>)}</details>
}
