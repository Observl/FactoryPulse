import {useEffect,useState} from "react";
import {useAuth} from "./Auth";
import {apiRequest,errorMessage} from "./api";


type Snapshot={filename:string;created_at:string;size_bytes:number;integrity:string};
type Status={status:string;last_success:Snapshot|null;last_error:string};
const labels:Record<string,string>={not_started:"等待首次备份",running:"正在生成备份",ready:"最近备份已完成",failed:"备份失败",disabled:"自动备份已关闭"};

export function BackupPanel(){
 const auth=useAuth();
 const [status,setStatus]=useState<Status|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 const allowed=!auth.required||auth.user?.role==="admin";
 const load=async()=>{const value:Status=await apiRequest("/backups/status");setStatus(value)};
 useEffect(()=>{if(!allowed||import.meta.env.VITE_STATIC_DEMO==="true")return;let active=true;const refresh=()=>apiRequest("/backups/status").then((value:Status)=>{if(active){setStatus(value);setError("")}}).catch(reason=>{if(active)setError(errorMessage(reason))});void refresh();const timer=window.setInterval(()=>void refresh(),10000);return()=>{active=false;window.clearInterval(timer)}},[allowed]);
 const create=async()=>{if(!allowed)return;setBusy(true);setError("");setMessage("");try{const result:{backup:Snapshot}=await apiRequest("/backups/create",{method:"POST"});setStatus({status:"ready",last_success:result.backup,last_error:""});setMessage("备份已生成并通过完整性检查。恢复能力仍需单独演练。")}catch(reason){setError(errorMessage(reason));await load().catch(()=>{})}finally{setBusy(false)}};
 if(!allowed||import.meta.env.VITE_STATIC_DEMO==="true")return null;
 const snapshot=status?.last_success;
 return <section className="panel backup-card"><div className="panel-heading"><h2>数据备份</h2><span className={status?.status==="failed"?"status-pill caution":"status-pill"}>{status?labels[status.status]||"状态待确认":"读取状态…"}</span></div><p className="quiet-note">业务数据库 · 启动后及每24小时自动备份</p>{error&&<p className="alert error" role="alert">{error}</p>}{status?.last_error&&<p className="alert error" role="alert">{status.last_error}</p>}{message&&<p className="inline-message" role="status">{message}</p>}{snapshot?<><dl className="backup-facts"><div><dt>最近完成</dt><dd>{new Date(snapshot.created_at).toLocaleString("zh-CN",{hour12:false})}</dd></div><div><dt>文件大小</dt><dd>{(snapshot.size_bytes/1024/1024).toFixed(2)} MB</dd></div><div><dt>完整性校验</dt><dd>{snapshot.integrity==="ok"?"通过":"未确认"}</dd></div></dl><details className="technical-details"><summary>备份文件与范围</summary><code>{snapshot.filename}</code><p>包含工单、库存、账号及审计记录；不包含原始上传文件和系统凭据。恢复前停止服务，详细要求见帮助页。</p></details></>:<p className="filter-empty">尚无已完成备份</p>}<div className="actions"><button className="primary" disabled={busy||status?.status==="running"} onClick={()=>void create()}>{busy||status?.status==="running"?"正在备份…":"立即备份"}</button><button className="secondary" disabled={busy} onClick={()=>void load().catch(reason=>setError(errorMessage(reason)))}>刷新状态</button></div></section>;
}
