import {ActionDialog} from "./components/ActionDialog";
import {Button} from "./components/Button";
import {useExclusiveOperation} from "./useExclusiveOperation";
import {useUnsavedChanges} from "./useUnsavedChanges";
import {createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode} from "react";
import {FirstLoginTutorial} from "./FirstLoginTutorial";
import {apiRequest,errorMessage} from "./api";

type User={user_id:string;username:string;display_name:string;role:string;staff_id?:string;version:number};
export type Onboarding={step:number;completed_at:string|null;total_steps:number};
type Status={required:boolean;setup_needed:boolean;mode:string;guest_available?:boolean;identity_provider?:string;user:User|null;onboarding?:Onboarding|null};
type AuthValue=Status&{canManage:boolean;refresh:()=>Promise<void>;logout:()=>Promise<void>};
const initial:Status={required:true,setup_needed:true,mode:"accounts",user:null};
const AuthContext=createContext<AuthValue>({...initial,canManage:false,refresh:async()=>{},logout:async()=>{}});
export const roleNames:Record<string,string>={developer:"开发者",admin:"管理员",user:"普通用户",viewer:"只读用户"};
export const useAuth=()=>useContext(AuthContext);
const post=(value:unknown):RequestInit=>({method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(value)});

export function AuthGate({children}:{children:ReactNode}){
 const [authorizedIdentity,setAuthorizedIdentity]=useState("local"),[status,setStatus]=useState<Status>(initial),[ready,setReady]=useState(false),[everAuthorized,setEverAuthorized]=useState(false),[error,setError]=useState("");
 const generation=useRef(0);
 const refresh=useCallback(async()=>{const revision=++generation.current;try{const next:Status=await apiRequest("/auth/status");if(revision!==generation.current)return;setStatus(next);setReady(true);setError("");if(next.user){setEverAuthorized(true);setAuthorizedIdentity(next.user?.user_id||"local")}}catch(reason){if(revision===generation.current){setError(errorMessage(reason));setReady(true)}}},[]);
 useEffect(()=>{void refresh();const expired=()=>void refresh();window.addEventListener("factorypulse:auth-expired",expired);return()=>window.removeEventListener("factorypulse:auth-expired",expired)},[refresh]);
 const logout=async()=>{await apiRequest("/auth/logout",{method:"POST"});generation.current++;setEverAuthorized(false);setStatus(old=>({...old,user:null,onboarding:null}))};
 const locked=!ready||!!error||!status.user;
 const tutorial=!locked&&!!status.user&&!status.onboarding?.completed_at;
 const value={...status,canManage:!!status.user&&["developer","admin"].includes(status.user.role),refresh,logout};
 return <AuthContext.Provider value={value}>{everAuthorized&&!locked&&!tutorial&&<div key={authorizedIdentity}>{children}</div>}{tutorial&&status.user&&<FirstLoginTutorial key={status.user.user_id} user={status.user} progress={status.onboarding||{step:0,completed_at:null,total_steps:5}} onCompleted={refresh} onLogout={logout}/>} {locked&&<main className="auth-frame"><section className="panel"><h1>FactoryPulse</h1><p className="hint">连接 Cloudflare 账号中心</p>{!ready?<p role="status">正在连接设备管理服务…</p>:error?<><p className="alert error" role="alert">{error}</p><Button className="primary" onClick={()=>void refresh()}>重新连接</Button></>:<LoginForm setup={status.setup_needed} cloud={status.guest_available===true} onLoggedIn={refresh}/>}</section></main>}</AuthContext.Provider>;
}

