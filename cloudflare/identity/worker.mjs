/** Real D1 account API. No database token, password, or administrator account is embedded. */
const ROLE_CODES={开发者:'developer',管理员:'admin',普通用户:'user',只读用户:'viewer'};
const ROLE_LABELS=Object.fromEntries(Object.entries(ROLE_CODES).map(([label,code])=>[code,label]));
const COOKIE='factorypulse_session',TTL=8*3600;
class Failure extends Error{constructor(status,message){super(message);this.status=status}}
const fail=(status,message)=>{throw new Failure(status,message)};
const hex=buffer=>Array.from(new Uint8Array(buffer),x=>x.toString(16).padStart(2,'0')).join('');
export async function sha256(value){return hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))}
function equal(a,b){let result=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)result|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return result===0}
async function verify(password,encoded){
 if(/^[a-f\d]{64}$/i.test(encoded))return equal(await sha256(password),encoded.toLowerCase());
 const parts=encoded.split('$');if(parts.length!==4||parts[0]!=='pbkdf2_sha256')return false;
 const rounds=Number(parts[1]);if(!Number.isInteger(rounds)||rounds<1||rounds>1000000||!/^([a-f\d]{2})+$/i.test(parts[2]))return false;
 const salt=Uint8Array.from(parts[2].match(/../g),x=>parseInt(x,16));
 const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);
 return equal(hex(await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt,iterations:rounds},key,256)),parts[3]);
}
const token=()=>{const bytes=crypto.getRandomValues(new Uint8Array(32));return btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')};
const userView=row=>({user_id:String(row.user_id),username:String(row.user_id),display_name:row.display_name,role:ROLE_CODES[row.role],staff_id:String(row.staff_id),version:row.version});
function password(value){if(typeof value!=='string'||Array.from(value).length<12||Array.from(value).length>256||!value.trim())fail(422,'密码需为12至256个字符，不能全部为空格');return value}
function displayName(value){if(typeof value!=='string'||!value.trim()||Array.from(value.trim()).length>100)fail(422,'请填写100个字符以内的显示名称');return value.trim()}
function staffNumber(role,value){
 if(!ROLE_LABELS[role])fail(422,'请选择有效角色');
 const expected=role==='developer'?0:role==='admin'?-1:null;
 if((value===null||value===undefined||value==='')&&expected!==null)return expected;
 if((typeof value!=='number'&&typeof value!=='string')||String(Number(value))!==String(value).trim()||!Number.isSafeInteger(Number(value)))fail(422,'人员编号必须是整数');
 const number=Number(value);
 if(expected!==null?number!==expected:number<=0)fail(422,'开发者人员编号为0，管理员为-1，公司人员为正整数');
 return number;
}
async function snapshot(db){
 const statements=['SELECT revision FROM fp_identity_revision WHERE id=1','SELECT * FROM auth_users','SELECT * FROM auth_sessions','SELECT * FROM auth_attempts','SELECT * FROM auth_onboarding','SELECT next_id FROM auth_id_sequence WHERE id=1',"SELECT COALESCE(MAX(seq),10000) AS high_id FROM sqlite_sequence WHERE name='auth_users'"];
 const rows=await db.batch(statements.map(sql=>db.prepare(sql)));
 if(!rows[0].results.length||!rows[5].results.length)fail(503,'账号中心结构尚未初始化');
 return {revision:rows[0].results[0].revision,users:rows[1].results,sessions:rows[2].results,attempts:rows[3].results,onboarding:rows[4].results,next:Math.max(10001,rows[5].results[0].next_id,rows[6].results[0].high_id+1,...rows[1].results.map(u=>u.user_id+1))};
}
async function commit(db,state,writes){
 const nonce=token();
 const queries=[['UPDATE fp_identity_revision SET revision=revision+1,commit_nonce=? WHERE id=1 AND revision=?',[nonce,state.revision]],['INSERT INTO fp_identity_guard(id) SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM fp_identity_revision WHERE id=1 AND commit_nonce=?)',[nonce]],...writes];
 try{await db.batch(queries.map(([sql,params=[]])=>db.prepare(sql).bind(...params)))}catch(error){if(/fp_identity_guard_revision/i.test(String(error)))fail(409,'账号记录已变化，请刷新后重新操作');throw error}
}
const audit=(type,id,content)=>['INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)',[type,String(id),JSON.stringify(content),new Date().toISOString()]];
function attempt(state,key){const previous=state.attempts.find(x=>x.attempt_key===key),recent=previous&&Date.parse(previous.window_start)>Date.now()-600000;if(recent&&previous.attempts>=5)fail(429,'尝试次数过多，请10分钟后重试');return ['INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)',[key,recent?previous.attempts+1:1,recent?previous.window_start:new Date().toISOString()]]}
function cookie(request){return request.headers.get('Cookie')?.split(';').map(x=>x.trim()).find(x=>x.startsWith(COOKIE+'='))?.slice(COOKIE.length+1)||''}
const cookieHeader=(value,maxAge)=>`${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=None; Partitioned; Max-Age=${maxAge}`;
async function principal(request,state){const value=cookie(request);if(!value)return null;const digest=await sha256(value),session=state.sessions.find(x=>x.token_hash===digest&&Date.parse(x.expires_at)>Date.now());return session?state.users.find(x=>String(x.user_id)===String(session.user_id)&&x.active===1)||null:null}
function developer(user){if(!user||ROLE_CODES[user.role]!=='developer')fail(403,'此功能需要开发者权限')}
const requireUser=user=>{if(!user)fail(401,'请先登录');return user};
async function signIn(env,state,row,extra=[]){
 const raw=token(),expires=new Date(Date.now()+TTL*1000).toISOString();
 await commit(env.DB,state,[['DELETE FROM auth_sessions WHERE expires_at<=?',[new Date().toISOString()]],['INSERT INTO auth_sessions VALUES (?,?,?)',[await sha256(raw),String(row.user_id),expires]],...extra]);
 return [{success:true,user:userView(row)},cookieHeader(raw,TTL)];
}
async function body(request){if(Number(request.headers.get('Content-Length')||0)>16384)fail(413,'输入内容过长');const text=await request.text();if(text.length>16384)fail(413,'输入内容过长');try{const value=JSON.parse(text||'{}');if(!value||typeof value!=='object'||Array.isArray(value))throw Error();return value}catch{fail(422,'请提交有效的表单数据')}}

async function account(request,env,path){
 const state=await snapshot(env.DB),user=await principal(request,state),guest=env.GUEST_USER_ID&&state.users.find(x=>String(x.user_id)===env.GUEST_USER_ID&&x.role==='只读用户'&&x.active===1);
 if(path==='/api/auth/status'&&request.method==='GET'){
  const progress=user&&state.onboarding.find(x=>String(x.user_id)===String(user.user_id));
  return [{required:true,setup_needed:!state.users.length,mode:'accounts',identity_provider:'cloudflare_d1',guest_available:!!guest,user:user?userView(user):null,onboarding:user?{step:progress?.step||0,completed_at:progress?.completed_at||null,total_steps:5}:null}];
 }
 if(path==='/api/auth/users'&&request.method==='GET'){developer(user);return [{records:state.users.map(row=>({...userView(row),active:row.active}))}]}
 if(request.method!=='POST')fail(405,'不支持此操作');
 const payload=await body(request);
 if(path==='/api/auth/bootstrap')fail(403,'账号中心由所有者配置，不自动创建默认账号');
 if(path==='/api/auth/login'){
  const id=String(payload.username??payload.user_id??'').trim();if(!/^\d{5,15}$/.test(id)||typeof payload.password!=='string'||payload.password.length>256)fail(401,'账号或密码不正确');
  const key=await sha256(id+'/'+(request.headers.get('CF-Connecting-IP')||'unknown'));
  await commit(env.DB,state,[attempt(state,key)]);
  const row=state.users.find(x=>String(x.user_id)===id);
  if(!row||row.active!==1||!await verify(payload.password,row.password_hash))fail(401,'账号或密码不正确');
  const current=await snapshot(env.DB),fresh=current.users.find(x=>String(x.user_id)===id&&x.active===1&&x.password_hash===row.password_hash);
  if(!fresh)fail(401,'账号状态已变化，请重新登录');
  return signIn(env,current,fresh,[['DELETE FROM auth_attempts WHERE attempt_key=?',[key]]]);
 }
 if(path==='/api/auth/guest'){if(!guest)fail(503,'未配置免密只读访客账号');return signIn(env,state,guest)}
 if(path==='/api/auth/logout'){
  const raw=cookie(request);if(raw)await commit(env.DB,state,[['DELETE FROM auth_sessions WHERE token_hash=?',[await sha256(raw)]]]);
  return [{success:true},cookieHeader('',0)];
 }
 requireUser(user);
 if(path==='/api/auth/onboarding'){
  const old=state.onboarding.find(x=>String(x.user_id)===String(user.user_id)),step=old?.step||0;
  if(!Number.isInteger(payload.step)||payload.step<0||payload.step>5)fail(422,'教程步骤无效');if(payload.step>step+1)fail(409,'请按顺序完成新手教程');
  const target=Math.max(step,payload.step),completed=old?.completed_at||(target===5?new Date().toISOString():null);
  const writes=[['INSERT INTO auth_onboarding(user_id,step,completed_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET step=excluded.step,completed_at=excluded.completed_at',[String(user.user_id),target,completed]]];
  if(completed&&!old?.completed_at)writes.push(audit('onboarding_completed',user.user_id,{actor_user_id:String(user.user_id),actor_role:ROLE_CODES[user.role]}));
  await commit(env.DB,state,writes);return [{step:target,completed_at:completed,total_steps:5}];
 }
 if(path==='/api/auth/password'){
  if(guest&&String(user.user_id)===String(guest.user_id))fail(403,'共享访客不能修改密码');
  password(payload.new_password);if(payload.current_password===payload.new_password)fail(422,'新密码不能与当前密码相同');
  const key='password-change/'+user.user_id;
  if(typeof payload.current_password!=='string'||!await verify(payload.current_password,user.password_hash)){await commit(env.DB,state,[attempt(state,key)]);fail(422,'当前密码不正确')}
  await commit(env.DB,state,[['UPDATE auth_users SET password_hash=?,version=version+1 WHERE user_id=?',[await sha256(payload.new_password),user.user_id]],['DELETE FROM auth_sessions WHERE user_id=?',[String(user.user_id)]],['DELETE FROM auth_attempts WHERE attempt_key=?',[key]],audit('auth_password_changed',user.user_id,{actor_user_id:String(user.user_id)})]);
  return [{success:true},cookieHeader('',0)];
 }
 if(path==='/api/auth/profile'){
  if(!['developer','admin'].includes(ROLE_CODES[user.role]))fail(403,'当前角色不能修改账号名称');
  if(payload.version!==user.version)fail(409,'账号信息已更新，请刷新');
  const name=displayName(payload.display_name);
  await commit(env.DB,state,[['UPDATE auth_users SET display_name=?,version=version+1 WHERE user_id=?',[name,user.user_id]],audit('auth_profile_updated',user.user_id,{actor_user_id:String(user.user_id)})]);
  return [{success:true,version:user.version+1}];
 }
 if(path==='/api/auth/users'){
  developer(user);const name=displayName(payload.display_name),staff=staffNumber(payload.role,payload.staff_id),encoded=await sha256(password(payload.password)),identifier=state.next;
  await commit(env.DB,state,[['UPDATE auth_id_sequence SET next_id=? WHERE id=1',[identifier+1]],['INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash,active,version) VALUES (?,?,?,?,?,1,1)',[identifier,name,ROLE_LABELS[payload.role],staff,encoded]],audit('auth_user_created',identifier,{role:payload.role,actor_user_id:String(user.user_id)})]);
  return [{success:true,user_id:String(identifier)}];
 }
 const update=/^\/api\/auth\/users\/(\d+)$/.exec(path);
 if(update){
  developer(user);const row=state.users.find(x=>String(x.user_id)===update[1]);if(!row)fail(404,'账号不存在');
  if(guest&&String(row.user_id)===String(guest.user_id))fail(403,'共享访客权限由部署配置管理');
  if(payload.version!==row.version)fail(409,'账号信息已更新，请刷新');
  const name=displayName(payload.display_name);if(name!==row.display_name&&row.user_id!==user.user_id)fail(403,'名称只能由账号本人修改');
  if(typeof payload.active!=='boolean')fail(422,'请选择账号启用状态');
  if(row.role==='开发者'&&row.active===1&&(!payload.active||payload.role!=='developer')&&state.users.filter(x=>x.role==='开发者'&&x.active===1).length<=1)fail(409,'不能停用或降级最后一个开发者');
  const staff=staffNumber(payload.role,payload.staff_id),writes=[['UPDATE auth_users SET display_name=?,role=?,staff_id=?,active=?,version=version+1 WHERE user_id=?',[name,ROLE_LABELS[payload.role],staff,Number(payload.active),row.user_id]]];
  if(!payload.active)writes.push(['DELETE FROM auth_sessions WHERE user_id=?',[String(row.user_id)]]);
  writes.push(audit('auth_user_updated',row.user_id,{role:payload.role,active:payload.active,actor_user_id:String(user.user_id)}));
  await commit(env.DB,state,writes);return [{success:true,version:row.version+1}];
 }
 fail(404,'请求的账号接口不存在');
}

export default{async fetch(request,env){
 const url=new URL(request.url),origin=request.headers.get('Origin'),allowed=new Set((env.ALLOWED_ORIGINS||'https://observl.github.io,http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000').split(',').map(x=>x.trim()).filter(Boolean));allowed.add(url.origin);
 const headers=new Headers({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Vary':'Origin'});
 if(origin&&allowed.has(origin)){headers.set('Access-Control-Allow-Origin',origin);headers.set('Access-Control-Allow-Credentials','true')}
 const json=(value,status=200,cookie)=>{const h=new Headers(headers);h.set('Content-Type','application/json; charset=utf-8');if(cookie)h.set('Set-Cookie',cookie);return new Response(JSON.stringify(value),{status,headers:h})};
 try{
  if(origin&&!allowed.has(origin))fail(403,'此来源不能访问账号服务');
  if(request.method==='OPTIONS'){headers.set('Access-Control-Allow-Methods','GET,POST,HEAD,OPTIONS');headers.set('Access-Control-Allow-Headers','Content-Type');headers.set('Access-Control-Max-Age','600');return new Response(null,{status:204,headers})}
  if(!['GET','HEAD'].includes(request.method)&&!origin)fail(403,'账号写入请求需要可信来源');
  if(url.pathname==='/api/health')return json({status:'ok',service:'factorypulse-identity',identity_provider:'cloudflare_d1',business_configured:!!env.BUSINESS_API_ORIGIN});
  if(!url.pathname.startsWith('/api/')&&env.ASSETS&&['GET','HEAD'].includes(request.method))return env.ASSETS.fetch(request);
  if(!env.DB)fail(503,'账号数据库尚未绑定');
  if(url.pathname.startsWith('/api/auth/')){const [value,setCookie]=await account(request,env,url.pathname);return json(value,200,setCookie)}
  if(url.pathname.startsWith('/api/')){
   const state=await snapshot(env.DB);requireUser(await principal(request,state));
   if(!env.BUSINESS_API_ORIGIN)fail(503,'账号已连接；设备与维修业务服务尚未部署，当前无法加载业务数据。');
   const upstream=new URL(env.BUSINESS_API_ORIGIN);if(upstream.protocol!=='https:'||upstream.pathname!=='/'||upstream.username||upstream.password)fail(503,'业务服务地址配置无效');
   const target=new URL(url.pathname+url.search,upstream),forward=new Headers(request.headers);forward.delete('Host');forward.delete('CF-Connecting-IP');
   const response=await fetch(target,{method:request.method,headers:forward,body:['GET','HEAD'].includes(request.method)?undefined:request.body,redirect:'manual'});
   const out=new Headers(response.headers);for(const [key,value] of headers)out.set(key,value);return new Response(response.body,{status:response.status,headers:out});
  }
  return json({detail:'请求的服务接口不存在'},404);
 }catch(error){if(error instanceof Failure)return json({detail:error.message},error.status);return json({detail:'账号中心暂时无法完成操作，请稍后重试。'},503)}
}};
