const API='https://api.dify.ai/v1';
const encode=value=>btoa(JSON.stringify(value)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const decode=value=>JSON.parse(atob(value.replace(/-/g,'+').replace(/_/g,'/')));
async function signingKey(secret){return crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign','verify'])}
const signature=async(key,value)=>Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(value)))).map(x=>x.toString(16).padStart(2,'0')).join('');
export async function sessionToken(secret,scope,id){const payload=encode({scope,id,expires:Date.now()+8*3600000});return payload+'.'+await signature(await signingKey(secret),payload)}
export async function conversationId(secret,scope,token){
 if(!token)return '';
 try{const [payload,sig,...extra]=token.split('.');if(extra.length||!/^[a-f0-9]{64}$/.test(sig))throw Error();const bytes=Uint8Array.from(sig.match(/../g),x=>parseInt(x,16));if(!await crypto.subtle.verify('HMAC',await signingKey(secret),bytes,new TextEncoder().encode(payload)))throw Error();const value=decode(payload);if(value.scope!==scope||value.expires<Date.now()||typeof value.id!=='string')throw Error();return value.id}catch{throw new Error('会话已过期，请新建对话。')}
}
function workflowAnswer(value,field){const outputs=value?.data?.outputs||{};const answer=outputs[field||'answer']??outputs.text??outputs.result;return typeof answer==='string'?answer:''}
export function safeDifyError(value,secret=''){
 let message=typeof value==='string'?value:'工作流运行失败。';
 if(secret)message=message.split(secret).join('[已隐藏]');
 return message.replace(/\b(?:app-|sk-)[a-zA-Z0-9_-]+/g,'[已隐藏]').replace(/Bearer\s+[^\s"']+/gi,'Bearer [已隐藏]').replace(/((?:api[_ -]?key|token|password|secret)["']?\s*[:=]\s*["']?)[^\s,"'}]+/gi,'$1[已隐藏]').slice(0,350);
}
export async function readDify(response,field,secret=''){
 if(response.headers.get('Content-Type')?.includes('application/json')){const value=await response.json();return {answer:value.answer||workflowAnswer(value,field),conversation:value.conversation_id||''}}
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',answer='',conversation='',ended=false,total=0;
 try{
  while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>4*1024*1024)throw new Error('回答过长，请缩小问题范围。');buffer=(buffer+decoder.decode(value,{stream:true})).replace(/\r\n/g,'\n');let split;
   while((split=buffer.indexOf('\n\n'))!==-1){const frame=buffer.slice(0,split);buffer=buffer.slice(split+2);const data=frame.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');if(!data||data==='[DONE]')continue;const event=JSON.parse(data);
    if(event.event==='error')throw new Error('Dify：'+safeDifyError(event.message||event.error,secret));
    if(event.conversation_id)conversation=event.conversation_id;
    if(['message','agent_message'].includes(event.event))answer+=event.answer||'';
    if(event.event==='message_replace')answer=event.answer||'';
    if(event.event==='message_end')ended=true;
    if(event.event==='workflow_finished'){if(event.data?.status!=='succeeded')throw new Error('Dify：'+safeDifyError(event.data?.error,secret));answer=workflowAnswer(event,field)||answer;ended=true}
   }
  }
 }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
 if(!ended)throw new Error('Dify 回答中断，请重试。');return {answer,conversation};
}
/** Called only after the site's normal account authentication. */
export async function dify(request,env,user,fetcher=fetch){
 const path=new URL(request.url).pathname;if(!path.startsWith('/api/copilot/dify/'))return null;
 const reply=(body,status=200)=>Response.json(body,{status,headers:{'Cache-Control':'no-store'}});
 const mode='workflow';
 const stub=env.IDENTITY_RUNTIME?.get(env.IDENTITY_RUNTIME.idFromName('identity-runtime-v1'));
 const stored=stub?await (await stub.fetch('https://identity.internal/dify-config-get',{method:'POST',body:JSON.stringify({user_id:String(user.user_id)})})).json():null;
 const secret=stored?.api_key||env.DIFY_API_KEY,inputField=stored?.input_field||env.DIFY_INPUT_FIELD||'question',outputField=stored?.output_field||env.DIFY_OUTPUT_FIELD||'answer';
 const publicConfig=()=>({provider:'dify',ready:!!secret,mode,api_base:API,input_field:inputField,output_field:outputField,version:stored?.version||0});
 if(path==='/api/copilot/dify/config'){
  if(request.method==='GET')return reply(publicConfig());
  if(request.method!=='POST')return reply({detail:'不支持此操作。'},405);
  let value;try{const text=await request.text();if(text.length>2000)return reply({detail:'配置过长。'},413);value=JSON.parse(text)}catch{return reply({detail:'配置格式错误。'},400)}
  if(typeof value.api_key!=='string'||value.api_key.length>512||(value.api_key&&!/^app-[a-zA-Z0-9_-]+$/.test(value.api_key))||(!value.api_key&&!secret))return reply({detail:'请输入 Dify 应用 API Key。'},422);
  if(![value.input_field,value.output_field].every(field=>typeof field==='string'&&/^[a-zA-Z_][a-zA-Z0-9_]{0,63}$/.test(field)))return reply({detail:'请填写工作流输入和输出变量名。'},422);
  if(!stub)return reply({detail:'配置存储未连接。'},503);
  const saved=await stub.fetch('https://identity.internal/dify-config-set',{method:'POST',body:JSON.stringify({...value,user_id:String(user.user_id)})});const result=await saved.json();return reply(result,saved.status);
 }
 if(path==='/api/copilot/dify/test'&&request.method==='POST'){
  if(!secret)return reply({detail:'请先保存 API Key。'},503);
  let response;
  try{response=await fetcher(API+'/parameters',{headers:{Authorization:'Bearer '+secret,Accept:'application/json'},signal:AbortSignal.timeout(25000),redirect:'follow'})}catch(error){return reply({detail:error.name==='TimeoutError'||error.name==='AbortError'?'Dify 连接超时，请稍后重试（DIFY_TIMEOUT）。':'线上服务到 Dify 的网络连接失败（DIFY_NETWORK）。'},502)}
  if(!response.ok){await response.body?.cancel();return reply({detail:[401,403].includes(response.status)?`Dify 拒绝访问，请核对应用 API Key（HTTP ${response.status}）。`:response.status===429?'Dify 请求或额度受限（HTTP 429）。':`Dify 参数接口返回 HTTP ${response.status}，请检查应用发布状态。`},502)}
  let parameters;try{parameters=await response.json()}catch{return reply({detail:'Dify 返回了非 JSON 内容（DIFY_RESPONSE_FORMAT）。'},502)}
  const form=Array.isArray(parameters.user_input_form)?parameters.user_input_form:[];
  const variables=form.filter(item=>item&&typeof item==='object').flatMap(item=>Object.values(item)).filter(item=>item&&typeof item==='object'&&typeof item.variable==='string').map(item=>({name:item.variable,required:!!item.required}));
  return reply({success:true,variables,message:'连接成功。'});
 }
 if(path==='/api/copilot/dify/status'&&request.method==='GET')return reply({provider:'dify',ready:!!secret,mode,message:secret?'Dify 已配置':'请配置 Dify 应用 API Key。'});
 if(path!=='/api/copilot/dify/chat'||request.method!=='POST')return reply({detail:'接口不存在。'},404);
 if(!secret)return reply({detail:'请先配置 Dify 应用 API Key。'},503);
 if(Number(request.headers.get('Content-Length'))>24000)return reply({detail:'问题过长。'},413);
 let body;try{const text=await request.text();if(text.length>12000)return reply({detail:'问题过长。'},413);body=JSON.parse(text)}catch{return reply({detail:'请求格式错误。'},400)}
 if(typeof body.question!=='string'||!body.question.trim()||body.question.length>4000)return reply({detail:'请输入 1–4000 字的问题。'},422);
 const scope=`${user.user_id}:${user.version}:${user.role}:${mode}`;
 let previous;try{previous=await conversationId(secret,scope,body.session||'')}catch(error){return reply({detail:error.message},409)}
 const context=typeof body.context==='string'?body.context.slice(0,1200):'';
 const query=(context?'页面定位信息：'+context+'\n\n':'')+body.question.trim();
 const inputs=mode==='workflow'?{[inputField]:query}:{};
 const payload={inputs,response_mode:'streaming',user:'factorypulse:'+user.user_id,...(mode==='chat'?{query,conversation_id:previous}: {})};
 const controller=new AbortController(),abort=()=>controller.abort();request.signal.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,120000);
 let stage='network';
 try{
  const response=await fetcher(API+(mode==='chat'?'/chat-messages':'/workflows/run'),{method:'POST',headers:{Authorization:'Bearer '+secret,'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal,redirect:'follow'});
  if(!response.ok){await response.body?.cancel();return reply({detail:[401,403].includes(response.status)?'Dify API Key 无效或无权访问此应用。':response.status===429?'Dify 请求过多或额度不足，请稍后重试。':'Dify 调用失败，请检查应用类型、输入变量和发布状态。'},502)}
  stage='response';const result=await readDify(response,outputField,secret);if(!result.answer)return reply({detail:'Dify 未返回文本回答，请检查输出变量。'},502);
  return reply({answer:result.answer,session:result.conversation?await sessionToken(secret,scope,result.conversation):'',provider:'dify'});
 }catch(error){return reply({detail:controller.signal.aborted?'Dify 响应超时，请重试。':error.message.startsWith('Dify')||error.message.startsWith('回答过长')?error.message:stage==='response'?'Dify 返回内容无法解析（DIFY_RESPONSE_PARSE）。':'无法连接 Dify 运行接口（DIFY_RUN_NETWORK）。'},502)}finally{clearTimeout(timer);request.signal.removeEventListener('abort',abort)}
}