function LoginForm({setup,cloud=false,onLoggedIn}:{setup:boolean;cloud?:boolean;onLoggedIn:()=>Promise<void>}){
 const [username,setUsername]=useState(""),[password,setPassword]=useState(""),[name,setName]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const submit=async()=>{setBusy(true);setError("");try{await apiRequest(setup?"/auth/bootstrap":"/auth/login",post({username,password,...(setup?{display_name:name}:{})}));setPassword("");await onLoggedIn()}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 return <>{cloud&&<div className="actions"><Button className="primary" disabled={busy} onClick={()=>{setBusy(true);setError("");void apiRequest("/auth/guest",{method:"POST"}).then(onLoggedIn).catch(reason=>setError(errorMessage(reason))).finally(()=>setBusy(false))}}>只读用户 · 一键进入</Button></div>}<form onSubmit={event=>{event.preventDefault();void submit()}}><h2>{setup?"初始化管理员":"登录设备管理工具"}</h2>{setup&&<p className="hint">在服务所在电脑上设置管理员，密码至少12个字符。</p>}<label>用户编号<input required autoComplete="username" value={username} onChange={event=>setUsername(event.target.value)}/></label>{setup&&<label>管理员姓名<input required value={name} onChange={event=>setName(event.target.value)}/></label>}<label>密码<input required type="password" autoComplete={setup?"new-password":"current-password"} minLength={setup?12:undefined} maxLength={256} value={password} onChange={event=>setPassword(event.target.value)}/></label>{error&&<p className="alert error" role="alert">{error}</p>}<Button className="primary" disabled={busy} type="submit" busy={busy} busyLabel="正在处理…">{setup?"创建管理员并登录":"登录"}</Button></form></>;
}

export function SessionBadge(){
 const auth=useAuth();const [error,setError]=useState("");
 if(!auth.user)return null;
 return <div className="session-badge"><span>{auth.user.display_name} · {roleNames[auth.user.role]}</span><PasswordSettings/><Button className="secondary" onClick={()=>void auth.logout().catch(reason=>setError(errorMessage(reason)))}>退出</Button>{error&&<span role="alert">{error}</span>}</div>;
}

type Account=User&{active:number|boolean};
export function SecurityPanel(){
 const auth=useAuth();
 const [open,setOpen]=useState(false),[accounts,setAccounts]=useState<Account[]>([]),[staff,setStaff]=useState<{staff_id:string;staff_name?:string}[]>([]),[editing,setEditing]=useState<Account|null>(null),[username,setUsername]=useState(""),[name,setName]=useState(""),[password,setPassword]=useState(""),[role,setRole]=useState("viewer"),[staffId,setStaffId]=useState(""),[active,setActive]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 const load=useCallback(async()=>{if(!auth.user||auth.user.role!=="developer")return;try{const [users,people]=await Promise.all([apiRequest("/auth/users"),apiRequest("/records/staff?limit=5000")]);setAccounts(users.records);setStaff(people.records)}catch(reason){setError(errorMessage(reason))}},[auth.user?.user_id,auth.user?.role]);
 useEffect(()=>{if(open)void load()},[open,load]);
 const reset=()=>{setEditing(null);setUsername("");setName("");setPassword("");setRole("viewer");setStaffId("");setActive(true)};
 const submit=async()=>{setBusy(true);setError("");try{if(!auth.required){await apiRequest("/auth/bootstrap",post({username,display_name:name,password}));setPassword("");await auth.refresh();setMessage("账号保护已启用。请妥善保管管理员密码。")}else if(editing){await apiRequest(`/auth/users/${editing.user_id}`,post({display_name:name,role,staff_id:role==="developer"?"0":role==="admin"?"-1":staffId,active,version:editing.version}));await auth.refresh();setMessage("账号权限已更新")}else{await apiRequest("/auth/users",post({display_name:name,password,role,staff_id:role==="developer"?"0":role==="admin"?"-1":staffId}));setMessage("账号已创建，初始密码请通过公司认可的方式交给本人")}reset();await load()}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 if(auth.required&&auth.user?.role!=="developer")return null;
 return <details className="panel security-panel" onToggle={event=>setOpen(event.currentTarget.open)}><summary>创建与管理账号 · {auth.required?"已启用":"本地单人模式"}</summary>{error&&<p className="alert error" role="alert">{error}</p>}{message&&<p className="alert success" aria-live="polite">{message}</p>}{!auth.required&&<p className="hint">启用后，审批和验收按账号权限执行，操作人自动记入记录。</p>}{accounts.length>0&&<div className="table-scroll"><table><thead><tr><th>账号</th><th>姓名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>{accounts.map(account=><tr key={account.user_id}><td>{account.username}</td><td>{account.display_name}</td><td>{roleNames[account.role]}</td><td>{account.active?"启用":"停用"}</td><td><Button disabled={busy} onClick={()=>{setEditing(account);setUsername(account.username);setName(account.display_name);setRole(account.role);setStaffId(account.staff_id||"");setActive(!!account.active);setPassword("")}}>编辑权限</Button></td></tr>)}</tbody></table></div>}<form onSubmit={event=>{event.preventDefault();void submit()}}><h3>{!auth.required?"设置首个管理员":editing?"编辑账号权限":"新增账号"}</h3><div className="form-grid"><label>用户编号<input readOnly value={editing?.user_id||"保存后自动分配，从 10001 开始"}/></label><label>姓名<input required readOnly={!!editing&&editing.user_id!==auth.user?.user_id} value={name} onChange={event=>setName(event.target.value)}/></label>{!editing&&<label>初始密码<input required type="password" minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={event=>setPassword(event.target.value)}/></label>}{auth.required&&<label>角色<select value={role} onChange={event=>setRole(event.target.value)}>{Object.entries(roleNames).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>}{["user","viewer"].includes(role)&&auth.required&&<label>公司人员编号<input required type="number" min="1" step="1" value={staffId} onChange={event=>setStaffId(event.target.value)}/></label>}</div>{editing&&<label className="check-line"><input type="checkbox" checked={active} onChange={event=>setActive(event.target.checked)}/>允许此账号登录</label>}<div className="actions"><Button className="primary" disabled={busy} type="submit" busy={busy} busyLabel="正在保存…">{!auth.required?"启用账号保护":editing?"保存权限":"创建账号"}</Button>{editing&&<Button type="button" disabled={busy} onClick={reset}>取消编辑</Button>}</div></form></details>;
}

export function PasswordSettings(){
 const auth=useAuth();const unsaved=useUnsavedChanges();
 const [open,setOpen]=useState(false),[current,setCurrent]=useState(""),[next,setNext]=useState(""),[confirmation,setConfirmation]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const close=()=>{unsaved.clear();setOpen(false);setCurrent("");setNext("");setConfirmation("");setError("")};
 const openOperation=useExclusiveOperation(close);
 const submit=async()=>{if(next!==confirmation){setError("两次新密码输入不一致");return}setBusy(true);setError("");try{await apiRequest("/auth/password",post({current_password:current,new_password:next}));close();await auth.refresh()}catch(reason){setError(errorMessage(reason))}finally{setBusy(false)}};
 return <div className="password-settings"><Button className="secondary" aria-expanded={open} onClick={()=>{if(open){if(unsaved.discard())close()}else if(openOperation())setOpen(true)}} disabled={busy}>修改密码</Button>{open&&<ActionDialog title="修改密码" busy={busy} onClose={()=>{if(unsaved.discard())close()}}><form className="operation-form" onChangeCapture={unsaved.mark} onSubmit={event=>{event.preventDefault();void submit()}} aria-label="修改自己的密码"><strong>修改密码</strong><label>当前密码<input required type="password" autoComplete="current-password" maxLength={256} value={current} onChange={event=>setCurrent(event.target.value)}/></label><label>新密码<input required type="password" autoComplete="new-password" minLength={12} maxLength={256} value={next} onChange={event=>setNext(event.target.value)}/></label><label>再次输入新密码<input required type="password" autoComplete="new-password" minLength={12} maxLength={256} value={confirmation} onChange={event=>setConfirmation(event.target.value)}/></label><p className="hint">至少12个字符。保存后所有设备上的旧会话都会退出，请使用新密码重新登录。</p><div className="ui-form-feedback" aria-live="polite">{error&&<p role="alert" className="error">{error}</p>}</div><div className="actions"><Button className="primary" type="submit" disabled={busy} busy={busy} busyLabel="正在保存…">{"保存并重新登录"}</Button><Button type="button" className="secondary" disabled={busy} onClick={()=>{if(unsaved.discard())close()}}>取消</Button></div></form></ActionDialog>}</div>;
}
