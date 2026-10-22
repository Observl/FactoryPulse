import {useState,type ReactNode} from 'react';
import {Button} from './components/Button';
export type CloudUser={user_id:string;username:string;display_name:string;role:string;version:number};
const key='factorypulse.cloud-session.v1';
const users:Record<string,CloudUser>={viewer:{user_id:'cloud-viewer',username:'viewer',display_name:'只读访客',role:'viewer',version:1},admin:{user_id:'test',username:'test',display_name:'线上测试员',role:'admin',version:1}};
function readSession(){try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');return saved&&saved.expires>Date.now()?users[saved.role]||null:null}catch{return null}}
export function CloudAuthGate({children}:{children:(user:CloudUser,logout:()=>Promise<void>)=>ReactNode}){
 const [user,setUser]=useState<CloudUser|null>(readSession),[account,setAccount]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const enter=(role:string)=>{try{sessionStorage.setItem(key,JSON.stringify({role,expires:Date.now()+8*60*60*1000}))}catch{}setPassword('');setError('');setUser(users[role])};
 const logout=async()=>{try{sessionStorage.removeItem(key)}catch{}setUser(null);setPassword('');setAccount('');setError('')};
 const login=async()=>{setBusy(true);setError('');try{const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password));const hash=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');if(!['test','线上测试员'].includes(account.trim())||hash!=='958e32809c23ebc1f09315ffb739b757e3590b0a5ee141e5a9a8e4a2917850e4')throw Error('账号或密码不正确');enter('admin')}catch(reason){setError(reason instanceof Error?reason.message:'登录未完成')}finally{setBusy(false)}};
 if(user)return <>{children(user,logout)}</>;
 return <main className="auth-frame"><section className="panel cloud-login"><p className="eyebrow">FACTORYPULSE · 线上展示版</p><h1>欢迎进入工作空间</h1><p>查看设备风险与维护决策的验收结果。</p><Button className="primary" onClick={()=>enter('viewer')} disabled={busy}>只读用户 · 一键进入</Button><hr/><form onSubmit={e=>{e.preventDefault();void login()}}><h2>管理员登录</h2><label>账号或 ID<input autoComplete="username" required value={account} onChange={e=>setAccount(e.target.value)} placeholder="输入管理员账号或 ID"/></label><label>密码<input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label><div className="ui-form-feedback" aria-live="polite">{error&&<p role="alert" className="error">{error}</p>}</div><Button className="secondary" type="submit" busy={busy} busyLabel="正在登录…">管理员登录</Button></form><p className="hint">线上为公开演示身份，查看与导出冻结验收结果。真实数据导入、排程和审批请使用本地服务版；此登录不保护真实业务数据。</p></section></main>;
}
