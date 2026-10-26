import {useApiUpdate} from "./useCachedData";
import {ContributionCalendar} from "./components/DesignCharts";
import {ActionDialog} from "./components/ActionDialog";
import {Button} from "./components/Button";
import {LoadingPanel} from "./LoadingPanel";
import {useExclusiveOperation} from "./useExclusiveOperation";
import {useAuth} from "./Auth";
import {apiRequest,errorMessage} from "./api";
import {useState} from "react";
type Version={version:string;source_name:string;source_date?:string;archived_at:string;record_count?:string;device_count?:string};
const request=apiRequest;
export function DataVersions({onRestored}:{onRestored:()=>Promise<unknown>}){
 const auth=useAuth();
 const [versions,setVersions]=useState<Version[]>([]),[current,setCurrent]=useState(""),[selected,setSelected]=useState<Version|null>(null),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 useApiUpdate(["/data/versions"],(_path,body)=>{setVersions(body.records);setCurrent(body.current_version);setLoaded(true)});
 const openOperation=useExclusiveOperation(()=>{setSelected(null);setConfirmed(false)});
 const load=async()=>{setBusy(true);setError("");try{const data=await request("/data/versions");setVersions(data.records);setCurrent(data.current_version);setLoaded(true)}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 const restore=async()=>{if(!selected)return;setBusy(true);setError("");try{const result=await request(`/data/versions/${encodeURIComponent(selected.version)}/restore`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed,expected_dataset_version:current})});setMessage(result.message);setSelected(null);setConfirmed(false);await onRestored();await load()}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 return <details className="panel data-versions" onToggle={event=>{if(event.currentTarget.open&&!loaded)void load()}}><summary>历史数据版本</summary><p className="hint">每次替换前保留旧数据。恢复时当前数据也会归档，工单与处理历史不会删除；库存与工单实际履历不回退，恢复后需重新核对维护安排。</p>{error&&<p className="alert error" role="alert">{error}</p>}{message&&<p className="alert success" aria-live="polite">{message}</p>}<Button className="secondary" disabled={busy} onClick={()=>void load()} busy={busy} busyLabel="处理中…">{"刷新版本列表"}</Button>{loaded&&<ContributionCalendar events={versions.map(item=>({timestamp:item.archived_at}))}/>} {loaded&&!versions.length&&<p>尚无归档版本。</p>}{!loaded&&<LoadingPanel title="历史数据版本" fields={[]} columns={["来源文件","数据日期","监测记录数","归档时间","操作"]}/>} {versions.length>0&&<div className="table-scroll"><table><thead><tr><th>来源文件</th><th>数据日期</th><th>监测记录数</th><th>归档时间</th><th>操作</th></tr></thead><tbody>{versions.map(item=><tr key={item.version}><td>{item.source_name}</td><td>{item.source_date||"未知"}</td><td>{item.record_count==null?"未知":Number(item.record_count).toLocaleString()}</td><td>{new Date(item.archived_at).toLocaleString("zh-CN",{hour12:false})}</td><td><Button disabled={busy||!auth.canManage} onClick={()=>{if(!openOperation())return;setSelected(item);setConfirmed(false)}}>选择恢复</Button></td></tr>)}</tbody></table></div>}{selected&&<ActionDialog title="恢复数据版本" busy={busy} onClose={()=>setSelected(null)}><section className="operation-form"><strong>恢复 {selected.source_name}</strong><p>这会替换当前设备和监测记录，旧工单不会自动变成新数据下的有效排程。</p><label className="check-line"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>我已确认数据来源，并会在恢复后重新核对维护安排。</label><div className="actions"><Button className="primary" disabled={busy||!auth.canManage||!confirmed} onClick={()=>void restore()}>确认恢复这份数据</Button><Button className="secondary" disabled={busy} onClick={()=>setSelected(null)}>取消</Button></div></section></ActionDialog>}</details>;
}
